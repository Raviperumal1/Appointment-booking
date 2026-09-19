from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.auth.patient_auth import hash_password, verify_password
from backend.database.models import User, Role
from backend.core.security import create_admin_access_token
from backend.auth.auth_dependencies import get_current_user, require_permission
from pydantic import BaseModel
from typing import Optional
import logging
from backend.core.logging_config import mask_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Admin Auth"])

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

class StaffUserCreateRequest(BaseModel):
    name: str
    email: str
    password: str
    role_id: int
    branch_id: Optional[int] = None
    department_id: Optional[int] = None

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user_record = db.query(User).filter(User.email == req.email, User.is_active == 1).first()

    if not user_record:
        logger.warning(f"Invalid login attempt | email={mask_email(req.email)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
        
    if not verify_password(req.password, user_record.password_hash):
        logger.warning(f"Invalid login attempt | email={mask_email(req.email)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
        
    role = db.query(Role).filter(Role.id == user_record.role_id).first()
    role_name = role.name if role else None
    
    token_data = {
        "sub": str(user_record.id),
        "role": role_name,
        "branch_id": user_record.branch_id,
        "department_id": user_record.department_id
    }
    access_token = create_admin_access_token(token_data)
    
    logger.info(f"Staff login successful | user_id={user_record.id} | role={role_name}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user_record.id,
            "name": user_record.name,
            "email": user_record.email,
            "role": role_name,
            "branch_id": user_record.branch_id,
            "department_id": user_record.department_id
        }
    }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role_name,
        "branch_id": current_user.branch_id,
        "department_id": current_user.department_id,
        "permissions": current_user.permissions
    }

@router.post("/register")
def register_staff_user(req: StaffUserCreateRequest, current_user: User = Depends(require_permission("USER_MANAGE")), db: Session = Depends(get_db)):
    target_role = db.query(Role).filter(Role.id == req.role_id).first()
    if not target_role:
        raise HTTPException(status_code=400, detail="Invalid role")

    if current_user.role_name == "BRANCH_ADMIN":
        if req.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Branch Admin can only create users in their own branch")
        if target_role.name == "ADMIN":
            raise HTTPException(status_code=403, detail="Branch Admin cannot create ADMIN users")

    if current_user.role_name == "DEPARTMENT_ADMIN":
        if req.branch_id != current_user.branch_id or req.department_id != current_user.department_id:
            raise HTTPException(status_code=403, detail="Department Admin can only create users in their own department")
        if target_role.name in ("ADMIN", "BRANCH_ADMIN", "DEPARTMENT_ADMIN"):
            raise HTTPException(status_code=403, detail="Department Admin cannot create equal or higher privileges")

    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    hashed = hash_password(req.password)
    
    new_user = User(
        name=req.name,
        email=req.email,
        password_hash=hashed,
        role_id=req.role_id,
        branch_id=req.branch_id,
        department_id=req.department_id,
        is_active=1
    )
    db.add(new_user)
    db.commit()
    
    return {"message": "User registered successfully", "user_id": new_user.id, "email": req.email}
