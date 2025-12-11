from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text
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
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://program:test@localhost:5432/cars")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database models
class Car(Base):
    __tablename__ = "cars"
    
    id = Column(Integer, primary_key=True, index=True)
    car_uid = Column(PostgresUUID(as_uuid=True), unique=True, index=True, default=uuid.uuid4)
    brand = Column(String(80), nullable=False)
    model = Column(String(80), nullable=False)
    registration_number = Column(String(20), nullable=False)
    power = Column(Integer)
    price = Column(Integer, nullable=False)
    type = Column(String(20))
    availability = Column(Boolean, nullable=False, default=True)

# Pydantic models
class CarResponse(BaseModel):
    carUid: UUID
    brand: str
    model: str
    registrationNumber: str
    power: Optional[int]
    price: int
    type: Optional[str]
    available: bool

    class Config:
        from_attributes = True
        json_encoders = {
            UUID: str
        }

class CarListResponse(BaseModel):
    page: int
    pageSize: int
    totalElements: int
    items: List[CarResponse]

# Create tables (will be created when first request comes)
# Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Cars Service", version="1.0.0")

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
    except Exception as e:
        print(f"Error creating tables: {e}")
        pass  # Tables might already exist
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/manage/health")
async def health_check():
    return {"status": "OK"}

@app.get("/api/v1/cars", response_model=CarListResponse)
async def get_cars(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    showAll: bool = Query(False),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get list of available cars"""
    try:
        query = db.query(Car)
        
        if not showAll:
            query = query.filter(Car.availability == True)
        
        total = query.count()
        cars = query.offset((page - 1) * pageSize).limit(pageSize).all()
        
        print(f"Cars service: Found {total} cars, returning {len(cars)} cars")
        
        return CarListResponse(
            page=page,
            pageSize=pageSize,
            totalElements=total,
            items=[CarResponse(
                carUid=car.car_uid,
                brand=car.brand,
                model=car.model,
                registrationNumber=car.registration_number,
                power=car.power,
                price=car.price,
                type=car.type,
                available=car.availability
            ) for car in cars]
        )
    except Exception as e:
        print(f"Error in get_cars: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/v1/cars/{car_uid}", response_model=CarResponse)
async def get_car(
    car_uid: UUID,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get car by UID"""
    car = db.query(Car).filter(Car.car_uid == car_uid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    
    return CarResponse(
        carUid=car.car_uid,
        brand=car.brand,
        model=car.model,
        registrationNumber=car.registration_number,
        power=car.power,
        price=car.price,
        type=car.type,
        available=car.availability
    )

@app.patch("/api/v1/cars/{car_uid}/availability")
async def update_car_availability(
    car_uid: UUID, 
    available: bool = Query(...),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update car availability"""
    car = db.query(Car).filter(Car.car_uid == car_uid).first()
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    
    car.availability = available
    db.commit()
    
    return {"message": "Car availability updated"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8070)

