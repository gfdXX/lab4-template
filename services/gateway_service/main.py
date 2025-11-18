from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
import requests
import os

# FastAPI app
app = FastAPI(title="Gateway Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs
CARS_SERVICE_URL = os.getenv("CARS_SERVICE_URL", "http://cars-service:8070")
RENTAL_SERVICE_URL = os.getenv("RENTAL_SERVICE_URL", "http://rental-service:8060")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8050")

# Pydantic models
class RentalRequest(BaseModel):
    carUid: str
    dateFrom: str
    dateTo: str

class CarResponse(BaseModel):
    carUid: str
    brand: str
    model: str
    registrationNumber: str
    power: int
    price: int
    type: str
    available: bool

class PaymentResponse(BaseModel):
    paymentUid: str
    status: str
    price: int

class RentalResponse(BaseModel):
    rentalUid: str
    status: str
    dateFrom: str
    dateTo: str
    carUid: str
    car: CarResponse
    payment: PaymentResponse

def get_username(x_user_name: str = Header(None)):
    if not x_user_name:
        raise HTTPException(status_code=400, detail="X-User-Name header is required")
    return x_user_name

@app.get("/manage/health")
async def health_check():
    return {"status": "OK"}

@app.get("/api/v1/cars")
async def get_cars(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    show_all: bool = Query(False)
):
    """Get list of available cars"""
    try:
        print(f"Gateway: Requesting cars from {CARS_SERVICE_URL}/api/v1/cars")
        response = requests.get(
            f"{CARS_SERVICE_URL}/api/v1/cars",
            params={"page": page, "pageSize": size, "showAll": show_all}
        )
        print(f"Gateway: Cars service response status: {response.status_code}")
        print(f"Gateway: Cars service response body: {response.text[:200]}...")
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="Cars service error")
    except requests.RequestException as e:
        print(f"Gateway: Cars service error: {e}")
        raise HTTPException(status_code=503, detail="Cars service unavailable")

@app.get("/api/v1/cars/{car_uid}")
async def get_car(car_uid: str):
    """Get car by UID"""
    try:
        response = requests.get(f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}")
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            raise HTTPException(status_code=404, detail="Car not found")
        else:
            raise HTTPException(status_code=response.status_code, detail="Cars service error")
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Cars service unavailable")

@app.get("/api/v1/rental")
async def get_rentals(
    username: str = Depends(get_username),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100)
):
    """Get all rentals for user"""
    try:
        response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental",
            params={"page": page, "pageSize": page_size},
            headers={"X-User-Name": username}
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Rental service error")
        
        rental_data = response.json()
        
        # Aggregate data from other services
        for item in rental_data["items"]:
            # Get car info
            try:
                car_response = requests.get(f"{CARS_SERVICE_URL}/api/v1/cars/{item['carUid']}")
                if car_response.status_code == 200:
                    car_data = car_response.json()
                    item["car"] = {
                        "carUid": car_data["carUid"],
                        "brand": car_data["brand"],
                        "model": car_data["model"],
                        "registrationNumber": car_data["registrationNumber"]
                    }
                else:
                    item["car"] = {}
            except:
                item["car"] = {}
            
            # Get payment info
            try:
                payment_response = requests.get(f"{PAYMENT_SERVICE_URL}/api/v1/payments/{item['paymentUid']}")
                if payment_response.status_code == 200:
                    item["payment"] = payment_response.json()
                else:
                    item["payment"] = {}
            except:
                item["payment"] = {}
        
        return rental_data
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

@app.get("/api/v1/rental/{rental_uid}")
async def get_rental(rental_uid: str, username: str = Depends(get_username)):
    """Get rental by UID"""
    try:
        response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers={"X-User-Name": username}
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Rental service error")
        
        rental_data = response.json()
        
        # Get car info
        try:
            car_response = requests.get(f"{CARS_SERVICE_URL}/api/v1/cars/{rental_data['carUid']}")
            if car_response.status_code == 200:
                car_data = car_response.json()
                rental_data["car"] = {
                    "carUid": car_data["carUid"],
                    "brand": car_data["brand"],
                    "model": car_data["model"],
                    "registrationNumber": car_data["registrationNumber"]
                }
            else:
                rental_data["car"] = {}
        except:
            rental_data["car"] = {}
        
        # Get payment info
        try:
            payment_response = requests.get(f"{PAYMENT_SERVICE_URL}/api/v1/payments/{rental_data['paymentUid']}")
            if payment_response.status_code == 200:
                rental_data["payment"] = payment_response.json()
            else:
                rental_data["payment"] = {}
        except:
            rental_data["payment"] = {}
        
        return rental_data
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

