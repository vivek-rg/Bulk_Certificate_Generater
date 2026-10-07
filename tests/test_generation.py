from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from app.db.models import Certificate, CertificateStatus, GenerationJob, JobStatus


def test_job_generates_a_pdf_and_tracks_progress(client, app, valid_payload):
    response = client.post("/api/v1/certificate-jobs", json=valid_payload)
    job_id = response.json()["job_id"]
    with app.state.session_factory() as session:
        job = session.get(GenerationJob, job_id)
        certificates = session.scalars(select(Certificate).where(Certificate.job_id == job_id)).all()
        assert job is not None
        assert len(certificates) == 3
        assert all(certificate.status == CertificateStatus.COMPLETED for certificate in certificates)
        assert all(certificate.certificate_number for certificate in certificates)
        assert all(Path(certificate.file_path).is_file() for certificate in certificates)
        pdf_text = PdfReader(certificates[0].file_path).pages[0].extract_text()
        assert "TECH ACADEMY" in pdf_text
        assert certificates[0].recipient_name in pdf_text
        assert certificates[0].certificate_title in pdf_text
        assert certificates[0].certificate_number in pdf_text
        assert job.status == JobStatus.COMPLETED
        assert (job.total_count, job.completed_count, job.successful_count, job.failed_count) == (3, 3, 3, 0)

    status_response = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["progress_percentage"] == 100.0
