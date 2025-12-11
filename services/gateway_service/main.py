from fastapi import FastAPI, HTTPException, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
import requests
import os
import time
import threading
import queue
import psycopg2
from enum import Enum
from threading import Lock
from services.auth import (
    AuthenticatedUser,
    auth_header_for,
    get_current_user,
    get_settings,
)

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
PAYMENT_DATABASE_URL = os.getenv("PAYMENT_DATABASE_URL", "postgresql://program:test@postgres:5432/payments")
AUTH_SETTINGS = get_settings()

# Ensure default audience is the configured issuer if audience is missing.
if not AUTH_SETTINGS.audience and AUTH_SETTINGS.issuer:
    AUTH_SETTINGS.audience = AUTH_SETTINGS.issuer.rstrip("/") + "/api/v2/"

# Circuit Breaker Implementation (from lab3)
class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class SlidingWindow:
    def __init__(self, size=10, window_type="count"):
        self.size = size
        self.window_type = window_type
        self.buckets = [{"failed": 0, "slow": 0, "total": 0} for _ in range(size)]
        self.total_failed = 0
        self.total_slow = 0
        self.total_calls = 0
        self.current_index = 0
        self.lock = Lock()
        
        if window_type == "time":
            self.bucket_start_time = time.time()
    
    def record_call(self, failed=False, slow=False):
        with self.lock:
            if self.window_type == "count":
                self._record_count_based(failed, slow)
            else:
                self._record_time_based(failed, slow)
    
    def _record_count_based(self, failed, slow):
        current_bucket = self.buckets[self.current_index]
        self.total_failed -= current_bucket["failed"]
        self.total_slow -= current_bucket["slow"]
        self.total_calls -= current_bucket["total"]
        
        current_bucket["total"] += 1
        if failed:
            current_bucket["failed"] += 1
            self.total_failed += 1
        if slow:
            current_bucket["slow"] += 1
            self.total_slow += 1
        self.total_calls += 1
        self.current_index = (self.current_index + 1) % self.size
    
    def _record_time_based(self, failed, slow):
        current_time = time.time()
        if current_time - self.bucket_start_time >= 1.0:
            seconds_elapsed = int(current_time - self.bucket_start_time)
            for _ in range(seconds_elapsed):
                old_bucket = self.buckets[self.current_index]
                self.total_failed -= old_bucket["failed"]
                self.total_slow -= old_bucket["slow"]
                self.total_calls -= old_bucket["total"]
                old_bucket["failed"] = 0
                old_bucket["slow"] = 0
                old_bucket["total"] = 0
                self.current_index = (self.current_index + 1) % self.size
            self.bucket_start_time = current_time
        
        current_bucket = self.buckets[self.current_index]
        current_bucket["total"] += 1
        if failed:
            current_bucket["failed"] += 1
            self.total_failed += 1
        if slow:
            current_bucket["slow"] += 1
            self.total_slow += 1
        self.total_calls += 1
    
    def get_failure_rate(self):
        with self.lock:
            if self.total_calls == 0:
                return 0.0
            return self.total_failed / self.total_calls
    
    def get_total_calls(self):
        with self.lock:
            return self.total_calls

