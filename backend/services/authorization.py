"""Central, deny-by-default authorization for new and migrated routes."""
import base64
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from fastapi import Depends, HTTPException, Request

from backend.database.db import get_db
from backend.auth.patient_auth import decode_access_token, verify_password

ROLE_PERMISSIONS = {
    "ADMIN": {"*"},
    "BRANCH_ADMIN": {
        "BRANCH_READ", "DEPARTMENT_READ", "DEPARTMENT_MANAGE",
        "DOCTOR_READ", "DOCTOR_MANAGE", "PATIENT_READ", "PATIENT_UPDATE",
        "APPOINTMENT_READ", "APPOINTMENT_MANAGE", "CONVERSATION_READ", "CONSULTATION_READ",
        "PRESCRIPTION_READ", "MEDICAL_REPORT_READ"
    },
    "DEPARTMENT_ADMIN": {
        "DEPARTMENT_READ", "DOCTOR_READ", "PATIENT_READ",
        "APPOINTMENT_READ", "CONVERSATION_READ", "CONSULTATION_READ", "PRESCRIPTION_READ",
        "MEDICAL_REPORT_READ"
    },
    "DOCTOR": {
        "DOCTOR_READ", "PATIENT_READ", "PATIENT_UPDATE", "APPOINTMENT_READ",
        "CONSULTATION_READ", "CONSULTATION_CREATE", "CONSULTATION_UPDATE",
        "PRESCRIPTION_READ", "PRESCRIPTION_CREATE", "MEDICAL_REPORT_READ",
        "MEDICAL_REPORT_UPLOAD"
    },
    "PATIENT": {
        "PATIENT_READ", "PATIENT_UPDATE", "APPOINTMENT_READ",
        "APPOINTMENT_MANAGE", "CONSULTATION_READ", "PRESCRIPTION_READ",
        "MEDICAL_REPORT_READ"
    },
}

def get_role_permissions_db(db) -> dict:
    try:
        from backend.database.models import Role, Permission, RolePermission
        rows = db.query(Role.name.label('role_name'), Permission.name.label('perm_name'))\
            .join(RolePermission, RolePermission.role_id == Role.id)\
            .join(Permission, Permission.id == RolePermission.permission_id)\
            .all()
            
        cache = {}
        for row in rows:
            rname = row.role_name
            pname = row.perm_name
            if rname not in cache:
                cache[rname] = set()
            cache[rname].add(pname)
        
        # Ensure ADMIN has full access in cache
        if "ADMIN" not in cache:
            cache["ADMIN"] = {"*"}
        else:
            cache["ADMIN"].add("*")
            
        return cache
    except Exception:
        # Fallback if tables not yet migrated
        return ROLE_PERMISSIONS

def clear_permission_cache():
    # Cache removed; this is a no-op for legacy compatibility
    pass

@dataclass
class Principal:
    user_id: Optional[int]
    patient_id: Optional[int]
    roles: set
    label: str
    scopes: List[Dict[str, Optional[int]]] = field(default_factory=list)

    @property
    def privileged(self): return bool({"ADMIN"} & self.roles)

def get_current_principal(request: Request, db = Depends(get_db)) -> Principal:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("basic "):
        try:
            username, password = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)
            from backend.database.models import User, Role, UserRole, UserScope
            user_record = db.query(User).filter(User.username == username, User.is_active == 1).first()
            if user_record and verify_password(password, user_record.password_hash):
                roles = db.query(Role.name).join(UserRole, UserRole.role_id == Role.id).filter(UserRole.user_id == user_record.id).all()
                role_set = {r[0] for r in roles}
                
                # Fetch scopes
                scopes = db.query(UserScope).filter(UserScope.user_id == user_record.id).all()
                scope_list = [{"branch_id": s.branch_id, "department_id": s.department_id} for s in scopes]

                return Principal(user_record.id, None, role_set, f"staff:{user_record.id}", scope_list)
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else request.cookies.get("varuvi_patient_token")
    if not token:
        token = request.cookies.get("varuvi_admin_token")
    if not token: raise HTTPException(status_code=401, detail="Authentication required")
    
    # Try parsing as an admin JWT token first
    try:
        from backend.core.security import decode_admin_access_token
        payload = decode_admin_access_token(token)
        user_id = payload.get("sub")
        if user_id:
            role = payload.get("role")
            role_set = {role} if role else set()
            branch_id = payload.get("branch_id")
            dept_id = payload.get("department_id")
            scope_list = [{"branch_id": branch_id, "department_id": dept_id}] if branch_id or dept_id else []
            return Principal(int(user_id), None, role_set, f"staff:{user_id}", scope_list)
    except Exception:
        pass # Fallback to patient token
        
    # Try as patient token
    try:
        payload = decode_access_token(token)
        patient_id = int(payload.get("sub"))
        return Principal(None, patient_id, {"PATIENT"}, f"patient:{patient_id}", [])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_permission(permission: str):
    def dependency(principal: Principal = Depends(get_current_principal), db = Depends(get_db)) -> Principal:
        db_perms = get_role_permissions_db(db)
        allowed = False
        for role in principal.roles:
            perms = db_perms.get(role, set())
            if "*" in perms or permission in perms:
                allowed = True
                break
                
        if not allowed: raise HTTPException(status_code=403, detail="Permission denied")
        return principal
    return dependency

def require_branch_access(branch_id: int):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.privileged: return principal
        for scope in principal.scopes:
            if scope["branch_id"] == branch_id or scope["branch_id"] is None:
                return principal
        raise HTTPException(status_code=403, detail="You do not have access to this branch.")
    return dependency

def require_department_access(branch_id: int, department_id: int):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.privileged: return principal
        for scope in principal.scopes:
            if (scope["branch_id"] == branch_id or scope["branch_id"] is None) and \
               (scope["department_id"] == department_id or scope["department_id"] is None):
                return principal
        raise HTTPException(status_code=403, detail="You do not have access to this department.")
    return dependency

def assert_report_access(conn, principal: Principal, report, write: bool = False):
    if principal.privileged: return
    if principal.patient_id == report["patient_id"] and not write: return
    raise HTTPException(status_code=403, detail="You are not authorized to access this medical report")

def audit(db, principal: Principal, action: str, resource_type: str, resource_id=None, result="SUCCESS", ip_address=None):
    from backend.database.models import AuditLog
    log = AuditLog(
        user_id=principal.user_id,
        actor_label=principal.label,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        result=result,
        ip_address=ip_address
    )
    db.add(log)
    db.commit()
