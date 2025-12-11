from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List, Optional
import uuid
from uuid import UUID
import os
from services.auth import AuthenticatedUser, get_current_user

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://program:test@localhost:5432/payments")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database models
class Payment(Base):
    __tablename__ = "payment"
    
    id = Column(Integer, primary_key=True, index=True)
    payment_uid = Column(PostgresUUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    status = Column(String(20), nullable=False, default="PAID")
    price = Column(Integer, nullable=False)

# Pydantic models
class PaymentRequest(BaseModel):
    price: int

class PaymentResponse(BaseModel):
    paymentUid: UUID
    status: str
    price: int

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

# Create tables (will be created when first request comes)
# Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    # Create tables if they don't exist
    try:
        Base.metadata.create_all(bind=engine)
    except:
        pass  # Tables might already exist
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FastAPI app
app = FastAPI(title="Payment Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/manage/health")
async def health_check():
    return {"status": "OK"}

@app.get("/api/v1/payments/{payment_uid}", response_model=PaymentResponse)
async def get_payment(
    payment_uid: UUID,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get payment by UID"""
    payment = db.query(Payment).filter(Payment.payment_uid == payment_uid).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    return PaymentResponse(
        paymentUid=payment.payment_uid,
        status=payment.status,
        price=payment.price
    )

@app.post("/api/v1/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(
    payment_request: PaymentRequest,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create new payment"""
    payment = Payment(
        price=payment_request.price,
        status="PAID"
    )
    
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    return PaymentResponse(
        paymentUid=payment.payment_uid,
        status=payment.status,
        price=payment.price
    )

@app.delete("/api/v1/payments/{payment_uid}")
async def cancel_payment(
    payment_uid: UUID,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Cancel payment"""
    payment = db.query(Payment).filter(Payment.payment_uid == payment_uid).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    if payment.status == "CANCELED":
        raise HTTPException(status_code=400, detail="Payment already canceled")
    
    payment.status = "CANCELED"
    db.commit()
    
    return {"message": "Payment canceled successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)

