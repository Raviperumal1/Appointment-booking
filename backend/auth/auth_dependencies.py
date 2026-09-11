from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import User, Role, RolePermission, Permission
from backend.core.security import decode_admin_access_token

security = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = None
    if credentials is not None:
        token = credentials.credentials
    elif request.cookies.get("varuvi_admin_token"):
        token = request.cookies.get("varuvi_admin_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_admin_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Attach loaded role for quick access
    # the relationship takes care of user.role, but let's make sure it's loaded
    role = db.query(Role).filter(Role.id == user.role_id).first()
    user.role_name = role.name if role else None

    # Load user permissions from RolePermission and Permission models
    permissions_query = db.query(Permission.name).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).filter(RolePermission.role_id == user.role_id).all()
    user.permissions = [p[0] for p in permissions_query]

    return user

def require_permission(permission_name: str):
    def permission_checker(current_user: User = Depends(get_current_user)):
        # Admin can do anything
        if current_user.role_name == "ADMIN":
            return current_user
            
        if permission_name not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_name}"
            )
        return current_user
    return permission_checker
