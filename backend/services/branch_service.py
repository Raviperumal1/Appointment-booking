from typing import Optional
from sqlalchemy.orm import Session
from backend.database.models import Branch, Doctor, Appointment

def list_branches(db: Session):
    branches = db.query(Branch).order_by(Branch.name).all()
    return [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status} for b in branches]


def get_branch(db: Session, branch_id: int) -> Optional[dict]:
    b = db.query(Branch).filter(Branch.id == branch_id).first()
    if b:
        return {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status}
    return None


def ensure_branch_exists(db: Session, branch_id: int):
    branch = get_branch(db, branch_id)
    if not branch:
        raise ValueError("Branch not found")
    return branch


def is_branch_open(db: Session, branch_id: int) -> bool:
    branch = get_branch(db, branch_id)
    return bool(branch and branch["branch_status"] == "OPEN")


def update_branch_status(db: Session, branch_id: int, branch_status: str):
    if branch_status not in ("OPEN", "CLOSED"):
        raise ValueError("branch_status must be OPEN or CLOSED")
    b = db.query(Branch).filter(Branch.id == branch_id).first()
    if not b:
        raise ValueError("Branch not found")
    
    b.branch_status = branch_status
    db.commit()
    return {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status}


def create_branch(db: Session, data: dict):
    if data["branch_status"] not in ("OPEN", "CLOSED"):
        raise ValueError("branch_status must be OPEN or CLOSED")
    
    b = Branch(
        name=data["name"],
        address=data.get("address", ""),
        phone=data.get("phone", ""),
        branch_status=data["branch_status"]
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status}


def update_branch(db: Session, branch_id: int, data: dict):
    b = db.query(Branch).filter(Branch.id == branch_id).first()
    if not b:
        raise ValueError("Branch not found")
    if data.get("branch_status") is not None and data["branch_status"] not in ("OPEN", "CLOSED"):
        raise ValueError("branch_status must be OPEN or CLOSED")
    
    for key in ["name", "address", "phone", "branch_status"]:
        if key in data and data[key] is not None:
            setattr(b, key, data[key])
            
    db.commit()
    db.refresh(b)
    return {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status}


def delete_branch(db: Session, branch_id: int):
    b = db.query(Branch).filter(Branch.id == branch_id).first()
    if not b:
        raise ValueError("Branch not found")
    
    existing_doc = db.query(Doctor).filter(Doctor.branch_id == branch_id).first()
    if existing_doc:
        raise ValueError("Cannot delete branch with existing doctors")
        
    existing_appt = db.query(Appointment).filter(Appointment.branch_id == branch_id).first()
    if existing_appt:
        raise ValueError("Cannot delete branch with existing appointments")
        
    db.delete(b)
    db.commit()
    return {"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status}


def list_open_branches(db: Session):
    branches = db.query(Branch).filter(Branch.branch_status == 'OPEN').order_by(Branch.name).all()
    return [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status} for b in branches]
