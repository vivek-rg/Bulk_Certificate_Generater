from sqlalchemy import select

from app.db.models import Certificate


def test_list_and_download_generated_certificate(client, app, valid_payload):
    response = client.post("/api/v1/certificate-jobs", json=valid_payload)
    job_id = response.json()["job_id"]

    listing = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates?page=1&page_size=2")
    assert listing.status_code == 200
    assert listing.json()["total_count"] == 3
    assert len(listing.json()["certificates"]) == 2
    certificate_id = listing.json()["certificates"][0]["certificate_id"]

    download = client.get(f"/api/v1/certificates/{certificate_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-")

    missing = client.get("/api/v1/certificates/00000000-0000-4000-8000-000000000000")
    assert missing.status_code == 404


def test_not_ready_certificate_returns_conflict(client, app, valid_payload):
    from app.schemas.certificate import CreateCertificateJobRequest
    from app.services.job_service import create_job

    with app.state.session_factory() as session:
        job = create_job(session, CreateCertificateJobRequest.model_validate(valid_payload))
        certificate = session.scalar(select(Certificate).where(Certificate.job_id == job.id))
        certificate_id = certificate.id
    # This route-level check uses a pending row; a direct database fixture avoids dispatching work.
    response = client.get(f"/api/v1/certificates/{certificate_id}")
    assert response.status_code == 409
