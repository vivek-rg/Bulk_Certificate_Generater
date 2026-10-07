from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Base, get_db
from app.main import create_app


@pytest.fixture
def app(tmp_path: Path):
    database_path = tmp_path / "test.db"
    template_path = Path(__file__).resolve().parents[1] / "templates" / "certificate_template.pdf"
    settings = Settings(
        database_url=f"sqlite:///{database_path.as_posix()}",
        generated_files_dir=tmp_path / "generated",
        template_path=template_path,
    )
    application = create_app(settings)
    engine = application.state.engine
    Base.metadata.create_all(engine)
    factory = application.state.session_factory

    def override_get_db(request: Request):
        with factory() as session:
            session.info["generated_files_dir"] = settings.generated_files_dir
            yield session

    application.dependency_overrides[get_db] = override_get_db
    yield application
    engine.dispose()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_payload() -> dict:
    return {
        "certificate_title": "Python Programming Certification",
        "certificate_date": date(2026, 10, 7).isoformat(),
        "recipients": [
            {"name": "Rahul Sharma", "email": "rahul@example.com"},
            {"name": "Priya Kumar", "email": "priya@example.com"},
            {"name": "Amit Singh", "email": "amit@example.com"},
        ],
    }
