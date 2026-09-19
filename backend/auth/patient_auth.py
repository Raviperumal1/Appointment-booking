import os
import hashlib
import hmac
import base64
import secrets
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.environ.get("JWT_SECRET", "varuvi-patient-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 6 * 60  # 6 hours
COOKIE_NAME = "varuvi_patient_token"

security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Adaptive scrypt hash; the random salt and work parameters travel with it."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(derived).decode())

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith("scrypt$"):
        try:
            _, n, r, p, salt, expected = hashed_password.split("$")
            actual = hashlib.scrypt(plain_password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
            return hmac.compare_digest(actual, base64.b64decode(expected))
        except (ValueError, TypeError):
            return False
    # Compatibility-only verification for records made before this migration.
    legacy = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), b'varuvi_salt_123', 100000).hex()
    return hmac.compare_digest(legacy, hashed_password)


def password_needs_upgrade(password_hash: str) -> bool:
    return not password_hash.startswith("scrypt$")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session has expired. Please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token. Please log in again.")

def get_current_patient_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> int:
    token = None

    if credentials is not None:
        token = credentials.credentials
    elif request.cookies.get(COOKIE_NAME):
        token = request.cookies.get(COOKIE_NAME)

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = decode_access_token(token)
    patient_id_db = payload.get("sub")
    if patient_id_db is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return int(patient_id_db)
