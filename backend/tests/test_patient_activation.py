import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pytest
from fastapi.testclient import TestClient
from backend.main import app, get_db
from backend.database.models import Patient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database.db import Base
from backend.utils.mobile import normalize_mobile_number
import time

from sqlalchemy.pool import StaticPool

# Create an in-memory SQLite db for testing
engine = create_engine(
    "sqlite:///:memory:", 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_chatbot_booking_creation():
    db = TestingSessionLocal()
    # Simulate a chatbot creating a booking patient
    p = Patient(
        patient_id="PAT07134513",
        username="booking_07134513",
        password_hash="!BOOKING_ONLY!",
        full_name="Ravi",
        dob="1990-01-01",
        mobile="7373857342",
        address="123 Main St",
        emergency_contact="9999999999",
        gender="Male",
        status="ACTIVE"
    )
    db.add(p)
    db.commit()
    
    # 1. Attempt to register a new account with this mobile number
    register_payload = {
        "full_name": "Ravi Kumar",
        "username": "ravi_new",
        "dob": "1990-01-01",
        "gender": "Male",
        "mobile": "7373857342", # Same mobile
        "address": "123 Main St",
        "emergency_contact": "9999999999",
        "password": "securepassword123"
    }
    
    res = client.post("/patient/auth/register", json=register_payload)
    assert res.status_code == 400
    assert res.json()["status"] == "activation_required"
    
    # Simulate OTP verification. The backend stores it in DEMO_OTP_STORE
    from backend.main import DEMO_OTP_STORE
    store_record = DEMO_OTP_STORE.get("7373857342")
    assert store_record is not None
    assert store_record["pending_username"] == "ravi_new"
    otp = store_record["otp"]
    
    # 3. Final Activation
    res_activate = client.post("/patient/auth/activate", json={
        "mobile": "7373857342",
        "otp": otp
    })
    
    assert res_activate.status_code == 200
    assert "token" in res_activate.json()
    assert res_activate.json()["patient_id"] == "PAT07134513"
    
    # Verify DB state
    db.expire_all()
    p_updated = db.query(Patient).filter(Patient.patient_id == "PAT07134513").first()
    assert p_updated.username == "ravi_new"
    assert p_updated.password_hash != "!BOOKING_ONLY!"
    print("Test passed!")

if __name__ == "__main__":
    test_chatbot_booking_creation()
