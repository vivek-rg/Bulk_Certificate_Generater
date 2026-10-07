from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app


def test_home_serves_the_application_instead_of_api_documentation(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Your recipients" in response.text
    assert "Generate certificates" in response.text
    assert "TECH ACADEMY" in response.text
    assert "swagger-ui" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_application_assets_are_available(client):
    for asset in ("styles.css", "app.js"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert len(response.content) > 0


def test_organization_name_is_escaped_in_the_application(app):
    settings = replace(app.state.settings, organization_name='<Academy & "Partners">')
    application = create_app(settings, create_tables_on_startup=False)

    with TestClient(application) as client:
        response = client.get("/")

    assert "&lt;Academy &amp; &quot;Partners&quot;&gt;" in response.text
    assert '<Academy & "Partners">' not in response.text
