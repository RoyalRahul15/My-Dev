
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app import app

client = TestClient(app)

# Fixture to mock environment variables
@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("GCP_LOGGER_NAME", "logging-service")
    monkeypatch.setenv("GCP_PROJECT_ID", "mock-project-id")

# Fixture to mock GCP logger methods
@pytest.fixture
def mock_gcp_logger():
    with patch("extensions.gcp_logger.GCPLOGGER.write_to_gcp") as mock_write, \
         patch("extensions.gcp_logger.GCPLOGGER.fetch_logs") as mock_fetch:
        yield mock_write, mock_fetch

# Test: Valid log creation
def test_post_log_success(mock_gcp_logger):
    mock_write, _ = mock_gcp_logger
    payload = {
        "log_type": "INFO",
        "service_name": "control-plane",
        "data": {"message": "test log"}
    }
    response = client.post("/api/v1/log", json=payload)
    assert response.status_code == 200
    assert "successfully" in response.json()["message"].lower()
    mock_write.assert_called_once()

# Test: Invalid payload
def test_post_log_invalid():
    response = client.post("/api/v1/log", json={
        "service_name": "missing-log-type",
        "data": {"message": "error"}
    })
    assert response.status_code == 422

# Test: Log retrieval with data
def test_get_logs_with_data(mock_gcp_logger):
    _, mock_fetch = mock_gcp_logger
    mock_fetch.return_value = [
        {"log_type": "INFO", "service_name": "control-plane", "message": "test A"},
        {"log_type": "ERROR", "service_name": "control-plane", "message": "test B"}
    ]
    response = client.get("/api/v1/logs")
    assert response.status_code == 200
    assert isinstance(response.json()["logs"], list)
    assert len(response.json()["logs"]) == 2

# Test: Empty log fetch
def test_get_logs_empty(mock_gcp_logger):
    _, mock_fetch = mock_gcp_logger
    mock_fetch.return_value = []
    response = client.get("/api/v1/logs")
    assert response.status_code == 200
    assert response.json()["logs"] == []

# Test: Health check OK
def test_health_ok(mock_gcp_logger):
    _, mock_fetch = mock_gcp_logger
    mock_fetch.return_value = []
    response = client.get("/")
    assert response.status_code == 200
    assert "running" in response.json()["message"].lower()

# Test: Health check with error
def test_health_error():
    with patch("extensions.gcp_logger.GCPLOGGER.fetch_logs", side_effect=Exception("Down")):
        response = client.get("/")
        assert response.status_code == 500
        assert "error" in response.json()["message"].lower()
