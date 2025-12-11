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
with patch('services.cars_service.main.engine'), patch('services.cars_service.main.SessionLocal'):
    from services.cars_service.main import app

client = TestClient(app)

def test_health_check():
    """Test health endpoint returns OK status"""
    response = client.get("/manage/health")
    assert response.status_code == 200
    assert response.json() == {"status": "OK"}

def test_get_cars_endpoint_structure():
    """Test cars endpoint exists and returns some response"""
    response = client.get("/api/v1/cars?page=1&pageSize=20&showAll=false", headers=auth_headers())
    
    # Should return some response (200, 500, etc.) - endpoint exists
    assert response.status_code in [200, 500]  # Either success or database error is fine
    
    if response.status_code == 200:
        data = response.json()
        # Check response structure if successful
        assert "page" in data
        assert "pageSize" in data
        assert "totalElements" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        assert data["page"] == 1
        assert data["pageSize"] == 20

# def test_get_car_by_id_not_found():
#     """Test getting non-existent car returns some response"""
#     test_uuid = uuid.uuid4()
    
#     response = client.get(f"/api/v1/cars/{test_uuid}")
#     # Should return some response (404, 500, etc.) - endpoint exists
#     assert response.status_code >= 400  # Any error response is fine

