from fastapi.testclient import TestClient

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings


def test_health() -> None:
    app = create_app(Settings(app_name="Test Inventory"))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "Test Inventory"}


def test_index_renders_app_name() -> None:
    app = create_app(Settings(app_name="Test Inventory"))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Test Inventory" in response.text
    assert "Stage 0 web shell" in response.text