class CircuitBreaker:
    def __init__(self, failure_threshold=3, timeout=30, window_size=10, window_type="count"):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        self.lock = Lock()
        self.sliding_window = SlidingWindow(size=window_size, window_type=window_type)
        self.half_open_allowed = 0
        self.half_open_max = 5
    
    def call(self, func, *args, **kwargs):
        with self.lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_allowed = 0
                else:
                    raise Exception("Circuit breaker is OPEN")
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_allowed >= self.half_open_max:
                    raise Exception("Circuit breaker is HALF_OPEN - too many requests")
                self.half_open_allowed += 1
        
        try:
            start_time = time.time()
            result = func(*args, **kwargs)
            call_duration = time.time() - start_time
            is_slow = call_duration > 5.0
            self.sliding_window.record_call(failed=False, slow=is_slow)
            
            with self.lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.half_open_allowed = 0
            
            return result
        except Exception as e:
            self.sliding_window.record_call(failed=True, slow=False)
            with self.lock:
                self.last_failure_time = time.time()
                if self._should_open():
                    self.state = CircuitState.OPEN
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.OPEN
                    self.half_open_allowed = 0
            raise e
    
    def _should_open(self):
        total_calls = self.sliding_window.get_total_calls()
        if total_calls == 0:
            return False
        if 0 < self.failure_threshold <= 1.0:
            failure_rate = self.sliding_window.get_failure_rate()
            return failure_rate >= self.failure_threshold
        failed_count = self.sliding_window.total_failed
        return failed_count >= self.failure_threshold

# Circuit breakers
payment_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)


class RetryQueue:
    """Background retry queue for deferred operations (e.g., payment cancellation)."""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def add_request(self, request_data: dict):
        """Add request to retry queue."""
        self.queue.put(request_data)

    def _process_queue(self):
        while True:
            try:
                request_data = self.queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                self._retry_request(request_data)
            except Exception as e:
                print(f"Retry queue error: {e}")
            finally:
                self.queue.task_done()

    def _retry_request(self, request_data: dict):
        req_type = request_data.get("type")
        time.sleep(5)
        token = request_data.get("token")
        headers = auth_header_for(token) if token else None

        if req_type == "cancel_payment":
            payment_uid = request_data.get("data", {}).get("payment_uid")
            if not payment_uid:
                return

            try:
                response = requests.delete(
                    f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_uid}",
                    headers=headers,
                    timeout=3
                )
                if response.status_code in (200, 204):
                    print(f"Retry succeeded: payment {payment_uid} cancelled")
                    return
            except requests.RequestException as e:
                print(f"Retry payment cancellation failed: {e}")

            # Re-queue if still failing
            self.queue.put(request_data)


retry_queue = RetryQueue()

# Pydantic models
class RentalRequest(BaseModel):
    carUid: str
    dateFrom: str
    dateTo: str

class AuthRequest(BaseModel):
    username: str
    password: str
    scope: Optional[str] = None

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


def force_cancel_payment(payment_uid: str) -> bool:
    """Fallback: mark payment as cancelled directly in DB when payment service is unavailable."""
    try:
        conn = psycopg2.connect(PAYMENT_DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE payment SET status = 'CANCELED' WHERE payment_uid = %s",
            (str(payment_uid),)
        )
        conn.commit()
        updated = cursor.rowcount > 0
        cursor.close()
        conn.close()
        if updated:
            print(f"Payment {payment_uid} status forcibly set to CANCELED in DB")
        return updated
    except Exception as e:
        print(f"Force payment cancellation failed: {e}")
        return False

@app.get("/manage/health")
async def health_check():
    return {"status": "OK"}

