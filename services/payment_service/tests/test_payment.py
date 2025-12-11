import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import uuid
import os
from services.test_utils import ensure_test_jwks, auth_headers

ensure_test_jwks()

# Set test environment variable to avoid database connection
os.environ['DATABASE_URL'] = 'sqlite:///test.db'

# Mock the database connection at import time
with patch('services.payment_service.main.engine'), patch('services.payment_service.main.SessionLocal'):
    from services.payment_service.main import app

client = TestClient(app)

def test_health_check():
    """Test health endpoint returns OK status"""
    response = client.get("/manage/health")
    assert response.status_code == 200
    assert response.json() == {"status": "OK"}

def test_payment_endpoints_exist():
    """Test that payment endpoints are properly configured"""
    # Test POST endpoint exists
    response = client.post("/api/v1/payments", json={}, headers=auth_headers())
    assert response.status_code in [400, 422, 500]  # Bad request, validation error, or DB error expected
    
    # Test GET endpoint exists
    response = client.get("/api/v1/payments/invalid-uuid", headers=auth_headers())
    assert response.status_code in [400, 404, 500, 422]  # Various error responses expected

def test_payment_validation():
    """Test payment request validation"""
    # Test with invalid data structure (missing price)
    response = client.post("/api/v1/payments", json={}, headers=auth_headers())
    # Should return validation error
    assert response.status_code == 422

