"""JWT auth with role-based access control. Demo users only; swap for Entra ID in production."""
import json
import os
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)
DEFAULT_USERS = {
    "alice": {"password": "alice-pass", "roles": ["reader"]},
    "bob": {"password": "bob-pass", "roles": ["reader", "approver"]},
    "admin": {"password": "admin-pass", "roles": ["reader", "approver", "admin"]},
}


def users() -> dict:
    raw = os.getenv("DEMO_USERS")
    return json.loads(raw) if raw else DEFAULT_USERS


def login(username: str, password: str) -> str | None:
    u = users().get(username)
    if not u or u["password"] != password:
        return None
    now = int(time.time())
    return jwt.encode({"sub": username, "roles": u["roles"], "iat": now, "exp": now + 3600},
                      get_settings().jwt_secret, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Missing bearer token")
    try:
        return jwt.decode(cred.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}") from e


def require_role(role: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if role not in user.get("roles", []):
            raise HTTPException(403, f"Role '{role}' required")
        return user

    return dep