@app.post("/api/v1/authorize")
async def authorize(auth_request: AuthRequest):
    """Exchange user credentials for tokens using Resource Owner Password flow."""
    token_url = AUTH_SETTINGS.token_url
    if not token_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC token endpoint is not configured",
        )

    # Auth0 requires password-realm grant type when no default connection is configured.
    # For other providers, the classic password grant with a connection parameter still works.
    connection_name = AUTH_SETTINGS.realm or "Username-Password-Authentication"
    grant_type = "password"
    use_realm = "auth0.com" in token_url or AUTH_SETTINGS.realm is not None

    data = {
        "grant_type": grant_type,
        "client_id": AUTH_SETTINGS.client_id,
        "client_secret": AUTH_SETTINGS.client_secret,
        "username": auth_request.username,
        "password": auth_request.password,
        "scope": auth_request.scope or AUTH_SETTINGS.scope,
    }

    if use_realm:
        data["grant_type"] = "http://auth0.com/oauth/grant-type/password-realm"
        data["realm"] = connection_name
    else:
        data["connection"] = connection_name

    # Add audience if configured (required for Auth0 to return JWT access_token)
    if AUTH_SETTINGS.audience:
        data["audience"] = AUTH_SETTINGS.audience

    try:
        response = requests.post(token_url, data=data, timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Identity provider unavailable") from exc

    if response.status_code >= 400:
        error_detail = response.text
        try:
            error_json = response.json()
            error_detail = error_json.get("error_description", error_json.get("error", "Authorization failed"))
        except:
            pass
        raise HTTPException(status_code=response.status_code, detail=error_detail)

    return response.json()

@app.get("/api/v1/callback")
async def callback(code: Optional[str] = None, state: Optional[str] = None):
    """
    Optional callback handler for Authorization Code flow.
    When code is provided, it is exchanged for tokens; otherwise a simple OK response is returned.
    """
    if not code:
        return {"status": "ok"}

    token_url = AUTH_SETTINGS.token_url
    if not token_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC token endpoint is not configured",
        )

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": AUTH_SETTINGS.redirect_uri,
        "client_id": AUTH_SETTINGS.client_id,
        "client_secret": AUTH_SETTINGS.client_secret,
    }

    try:
        response = requests.post(token_url, data=data, timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Identity provider unavailable") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Token exchange failed")

    return response.json()

@app.get("/api/v1/cars")
async def get_cars(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    show_all: bool = Query(False),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get list of available cars"""
    try:
        response = requests.get(
            f"{CARS_SERVICE_URL}/api/v1/cars",
            params={"page": page, "pageSize": size, "showAll": show_all},
            headers=auth_header_for(user.token),
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(status_code=response.status_code, detail="Cars service error")
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail="Cars service unavailable")

@app.get("/api/v1/cars/{car_uid}")
async def get_car(car_uid: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Get car by UID"""
    try:
        response = requests.get(
            f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}",
            headers=auth_header_for(user.token),
            timeout=5
        )
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
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100)
):
    """Get all rentals for user"""
    try:
        response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental",
            params={"page": page, "pageSize": page_size},
            headers=auth_header_for(user.token),
            timeout=5
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Rental service error")
        
        rental_data = response.json()
        items = rental_data.get("items", rental_data if isinstance(rental_data, list) else [])
        
        for item in items:
            try:
                car_response = requests.get(
                    f"{CARS_SERVICE_URL}/api/v1/cars/{item['carUid']}",
                    headers=auth_header_for(user.token),
                    timeout=3
                )
                if car_response.status_code == 200:
                    car_data = car_response.json()
                    item["car"] = {
                        "carUid": car_data["carUid"],
                        "brand": car_data["brand"],
                        "model": car_data["model"],
                        "registrationNumber": car_data["registrationNumber"]
                    }
                else:
                    item["car"] = {"carUid": item["carUid"]}
            except (requests.RequestException, requests.Timeout):
                item["car"] = {"carUid": item["carUid"]}
            
            try:
                payment_response = requests.get(
                    f"{PAYMENT_SERVICE_URL}/api/v1/payments/{item['paymentUid']}",
                    headers=auth_header_for(user.token),
                    timeout=3
                )
                if payment_response.status_code == 200:
                    item["payment"] = payment_response.json()
                elif payment_response.status_code == 404:
                    item["payment"] = {}
                else:
                    if item.get("status") != "CANCELED":
                        item["payment"] = {"paymentUid": item["paymentUid"]}
                    else:
                        item["payment"] = {}
            except (requests.RequestException, requests.Timeout):
                if item.get("status") != "CANCELED":
                    item["payment"] = {"paymentUid": item["paymentUid"]}
                else:
                    item["payment"] = {}
        
        return items
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

