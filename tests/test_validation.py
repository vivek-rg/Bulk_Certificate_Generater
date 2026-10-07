import pytest


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(recipients=[]),
        lambda payload: payload["recipients"][0].update(email="not-an-email"),
        lambda payload: payload["recipients"][0].pop("name"),
        lambda payload: payload["recipients"][0].update(name="   "),
        lambda payload: payload["recipients"][0].update(name="x" * 121),
        lambda payload: payload.update(certificate_title=" "),
        lambda payload: payload.pop("certificate_title"),
        lambda payload: payload.update(certificate_date="not-a-date"),
    ],
)
def test_invalid_job_payload_returns_422(client, valid_payload, mutate):
    mutate(valid_payload)
    response = client.post("/api/v1/certificate-jobs", json=valid_payload)
    assert response.status_code == 422
