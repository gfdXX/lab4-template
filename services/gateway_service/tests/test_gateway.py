import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import uuid
from services.test_utils import ensure_test_jwks, auth_headers

ensure_test_jwks()
from services.gateway_service.main import app

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

def test_get_cars_through_gateway():
    """Test cars endpoint through gateway with mocked service response"""
    mock_cars_data = {
        "page": 1,
        "pageSize": 20,
        "totalElements": 1,
        "items": [
            {
                "carUid": "109b42f3-198d-4c89-9276-a7520a7120ab",
                "brand": "Mercedes Benz",
                "model": "GLA 250",
                "registrationNumber": "ЛО777Х799",
                "power": 249,
                "price": 3500,
                "type": "SEDAN",
                "available": True
            }
        ]
    }
    
    with patch('services.gateway_service.main.requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_cars_data
        mock_get.return_value = mock_response
        
        response = client.get(
            "/api/v1/cars?page=1&size=20&show_all=false",
            headers=auth_headers(),
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["totalElements"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["brand"] == "Mercedes Benz"
        assert data["items"][0]["available"] == True

def test_create_rental_through_gateway():
    """Test rental creation through gateway with mocked service response"""
    rental_data = {
        "carUid": "109b42f3-198d-4c89-9276-a7520a7120ab",
        "dateFrom": "2024-01-01",
        "dateTo": "2024-01-05"
    }
    
    # Mock car data
    mock_car_data = {
        "carUid": "109b42f3-198d-4c89-9276-a7520a7120ab",
        "brand": "Mercedes Benz",
        "model": "GLA 250",
        "registrationNumber": "ЛО777Х799",
        "power": 249,
        "price": 3500,
        "type": "SEDAN",
        "available": True
    }
    
    # Mock payment response
    mock_payment_response = {
        "paymentUid": str(uuid.uuid4()),
        "status": "PAID",
        "price": 14000
    }
    
    # Mock rental response
    mock_rental_response = {
        "rentalUid": str(uuid.uuid4()),
        "status": "IN_PROGRESS",
        "dateFrom": "2024-01-01",
        "dateTo": "2024-01-05",
        "carUid": "109b42f3-198d-4c89-9276-a7520a7120ab",
        "paymentUid": mock_payment_response["paymentUid"]
    }
    
    with patch('services.gateway_service.main.requests.get') as mock_get, \
         patch('services.gateway_service.main.requests.post') as mock_post, \
         patch('services.gateway_service.main.requests.patch') as mock_patch:
        
        # Mock car availability check
        car_response = MagicMock()
        car_response.status_code = 200
        car_response.json.return_value = mock_car_data
        
        # Mock payment creation
        payment_response = MagicMock()
        payment_response.status_code = 201
        payment_response.json.return_value = mock_payment_response
        
        # Mock car reservation
        car_reserve_response = MagicMock()
        car_reserve_response.status_code = 200
        
        # Mock rental creation
        rental_response = MagicMock()
        rental_response.status_code = 200
        rental_response.json.return_value = mock_rental_response
        
        # Configure mocks to return appropriate responses based on URL
        def mock_get_side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get('url', '')
            if 'cars' in url and 'availability' not in url:
                return car_response
            return MagicMock()
        
        def mock_post_side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get('url', '')
            if 'payments' in url:
                return payment_response
            elif 'rental' in url:
                return rental_response
            return MagicMock()
        
        def mock_patch_side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get('url', '')
            if 'availability' in url:
                return car_reserve_response
            return MagicMock()
        
        mock_get.side_effect = mock_get_side_effect
        mock_post.side_effect = mock_post_side_effect
        mock_patch.side_effect = mock_patch_side_effect
        
        response = client.post(
            "/api/v1/rental", 
            json=rental_data, 
            headers=auth_headers()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "IN_PROGRESS"
        assert data["carUid"] == "109b42f3-198d-4c89-9276-a7520a7120ab"
        assert data["payment"]["status"] == "PAID"
        assert data["payment"]["price"] == 14000