@app.get("/api/v1/rental/{rental_uid}")
async def get_rental(rental_uid: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Get rental by UID"""
    try:
        response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers=auth_header_for(user.token),
            timeout=5
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Rental service error")
        
        rental_data = response.json()
        
        try:
            car_response = requests.get(
                f"{CARS_SERVICE_URL}/api/v1/cars/{rental_data['carUid']}",
                headers=auth_header_for(user.token),
                timeout=3
            )
            if car_response.status_code == 200:
                car_data = car_response.json()
                rental_data["car"] = {
                    "carUid": car_data["carUid"],
                    "brand": car_data["brand"],
                    "model": car_data["model"],
                    "registrationNumber": car_data["registrationNumber"]
                }
            else:
                rental_data["car"] = {"carUid": rental_data["carUid"]}
        except (requests.RequestException, requests.Timeout):
            rental_data["car"] = {"carUid": rental_data["carUid"]}
        
        try:
            payment_response = requests.get(
                f"{PAYMENT_SERVICE_URL}/api/v1/payments/{rental_data['paymentUid']}",
                headers=auth_header_for(user.token),
                timeout=3
            )
            if payment_response.status_code == 200:
                rental_data["payment"] = payment_response.json()
            elif payment_response.status_code == 404:
                rental_data["payment"] = {}
            else:
                if rental_data.get("status") != "CANCELED":
                    rental_data["payment"] = {"paymentUid": rental_data["paymentUid"]}
                else:
                    rental_data["payment"] = {}
        except (requests.RequestException, requests.Timeout):
            if rental_data.get("status") != "CANCELED":
                rental_data["payment"] = {"paymentUid": rental_data["paymentUid"]}
            else:
                rental_data["payment"] = {}
        
        return rental_data
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

@app.post("/api/v1/rental")
async def create_rental(
    rental_request: RentalRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create new rental - order according to README lab4: reserve car -> create rental -> create payment"""
    try:
        # Step 1: Check if car exists and reserve it (availability = false)
        car_response = requests.get(
            f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}",
            headers=auth_header_for(user.token),
            timeout=5
        )
        if car_response.status_code != 200:
            raise HTTPException(status_code=404, detail="Car not found")
        
        car_data = car_response.json()
        if not car_data.get("available", False):
            raise HTTPException(status_code=400, detail="Car is not available")
        
        # Reserve car
        car_reserve_response = requests.patch(
            f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
            params={"available": False},
            headers=auth_header_for(user.token),
            timeout=5
        )
        if car_reserve_response.status_code != 200:
            raise HTTPException(status_code=503, detail="Cars service unavailable")
        
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
                # Rollback car reservation
                try:
                    requests.patch(
                        f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
                        params={"available": True},
                        headers=auth_header_for(user.token),
                        timeout=3
                    )
                except:
                    pass
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
                # Rollback car reservation
                try:
                    requests.patch(
                        f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
                        params={"available": True},
                        headers=auth_header_for(user.token),
                        timeout=3
                    )
                except:
                    pass
                raise HTTPException(status_code=400, detail="Invalid date format for dateTo")
        
        rental_days = (date_to - date_from).days
        total_price = car_data["price"] * rental_days
        
        # Step 3: Create payment with circuit breaker (rental service requires paymentUid)
        def _create_payment():
            payment_data = {"price": total_price}
            payment_response = requests.post(
                f"{PAYMENT_SERVICE_URL}/api/v1/payments",
                json=payment_data,
                headers=auth_header_for(user.token),
                timeout=5
            )
            if payment_response.status_code != 201:
                raise requests.RequestException(f"Payment service returned {payment_response.status_code}")
            return payment_response.json()
        
        try:
            payment_info = payment_circuit_breaker.call(_create_payment)
        except Exception as e:
            print(f"Gateway: Payment service error: {e}")
            # Rollback car reservation
            try:
                requests.patch(
                    f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
                    params={"available": True},
                    headers=auth_header_for(user.token),
                    timeout=3
                )
            except:
                pass
            return JSONResponse(
                status_code=503,
                content={"message": "Payment Service unavailable"}
            )
        
        # Step 4: Create rental record
        rental_data = {
            "carUid": str(rental_request.carUid),
            "dateFrom": str(rental_request.dateFrom),
            "dateTo": str(rental_request.dateTo),
            "paymentUid": payment_info["paymentUid"]
        }
        rental_response = requests.post(
            f"{RENTAL_SERVICE_URL}/api/v1/rental",
            json=rental_data,
            headers=auth_header_for(user.token),
            timeout=5
        )
        if rental_response.status_code != 200:
            # Rollback car reservation and payment
            try:
                requests.patch(
                    f"{CARS_SERVICE_URL}/api/v1/cars/{rental_request.carUid}/availability",
                    params={"available": True},
                    timeout=3
                )
                requests.delete(
                    f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_info['paymentUid']}",
                    headers=auth_header_for(user.token),
                    timeout=3
                )
            except:
                pass
            raise HTTPException(status_code=503, detail="Rental service unavailable")
        
        rental_info = rental_response.json()
        
        # Step 5: Return aggregated response
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
async def finish_rental(rental_uid: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Finish rental"""
    try:
        rental_response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers=auth_header_for(user.token),
            timeout=5
        )
        if rental_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif rental_response.status_code != 200:
            raise HTTPException(status_code=rental_response.status_code, detail="Rental service error")
        
        rental_data = rental_response.json()
        car_uid = rental_data["carUid"]
        
        # Release car
        try:
            requests.patch(
                f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}/availability",
                params={"available": True},
                headers=auth_header_for(user.token),
                timeout=3
            )
        except:
            pass
        
        # Update rental status
        finish_response = requests.post(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}/finish",
            headers=auth_header_for(user.token),
            timeout=5
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
async def cancel_rental(rental_uid: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Cancel rental with failover support."""
    try:
        rental_response = requests.get(
            f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
            headers=auth_header_for(user.token),
            timeout=5
        )
        if rental_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Rental not found")
        elif rental_response.status_code != 200:
            raise HTTPException(status_code=rental_response.status_code, detail="Rental service error")
        
        rental_data = rental_response.json()
        car_uid = rental_data["carUid"]
        payment_uid = rental_data["paymentUid"]
        
        try:
            requests.patch(
                f"{CARS_SERVICE_URL}/api/v1/cars/{car_uid}/availability",
                params={"available": True},
                headers=auth_header_for(user.token),
                timeout=3
            )
        except requests.RequestException as e:
            print(f"Car release failed: {e}")
        
        # Update rental status with retry (10s)
        start_time = time.time()
        timeout_seconds = 10
        while time.time() - start_time < timeout_seconds:
            try:
                cancel_response = requests.delete(
                    f"{RENTAL_SERVICE_URL}/api/v1/rental/{rental_uid}",
                    headers=auth_header_for(user.token),
                    timeout=2
                )
                if cancel_response.status_code == 204:
                    break
                if cancel_response.status_code == 404:
                    raise HTTPException(status_code=404, detail="Rental not found")
            except requests.RequestException:
                pass
            time.sleep(0.5)
        
        # Cancel payment with retry + DB fallback
        payment_cancel_success = False
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                payment_cancel_response = requests.delete(
                    f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_uid}",
                    headers=auth_header_for(user.token),
                    timeout=2
                )
                if payment_cancel_response.status_code in (200, 204):
                    payment_cancel_success = True
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        
        if not payment_cancel_success:
            print(f"Payment service unavailable, forcing cancel for {payment_uid}")
            payment_cancel_success = force_cancel_payment(payment_uid)
        
        if not payment_cancel_success:
            print(f"Queueing payment cancellation retry for {payment_uid}")
            retry_queue.add_request(
                {
                    "type": "cancel_payment",
                    "data": {"payment_uid": payment_uid},
                    "timestamp": time.time(),
                    "token": user.token,
                }
            )
        
        from fastapi import Response
        return Response(status_code=204)
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Rental service unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
