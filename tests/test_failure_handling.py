from pathlib import Path

from sqlalchemy import select

from app.db.models import Certificate, CertificateStatus, GenerationJob, JobStatus
from app.services.job_service import process_generation_job


def test_one_certificate_failure_does_not_stop_later_recipients(app, valid_payload, monkeypatch):
    from app.services import job_service

    created = []

    def fail_middle(*, template_path, output_path, recipient_name, **kwargs):
        created.append(recipient_name)
        if recipient_name == "Priya Kumar":
            raise RuntimeError("simulated renderer failure")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setattr(job_service, "generate_certificate_pdf", fail_middle)
    from app.schemas.certificate import CreateCertificateJobRequest
    with app.state.session_factory() as session:
        job = job_service.create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        job_id = job.id

    process_generation_job(job_id, app.state.session_factory, app.state.settings)
    with app.state.session_factory() as session:
        job = session.get(GenerationJob, job_id)
        certificates = session.scalars(
            select(Certificate).where(Certificate.job_id == job_id).order_by(Certificate.sequence)
        ).all()
        assert created == ["Rahul Sharma", "Priya Kumar", "Amit Singh"]
        assert [c.status for c in certificates] == [
            CertificateStatus.COMPLETED,
            CertificateStatus.FAILED,
            CertificateStatus.COMPLETED,
        ]
        assert certificates[1].error_message
        assert (job.total_count, job.completed_count, job.successful_count, job.failed_count) == (3, 3, 2, 1)
        assert job.status == JobStatus.COMPLETED_WITH_ERRORS
