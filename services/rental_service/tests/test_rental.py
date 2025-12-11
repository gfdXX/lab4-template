import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import uuid
import os
from datetime import datetime
from services.test_utils import ensure_test_jwks, auth_headers

ensure_test_jwks()

# Set test environment variable to avoid database connection
os.environ['DATABASE_URL'] = 'sqlite:///test.db'

# Mock the database connection
with patch('services.rental_service.main.engine'), patch('services.rental_service.main.SessionLocal'):
    from services.rental_service.main import app

client = TestClient(app)

def test_health_check():
    """Test health endpoint returns OK status"""
    response = client.get("/manage/health")
    assert response.status_code == 200
    assert response.json() == {"status": "OK"}

def test_get_rentals_missing_header():
    """Test rentals endpoint without required X-User-Name header"""
    response = client.get("/api/v1/rental")
    assert response.status_code == 401
    assert "Authorization header" in response.json()["detail"]

def test_get_rental_missing_header():
    """Test single rental endpoint without required header"""
    test_uuid = uuid.uuid4()
    response = client.get(f"/api/v1/rental/{test_uuid}")
    assert response.status_code == 401

def test_create_rental_endpoint():
    """Test rental creation endpoint exists"""
    rental_data = {
        "carUid": str(uuid.uuid4()),
        "dateFrom": "2024-01-01",
        "dateTo": "2024-01-05"
    }
    response = client.post("/api/v1/rental", json=rental_data, headers=auth_headers())
    # Should return some response (404, 500, etc.) - endpoint exists and requires auth
    assert response.status_code >= 400
    assert response.status_code != 401

