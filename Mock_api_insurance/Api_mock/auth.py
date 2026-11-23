import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from .audit import record_activity, record_activity_to_db
from .password_utils import hash_password, verify_password

dotenv.load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set")
ALGORITHM  = "HS256"
DB_PATH    = "Sqllite/insurance.db"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login", auto_error=False)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    return conn


def create_token(user_id: int, role: str) -> str:
    payload = {
        "sub":  str(user_id),
        "role": role,
        "exp":  datetime.now() + timedelta(hours=1),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ── login endpoint logi
# c ───────────────────────────────────────────────────────

def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Accepts username (treated as email) + password via form body.
    Returns a Bearer token on success.
    """
    conn   = _get_connection()
    try:
        user = conn.execute(
            "SELECT user_id, name, email, role, password_hash, is_active FROM users WHERE email = ?",
            (form_data.username,),
        ).fetchone()

        if (
            user is None
            or not user["is_active"]
            or not verify_password(form_data.password, user["password_hash"])
        ):
            record_activity(
                conn,
                event_type="LOGIN",
                outcome="DENIED",
                actor_user_id=user["user_id"] if user is not None else None,
                resource_type="AUTH",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
            conn.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_token(user["user_id"], user["role"])
        record_activity(
            conn,
            event_type="LOGIN",
            outcome="SUCCESS",
            actor_user_id=user["user_id"],
            resource_type="AUTH",
            status_code=status.HTTP_200_OK,
        )
        conn.commit()
        return {
            "access_token": token,
            "token_type":   "bearer",
            "user_id":      user["user_id"],
            "role":         user["role"],
        }
    finally:
        conn.close()


# ── token verification (use as Depends in protected routes) ───────────────────

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    credentials_error = HTTPException(
        status_code=401,
        detail="Could not validate token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        record_activity_to_db(
            DB_PATH,
            event_type="TOKEN_AUTHENTICATION",
            outcome="DENIED",
            resource_type="AUTH",
            status_code=401,
        )
        raise credentials_error
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        record_activity_to_db(
            DB_PATH,
            event_type="TOKEN_AUTHENTICATION",
            outcome="DENIED",
            resource_type="AUTH",
            status_code=401,
        )
        raise credentials_error
    conn = _get_connection()
    try:
        user = conn.execute(
            "SELECT role, is_active FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if user is None or not user["is_active"]:
        record_activity_to_db(
            DB_PATH,
            event_type="TOKEN_AUTHENTICATION",
            outcome="DENIED",
            actor_user_id=user_id,
            resource_type="AUTH",
            status_code=401,
        )
        raise credentials_error

    return {"user_id": user_id, "role": user["role"]}


# ── RBAC — role based access control ─────────────────────────────────────────

def require_role(*allowed_roles: str):
    """
    Usage:  Depends(require_role("admin"))
            Depends(require_role("admin", "agent"))
    """
    def check(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            record_activity_to_db(
                DB_PATH,
                event_type="ROLE_ACCESS",
                outcome="DENIED",
                actor_user_id=current_user["user_id"],
                resource_type="AUTH",
                status_code=403,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {list(allowed_roles)}",
            )
        return current_user
    return check


def create_agent_token(agent_id: int) -> str:
    payload = {
        "agent_id": agent_id,
        "exp": datetime.now() + timedelta(hours=1),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_agent(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """Validates a token that was issued for a specific agent (contains agent_id)."""
    credentials_error = HTTPException(
        status_code=401,
        detail="Could not validate agent token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        record_activity_to_db(
            DB_PATH,
            event_type="AGENT_TOKEN_AUTHENTICATION",
            outcome="DENIED",
            resource_type="AUTH",
            status_code=401,
        )
        raise credentials_error
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        agent_id = int(payload.get("agent_id"))
    except (JWTError, TypeError, ValueError):
        record_activity_to_db(
            DB_PATH,
            event_type="AGENT_TOKEN_AUTHENTICATION",
            outcome="DENIED",
            resource_type="AUTH",
            status_code=401,
        )
        raise credentials_error

    conn = _get_connection()
    try:
        agent = conn.execute(
            "SELECT user_id FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
    finally:
        conn.close()
    if agent is None:
        record_activity_to_db(
            DB_PATH,
            event_type="AGENT_TOKEN_AUTHENTICATION",
            outcome="DENIED",
            resource_type="AGENT",
            resource_id=agent_id,
            status_code=401,
        )
        raise credentials_error
    return {"agent_id": agent_id, "user_id": agent["user_id"]}


def registration_new_user(
    details: dict, actor_user_id: Optional[int] = None
) -> dict:
    """Create a customer login account; callers cannot choose a privileged role."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id FROM users WHERE email = ?", (details["email"],)
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
            
        # hashing the password before store    # 
        cursor.execute(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (
                    details["email"],
                    details["name"],
                    hash_password(details["password"]),
                    "Customer",
                ),
            )
        user_id = cursor.lastrowid
        record_activity(
            conn,
            event_type="USER_REGISTERED",
            outcome="SUCCESS",
            actor_user_id=actor_user_id if actor_user_id is not None else user_id,
            resource_type="USER",
            resource_id=user_id,
            status_code=201,
        )
        conn.commit()
        row = cursor.execute(
            """SELECT user_id, email, name, role, is_active, last_login, created_at
               FROM users WHERE user_id = ?""", (user_id,),
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or name already registered",
        ) from exc
    finally:
        conn.close()




   



    
        

       

    



