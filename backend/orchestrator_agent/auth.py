"""
Authentication & User Management — auth.py
JWT auth, API key auth, user CRUD, session tracking.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json as _json
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, Request


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _jwt_encode(payload: dict, secret: str) -> str:
    header = _b64url_encode(_json.dumps(
        {"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(_json.dumps(payload, default=str).encode())
    sig_input = f"{header}.{body}"
    sig = _b64url_encode(hmac.new(
        secret.encode(), sig_input.encode(), hashlib.sha256).digest())
    return f"{sig_input}.{sig}"


def _jwt_decode(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid token")
    sig_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(
        secret.encode(), sig_input.encode(), hashlib.sha256).digest()
    actual = _b64url_decode(parts[2])
    if not hmac.compare_digest(expected, actual):
        raise ValueError("invalid signature")
    payload = _json.loads(_b64url_decode(parts[1]))
    if "exp" in payload:
        from datetime import datetime, timezone
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise ValueError("token expired")
    return payload


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    name: str
    created_at: datetime
    settings: dict[str, Any] = field(default_factory=dict)
    api_keys: list[str] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    user_id: str
    created_at: datetime
    last_active: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


def _hash_password(password: str) -> str:
    salt = os.urandom(32)
    h = hashlib.sha256(salt + password.encode()).hexdigest()
    return f"{salt.hex()}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    h = hashlib.sha256(salt + password.encode()).hexdigest()
    return secrets.compare_digest(h, hash_hex)


class UserStore(ABC):
    @abstractmethod
    async def create_user(self, email: str, password: str, name: str) -> User: ...

    @abstractmethod
    async def get_user(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    async def get_user_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    async def update_user(self, user_id: str, **fields: Any) -> User: ...

    @abstractmethod
    async def delete_user(self, user_id: str) -> bool: ...

    @abstractmethod
    async def create_api_key(self, user_id: str) -> str: ...

    @abstractmethod
    async def revoke_api_key(self, user_id: str, key: str) -> bool: ...

    @abstractmethod
    async def get_user_by_api_key(self, key: str) -> Optional[User]: ...


class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._email_index: dict[str, str] = {}
        self._api_key_index: dict[str, str] = {}

    async def create_user(self, email: str, password: str, name: str) -> User:
        if email in self._email_index:
            raise ValueError(f"Email already registered: {email}")
        user = User(
            id=str(uuid4()),
            email=email,
            password_hash=_hash_password(password),
            name=name,
            created_at=datetime.now(timezone.utc),
        )
        self._users[user.id] = user
        self._email_index[email] = user.id
        return user

    async def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    async def get_user_by_email(self, email: str) -> Optional[User]:
        user_id = self._email_index.get(email)
        if user_id is None:
            return None
        return self._users.get(user_id)

    async def update_user(self, user_id: str, **fields: Any) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        for key, value in fields.items():
            if not hasattr(user, key):
                raise ValueError(f"Invalid field: {key}")
            setattr(user, key, value)
        if "email" in fields:
            old_emails = [e for e, uid in self._email_index.items() if uid == user_id]
            for old_email in old_emails:
                del self._email_index[old_email]
            self._email_index[fields["email"]] = user_id
        return user

    async def delete_user(self, user_id: str) -> bool:
        user = self._users.pop(user_id, None)
        if user is None:
            return False
        self._email_index.pop(user.email, None)
        for key in user.api_keys:
            self._api_key_index.pop(key, None)
        return True

    async def create_api_key(self, user_id: str) -> str:
        user = self._users.get(user_id)
        if user is None:
            raise ValueError(f"User not found: {user_id}")
        key = f"po_{secrets.token_urlsafe(32)}"
        user.api_keys.append(key)
        self._api_key_index[key] = user_id
        return key

    async def revoke_api_key(self, user_id: str, key: str) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False
        if key not in user.api_keys:
            return False
        user.api_keys.remove(key)
        self._api_key_index.pop(key, None)
        return True

    async def get_user_by_api_key(self, key: str) -> Optional[User]:
        user_id = self._api_key_index.get(key)
        if user_id is None:
            return None
        return self._users.get(user_id)


class AuthManager:
    def __init__(
        self,
        secret_key: str,
        user_store: UserStore,
        token_expiry_hours: int = 24,
    ) -> None:
        self.secret_key = secret_key
        self.user_store = user_store
        self.token_expiry_hours = token_expiry_hours
        self._sessions: dict[str, Session] = {}

    def _create_token(self, user: User) -> str:
        payload = {
            "sub": user.id,
            "email": user.email,
            "exp": datetime.now(timezone.utc) + timedelta(hours=self.token_expiry_hours),
        }
        payload["exp"] = int(payload["exp"].timestamp())
        return _jwt_encode(payload, self.secret_key)

    async def register(self, email: str, password: str, name: str) -> User:
        existing = await self.user_store.get_user_by_email(email)
        if existing is not None:
            raise ValueError(f"Email already registered: {email}")
        return await self.user_store.create_user(email, password, name)

    async def login(self, email: str, password: str) -> dict[str, Any]:
        user = await self.user_store.get_user_by_email(email)
        if user is None or not _verify_password(password, user.password_hash):
            raise ValueError("Invalid email or password")
        token = self._create_token(user)
        return {"access_token": token, "token_type": "bearer", "user": user}

    async def verify_token(self, token: str) -> User:
        try:
            payload = _jwt_decode(token, self.secret_key)
        except ValueError as e:
            raise ValueError(str(e))
        user = await self.user_store.get_user(payload["sub"])
        if user is None:
            raise ValueError("User not found")
        return user

    async def verify_api_key(self, key: str) -> User:
        user = await self.user_store.get_user_by_api_key(key)
        if user is None:
            raise ValueError("Invalid API key")
        return user

    async def create_session(self, user_id: str) -> Session:
        now = datetime.now(timezone.utc)
        session = Session(
            session_id=str(uuid4()),
            user_id=user_id,
            created_at=now,
            last_active=now,
        )
        self._sessions[session.session_id] = session
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_active = datetime.now(timezone.utc)
        return session

    async def refresh_token(self, token: str) -> dict[str, Any]:
        user = await self.verify_token(token)
        new_token = self._create_token(user)
        return {"access_token": new_token, "token_type": "bearer", "user": user}


async def auth_dependency(request: Request) -> User:
    auth_manager: AuthManager = request.app.state.auth_manager

    authorization = request.headers.get("Authorization")
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            try:
                return await auth_manager.verify_token(token)
            except ValueError as e:
                raise HTTPException(status_code=401, detail=str(e))
        try:
            return await auth_manager.verify_api_key(authorization)
        except ValueError:
            pass

    api_key = request.headers.get("X-API-Key")
    if api_key:
        try:
            return await auth_manager.verify_api_key(api_key)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))

    raise HTTPException(status_code=401, detail="Missing authentication credentials")
