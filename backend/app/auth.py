"""
Authentication & Web Security Engine
Implements:
- Production-grade password hashing via bcrypt with per-user unique salt rounds.
- Backward-compatible migration from legacy SHA-256 hashes to bcrypt on login.
- JWT session token issuance (Access & Refresh tokens) with cryptographic signing and expiry.
- Token revocation table support for instant invalidation.
- Strict authentication enforcement: Rejects missing, malformed, or invalid credentials with HTTP 401.
"""
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import bcrypt
import jwt
from fastapi import Header, HTTPException, Security, Depends, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
import logging

from app.config import (
    JWT_SECRET_KEY, JWT_ALGORITHM, 
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS
)
from app.database import get_db_connection

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
HTTP_BEARER = HTTPBearer(auto_error=False)

LEGACY_SALT = "predictastock_salt_v2"


def hash_password(password: str) -> str:
    """Hash password using industry-standard bcrypt with unique 12-round salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """
    Verify password against stored hash.
    Returns: (is_valid: bool, needs_upgrade: bool)
    Supports transparent migration from legacy SHA-256 to bcrypt.
    """
    if not stored_hash or not password:
        return False, False

    # 1. Modern bcrypt hash check ($2a$, $2b$, or $2y$)
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            is_valid = bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
            return is_valid, False
        except Exception as e:
            logger.warning(f"Bcrypt verification failed with error: {e}")
            return False, False

    # 2. Legacy SHA-256 hash check
    legacy_hash = hashlib.sha256((password + LEGACY_SALT).encode("utf-8")).hexdigest()
    if stored_hash == legacy_hash:
        logger.info("Verified password via legacy SHA-256 hash. Flagged for automatic bcrypt upgrade.")
        return True, True

    return False, False


def create_access_token(user_id: str, username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate cryptographically signed JWT access token."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "username": username,
        "jti": jti,
        "token_type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, username: str) -> str:
    """Generate cryptographically signed JWT refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "username": username,
        "jti": jti,
        "token_type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def is_token_revoked(jti: str) -> bool:
    """Check if token JTI has been revoked in SQLite database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM revoked_tokens WHERE token_jti = ?", (jti,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def revoke_token(jti: str, user_id: str, expires_at: datetime) -> None:
    """Record token JTI into revoked_tokens table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO revoked_tokens (token_jti, user_id, revoked_at, expires_at)
    VALUES (?, ?, ?, ?)
    """, (jti, user_id, datetime.now(timezone.utc).isoformat(), expires_at.isoformat()))
    conn.commit()
    conn.close()


def register_user(username: str, password: str, email: str = None) -> Dict[str, Any]:
    """Register a new user account with dedicated portfolio partition and bcrypt hash."""
    clean_user = username.strip().lower()
    if len(clean_user) < 3:
        raise ValueError("Username must be at least 3 characters long.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ?", (clean_user,))
    if cursor.fetchone():
        conn.close()
        raise ValueError(f"Username '{clean_user}' already exists.")

    user_id = str(uuid.uuid4())
    api_key = f"pstk_live_{uuid.uuid4().hex[:20]}"
    pwd_hash = hash_password(password)
    now_str = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
    INSERT INTO users (id, username, email, password_hash, api_key, created_at, token_version)
    VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (user_id, clean_user, email, pwd_hash, api_key, now_str))
    conn.commit()
    conn.close()

    access_token = create_access_token(user_id, clean_user)
    refresh_token = create_refresh_token(user_id, clean_user)

    return {
        "user_id": user_id,
        "username": clean_user,
        "email": email,
        "api_key": api_key,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "created_at": now_str
    }


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Verify user credentials and return user context with JWT tokens.
    Transparently upgrades legacy SHA-256 hashes to bcrypt on success.
    """
    clean_user = username.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, username, email, password_hash, api_key, created_at 
    FROM users 
    WHERE username = ?
    """, (clean_user,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    stored_hash = row["password_hash"]
    is_valid, needs_upgrade = verify_password(password, stored_hash)

    if not is_valid:
        conn.close()
        return None

    # Safe transparent hash migration to bcrypt
    if needs_upgrade:
        new_bcrypt_hash = hash_password(password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_bcrypt_hash, row["id"]))
        conn.commit()
        logger.info(f"User account '{clean_user}' migrated from legacy SHA-256 to modern bcrypt hash.")

    conn.close()

    user_dict = dict(row)
    user_dict.pop("password_hash", None)
    user_dict["access_token"] = create_access_token(user_dict["id"], user_dict["username"])
    user_dict["refresh_token"] = create_refresh_token(user_dict["id"], user_dict["username"])
    return user_dict


def get_current_user_from_key(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(HTTP_BEARER)
) -> Dict[str, Any]:
    """
    Dependency to resolve authenticated user from either Bearer JWT or X-API-Key.
    Strictly enforces authentication: missing or invalid credentials raise HTTP 401.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Bearer JWT Token resolution
    if bearer and bearer.credentials:
        token = bearer.credentials
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("sub")
            jti = payload.get("jti")
            token_type = payload.get("token_type")

            if token_type != "access":
                conn.close()
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type for API access.")

            if jti and is_token_revoked(jti):
                conn.close()
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")

            cursor.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found.")
            return dict(row)

        except jwt.ExpiredSignatureError:
            conn.close()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token has expired. Please re-authenticate.")
        except jwt.PyJWTError as e:
            conn.close()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid session token: {str(e)}")

    # 2. X-API-Key resolution
    if api_key:
        cursor.execute("SELECT id, username, email FROM users WHERE api_key = ?", (api_key,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key provided.")

    conn.close()
    # Explicit 401 rejection: no implicit default trader fallback
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"}
    )


def ensure_default_trader_account() -> None:
    """Ensure the standard test trader account exists with a modern bcrypt hash."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash FROM users WHERE username = 'default_trader'")
    row = cursor.fetchone()

    default_pwd = "trader123"
    if not row:
        user_id = "usr_default_trader"
        api_key = "pstk_live_default_trader_key"
        pwd_hash = hash_password(default_pwd)
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
        INSERT INTO users (id, username, email, password_hash, api_key, created_at, token_version)
        VALUES (?, 'default_trader', 'trader@predictastock.internal', ?, ?, ?, 1)
        """, (user_id, pwd_hash, api_key, now_str))
        conn.commit()
        logger.info("Created default trader account (username: default_trader, password: trader123).")
    else:
        # Upgrade hash if still in legacy format
        curr_hash = row["password_hash"]
        if not curr_hash.startswith(("$2a$", "$2b$", "$2y$")):
            new_hash = hash_password(default_pwd)
            cursor.execute("UPDATE users SET password_hash = ? WHERE username = 'default_trader'", (new_hash,))
            conn.commit()
            logger.info("Migrated default trader account hash to bcrypt.")

    conn.close()
