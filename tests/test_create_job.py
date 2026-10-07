def test_create_job_returns_accepted_and_persists_job(client, app, valid_payload):
    response = client.post("/api/v1/certificate-jobs", json=valid_payload)

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status"] == "PENDING"
    assert body["total_count"] == 3
    with app.state.session_factory() as session:
        from app.db.models import Certificate, GenerationJob

        job = session.get(GenerationJob, body["job_id"])
        assert job is not None
        assert job.total_count == 3
        assert len(job.certificates) == 3


def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_swagger_docs_are_available(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()