@app.post("/api/v1/rental")
async def create_rental(rental_request: RentalRequest, username: str = Depends(get_username)):
    """Create new rental"""
    try:
        print(f"Gateway: Creating rental for car {rental_request.carUid}, user {username}")
        
        # Step 1: Check if car exists and is available
        car_response = requests.get(f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}")
        if car_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Car not found")
        
        car_data = car_response.json()
        if not car_data.get("available", False):
            raise HTTPException(status_code=400, detail="Car is not available")
        
        # Step 2: Calculate rental days and price
        from datetime import datetime
        try:
            if 'T' in rental_request.dateFrom:
                date_from = datetime.fromisoformat(rental_request.dateFrom.replace('Z', '+00:00'))
            else:
                date_from = datetime.strptime(rental_request.dateFrom, "%Y-%m-%d")
        except ValueError:
            try:
                date_from = datetime.fromisoformat(rental_request.dateFrom)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format for dateFrom")
        
        try:
            if 'T' in rental_request.dateTo:
                date_to = datetime.fromisoformat(rental_request.dateTo.replace('Z', '+00:00'))
            else:
                date_to = datetime.strptime(rental_request.dateTo, "%Y-%m-%d")
        except ValueError:
            try:
                date_to = datetime.fromisoformat(rental_request.dateTo)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format for dateTo")
        
        rental_days = (date_to - date_from).days
        total_price = car_data["price"] * rental_days
        
        # Step 3: Create payment
        payment_data = {"price": total_price}
        payment_response = requests.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/payments",
            json=payment_data
        )
        if payment_response.status_code != 201:
            raise HTTPException(status_code=503, detail="Payment service unavailable")
        payment_info = payment_response.json()
        
        # Step 4: Reserve car
        car_reserve_response = requests.patch(
            f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
            params={"available": False}
        )
        if car_reserve_response.status_code != 200:
            # Rollback payment if car reservation fails
            try:
                requests.delete(f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_info['paymentUid']}")
            except:
                pass
            raise HTTPException(status_code=503, detail="Cars service unavailable")
        
        # Step 5: Create rental record
        rental_data = {
            "carUid": str(rental_request.carUid),
            "dateFrom": str(rental_request.dateFrom),
            "dateTo": str(rental_request.dateTo),
            "paymentUid": payment_info["paymentUid"]
        }
        rental_response = requests.post(
            f"{RENTAL_SERVICE_URL}/api/v1/rental",
            json=rental_data,
            headers={"X-User-Name": username}
        )
        if rental_response.status_code != 200:
            # Rollback car reservation and payment
            try:
                requests.patch(
                    f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
                    params={"available": True}
                )
                requests.delete(f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_info['paymentUid']}")
            except:
                pass
            raise HTTPException(status_code=503, detail="Rental service unavailable")
        
        rental_info = rental_response.json()
        
        # Step 6: Return aggregated response
        return {
            "rentalUid": rental_info["rentalUid"],
            "status": rental_info["status"],
            "carUid": rental_info["carUid"],
            "dateFrom": rental_info["dateFrom"],
            "dateTo": rental_info["dateTo"],
            "payment": payment_info
        }
        
    except requests.RequestException as e:
        print(f"Gateway: Service error: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.post("/api/v1/rental/{rental_uid}/finish")
async def finish_rental(rental_uid: str, username: str = Depends(get_username)):
    """Finish rental"""
    try:
        # Step 1: Get rental info to find car_uid
        rental_response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers={"X-User-Name": username}
        )
        if rental_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif rental_response.status_code != 200:
            raise HTTPException(status_code=rental_response.status_code, detail="Rental service error")
        
        rental_data = rental_response.json()
        car_uid = rental_data["carUid"]
        
        # Step 2: Release car
        car_release_response = requests.patch(
            f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}/availability",
            params={"available": True}
        )
        # Continue even if car service is unavailable
        
        # Step 3: Update rental status
        finish_response = requests.post(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}/finish",
            headers={"X-User-Name": username}
        )
        if finish_response.status_code == 204:
            from fastapi import Response
            return Response(status_code=204)
        elif finish_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        else:
            raise HTTPException(status_code=finish_response.status_code, detail="Rental service error")
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

@app.delete("/api/v1/rental/{rental_uid}")
async def cancel_rental(rental_uid: str, username: str = Depends(get_username)):
    """Cancel rental"""
    try:
        # Step 1: Get rental info to find car_uid and payment_uid
        rental_response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers={"X-User-Name": username}
        )
        if rental_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif rental_response.status_code != 200:
            raise HTTPException(status_code=rental_response.status_code, detail="Rental service error")
        
        rental_data = rental_response.json()
        car_uid = rental_data["carUid"]
        payment_uid = rental_data["paymentUid"]
        
        # Step 2: Release car
        car_release_response = requests.patch(
            f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}/availability",
            params={"available": True}
        )
        # Continue even if car service is unavailable
        
        # Step 3: Cancel payment
        payment_cancel_response = requests.delete(
            f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_uid}"
        )
        # Continue even if payment service is unavailable
        
        # Step 4: Update rental status
        cancel_response = requests.delete(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers={"X-User-Name": username}
        )
        if cancel_response.status_code == 204:
            from fastapi import Response
            return Response(status_code=204)
        elif cancel_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        else:
            raise HTTPException(status_code=cancel_response.status_code, detail="Rental service error")
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

