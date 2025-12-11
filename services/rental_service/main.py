from fastapi import FastAPI, HTTPException, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, desc
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import uuid
from uuid import UUID
import os
from services.auth import AuthenticatedUser, get_current_user

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://program:test@localhost:5432/rentals")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database models
class Rental(Base):
    __tablename__ = "rental"
    
    id = Column(Integer, primary_key=True, index=True)
    rental_uid = Column(PostgresUUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    username = Column(String(80), nullable=False)
    payment_uid = Column(PostgresUUID(as_uuid=True), nullable=False)
    car_uid = Column(PostgresUUID(as_uuid=True), nullable=False)
    date_from = Column(DateTime, nullable=False)
    date_to = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="IN_PROGRESS")

# Pydantic models
class RentalRequest(BaseModel):
    carUid: str
    dateFrom: str
    dateTo: str

class RentalResponse(BaseModel):
    rentalUid: str
    status: str
    dateFrom: str
    dateTo: str
    carUid: str
    paymentUid: str

    class Config:
        from_attributes = True

class RentalListResponse(BaseModel):
    page: int
    pageSize: int
    totalElements: int
    items: List[RentalResponse]

# Create tables (will be created when first request comes)
# Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Rental Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/manage/health")
async def health_check():
    return {"status": "OK"}

@app.get("/api/v1/rental", response_model=RentalListResponse)
async def get_rentals(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = 0,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    """Get all rentals for user"""
    query = db.query(Rental).filter(Rental.username == user.username).order_by(desc(Rental.id))
    total = query.count()
    rentals = query.offset(page * page_size).limit(page_size).all()
    
    items = []
    for rental in rentals:
        items.append(RentalResponse(
            rentalUid=str(rental.rental_uid),
            status=rental.status,
            dateFrom=rental.date_from.strftime("%Y-%m-%d") if isinstance(rental.date_from, datetime) else rental.date_from.isoformat(),
            dateTo=rental.date_to.strftime("%Y-%m-%d") if isinstance(rental.date_to, datetime) else rental.date_to.isoformat(),
            carUid=str(rental.car_uid),
            paymentUid=str(rental.payment_uid)
        ))
    
    return RentalListResponse(
        page=page,
        pageSize=page_size,
        totalElements=total,
        items=items
    )

@app.get("/api/v1/rental/{rental_uid}", response_model=RentalResponse)
async def get_rental(
    rental_uid: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get rental by UID"""
    rental = db.query(Rental).filter(
        Rental.rental_uid == rental_uid,
        Rental.username == user.username
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Rental not found")
    
    return RentalResponse(
        rentalUid=str(rental.rental_uid),
        status=rental.status,
        dateFrom=rental.date_from.strftime("%Y-%m-%d") if isinstance(rental.date_from, datetime) else rental.date_from.isoformat(),
        dateTo=rental.date_to.strftime("%Y-%m-%d") if isinstance(rental.date_to, datetime) else rental.date_to.isoformat(),
        carUid=str(rental.car_uid),
        paymentUid=str(rental.payment_uid)
    )

class CreateRentalRequest(BaseModel):
    carUid: str
    dateFrom: str
    dateTo: str
    paymentUid: str

@app.post("/api/v1/rental", response_model=RentalResponse)
async def create_rental(
    rental_request: CreateRentalRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create new rental record"""
    print(f"Creating rental for car {rental_request.carUid}, user {user.username}")
    
    # Parse dates
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
    
    # Create rental record
    rental = Rental(
        username=user.username,
        payment_uid=UUID(rental_request.paymentUid),
        car_uid=UUID(rental_request.carUid),
        date_from=date_from,
        date_to=date_to,
        status="IN_PROGRESS"
    )
    
    db.add(rental)
    db.commit()
    db.refresh(rental)
    
    return RentalResponse(
        rentalUid=str(rental.rental_uid),
        status=rental.status,
        dateFrom=date_from.strftime("%Y-%m-%d"),
        dateTo=date_to.strftime("%Y-%m-%d"),
        carUid=str(rental.car_uid),
        paymentUid=str(rental.payment_uid)
    )

@app.post("/api/v1/rental/{rental_uid}/finish")
async def finish_rental(
    rental_uid: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Finish rental"""
    rental = db.query(Rental).filter(
        Rental.rental_uid == rental_uid,
        Rental.username == user.username
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Rental not found")
    
    if rental.status != "IN_PROGRESS":
        raise HTTPException(status_code=400, detail="Rental is not in progress")
    
    # Update rental status
    rental.status = "FINISHED"
    db.commit()
    
    return Response(status_code=204)

@app.delete("/api/v1/rental/{rental_uid}")
async def cancel_rental(
    rental_uid: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel rental"""
    rental = db.query(Rental).filter(
        Rental.rental_uid == rental_uid,
        Rental.username == user.username
    ).first()
    
    if not rental:
        raise HTTPException(status_code=404, detail="Rental not found")
    
    if rental.status == "CANCELED":
        raise HTTPException(status_code=400, detail="Rental already canceled")
    
    # Update rental status
    rental.status = "CANCELED"
    db.commit()
    
    return Response(status_code=204)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8060)

