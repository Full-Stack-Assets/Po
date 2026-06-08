"""Unit tests for authentication & user management module."""

import pytest

from orchestrator_agent.auth import (
    AuthManager,
    InMemoryUserStore,
    _hash_password,
    _jwt_decode,
    _jwt_encode,
    _verify_password,
)


SECRET = "test-secret-key-for-unit-tests"


# ── Password hashing ─────────────────────────────────────────────────


def test_hash_and_verify_password():
    hashed = _hash_password("correct-horse-battery")
    assert _verify_password("correct-horse-battery", hashed)
    assert not _verify_password("wrong-password", hashed)


# ── JWT encode / decode ──────────────────────────────────────────────


def test_jwt_encode_decode():
    payload = {"sub": "user-123", "email": "a@b.com", "extra": 42}
    token = _jwt_encode(payload, SECRET)
    decoded = _jwt_decode(token, SECRET)
    assert decoded["sub"] == "user-123"
    assert decoded["email"] == "a@b.com"
    assert decoded["extra"] == 42


def test_jwt_invalid_signature():
    payload = {"sub": "user-123"}
    token = _jwt_encode(payload, SECRET)
    # Tamper with the token by changing a character in the signature
    parts = token.split(".")
    sig = parts[2]
    tampered_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"
    with pytest.raises(ValueError, match="invalid signature"):
        _jwt_decode(tampered_token, SECRET)


# ── Registration ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_user():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    user = await mgr.register("alice@example.com", "s3cret", "Alice")
    assert user.id  # non-empty UUID
    assert user.email == "alice@example.com"
    assert user.name == "Alice"


@pytest.mark.asyncio
async def test_register_duplicate_email():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    await mgr.register("dup@example.com", "pw1", "First")
    with pytest.raises(ValueError, match="already registered"):
        await mgr.register("dup@example.com", "pw2", "Second")


# ── Login ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_success():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    await mgr.register("bob@example.com", "pass123", "Bob")
    result = await mgr.login("bob@example.com", "pass123")
    assert "access_token" in result
    assert result["token_type"] == "bearer"
    assert result["user"].email == "bob@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    await mgr.register("carol@example.com", "right", "Carol")
    with pytest.raises(ValueError, match="Invalid email or password"):
        await mgr.login("carol@example.com", "wrong")


@pytest.mark.asyncio
async def test_login_nonexistent():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    with pytest.raises(ValueError, match="Invalid email or password"):
        await mgr.login("nobody@example.com", "whatever")


# ── Token verification ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_token():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    await mgr.register("dan@example.com", "pw", "Dan")
    result = await mgr.login("dan@example.com", "pw")
    user = await mgr.verify_token(result["access_token"])
    assert user.email == "dan@example.com"
    assert user.name == "Dan"


@pytest.mark.asyncio
async def test_verify_expired_token():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store, token_expiry_hours=0)
    await mgr.register("eve@example.com", "pw", "Eve")
    result = await mgr.login("eve@example.com", "pw")
    with pytest.raises(ValueError, match="token expired"):
        await mgr.verify_token(result["access_token"])


# ── API keys ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_verify_api_key():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    user = await mgr.register("frank@example.com", "pw", "Frank")
    key = await store.create_api_key(user.id)
    assert key.startswith("po_")
    verified = await mgr.verify_api_key(key)
    assert verified.id == user.id


@pytest.mark.asyncio
async def test_revoke_api_key():
    store = InMemoryUserStore()
    mgr = AuthManager(SECRET, store)
    user = await mgr.register("grace@example.com", "pw", "Grace")
    key = await store.create_api_key(user.id)
    revoked = await store.revoke_api_key(user.id, key)
    assert revoked is True
    with pytest.raises(ValueError, match="Invalid API key"):
        await mgr.verify_api_key(key)
