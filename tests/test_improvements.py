import io
from pathlib import Path
import zipfile
import pytest
from sqlalchemy import select

from app.db.models import Certificate, CertificateStatus, GenerationJob, JobStatus
from app.schemas.certificate import CreateCertificateJobRequest
from app.services.job_service import create_job, recover_interrupted_jobs, _process_generation_job
from app.core.config import Settings


def test_download_all_certificates_zip(client, valid_payload):
    # Create job and let background tasks run
    response = client.post("/api/v1/certificate-jobs", json=valid_payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Download zip
    zip_resp = client.get(f"/api/v1/certificate-jobs/{job_id}/zip")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"
    assert "attachment; filename=" in zip_resp.headers["content-disposition"]

    # Verify contents of zip
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as archive:
        namelist = archive.namelist()
        assert len(namelist) == 3
        assert any("Rahul" in name for name in namelist)
        assert any("Priya" in name for name in namelist)
        assert any("Amit" in name for name in namelist)
        for name in namelist:
            assert name.endswith(".pdf")
            data = archive.read(name)
            assert data.startswith(b"%PDF-")


def test_download_zip_not_found(client):
    response = client.get("/api/v1/certificate-jobs/00000000-0000-0000-0000-000000000000/zip")
    assert response.status_code == 404


def test_download_zip_conflict_when_no_certificates_completed(client, app, valid_payload):
    with app.state.session_factory() as session:
        job = create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        job_id = job.id

    response = client.get(f"/api/v1/certificate-jobs/{job_id}/zip")
    assert response.status_code == 409


def test_recover_interrupted_jobs(app, valid_payload):
    with app.state.session_factory() as session:
        job = create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        job.status = JobStatus.PROCESSING
        session.commit()
        job_id = job.id

    recovered = recover_interrupted_jobs(app.state.session_factory)
    assert recovered == 1

    with app.state.session_factory() as session:
        recovered_job = session.get(GenerationJob, job_id)
        assert recovered_job.status == JobStatus.FAILED
        assert recovered_job.completed_at is not None
        certs = session.scalars(select(Certificate).where(Certificate.job_id == job_id)).all()
        assert all(c.status == CertificateStatus.FAILED for c in certs)
        assert all("Interrupted by server restart" in c.error_message for c in certs)


def test_missing_template_fails_job_immediately(app, valid_payload, tmp_path):
    with app.state.session_factory() as session:
        job = create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        job_id = job.id

    settings = Settings(
        database_url=app.state.settings.database_url,
        generated_files_dir=tmp_path / "gen",
        template_path=tmp_path / "nonexistent_template.pdf",
    )

    from app.services.job_service import process_generation_job
    process_generation_job(job_id, app.state.session_factory, settings)

    with app.state.session_factory() as session:
        checked_job = session.get(GenerationJob, job_id)
        assert checked_job.status == JobStatus.FAILED
        certs = session.scalars(select(Certificate).where(Certificate.job_id == job_id)).all()
        assert all(c.status == CertificateStatus.FAILED for c in certs)
        assert all("template is missing" in c.error_message.lower() for c in certs)


def test_partial_completion_status_calculation(app, valid_payload, monkeypatch):
    from app.services import job_service

    call_count = 0

    def fail_after_first(*, template_path, output_path, recipient_name, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise RuntimeError("Renderer crash")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4 sample")

    monkeypatch.setattr(job_service, "generate_certificate_pdf", fail_after_first)

    with app.state.session_factory() as session:
        job = create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        job_id = job.id

    job_service.process_generation_job(job_id, app.state.session_factory, app.state.settings)

    with app.state.session_factory() as session:
        result_job = session.get(GenerationJob, job_id)
        assert result_job.status == JobStatus.COMPLETED_WITH_ERRORS
        assert result_job.successful_count == 1
        assert result_job.failed_count == 2
        assert result_job.completed_count == 3


def test_job_with_signature_image_generates_pdf(client, valid_payload):
    # Minimal 1x1 base64 transparent PNG
    tiny_png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    payload = {**valid_payload, "signature_image": tiny_png}
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status_resp = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "COMPLETED"
    assert status_resp.json()["successful_count"] == 3

