"""Signed authentication sessions and server-validated policy context.

The browser can never select the vendor, region, department, or role used by
the policy agents. Those attributes come only from the authenticated account.
Passwords are verified against salted PBKDF2 hashes stored outside source code,
while sessions are signed JWTs persisted locally for logout revocation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import HTTPException, Request, Response, status

from config import settings
from schemas import IdentityContext

logger = logging.getLogger(__name__)
SESSION_COOKIE = "arbiter_session"
SESSION_TTL_SECONDS = settings.JWT_EXPIRATION_SECONDS
# Fast-path cache; SQLite remains the durable source across a reload.
_sessions: dict[str, tuple[IdentityContext, float]] = {}


@dataclass(frozen=True)
class AccountRecord:
    username: str
    salt: str
    password_hash: str
    identity: IdentityContext


def hash_password(password: str, salt: str) -> str:
    """Return the PBKDF2-HMAC-SHA256 digest used by the account file."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    return secrets.compare_digest(hash_password(password, salt), password_hash)


def _users_file() -> Optional[Path]:
    candidates = (
        Path(settings.USERS_CONFIG_PATH),
        Path(__file__).resolve().parent / "data" / "users.json",
        Path.cwd() / "arbiter" / "backend" / "data" / "users.json",
        Path.cwd() / "data" / "users.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def _load_accounts() -> list[AccountRecord]:
    path = _users_file()
    if not path:
        logger.error("No authentication user file was found.")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        accounts = []
        for item in data:
            accounts.append(AccountRecord(
                username=str(item["username"]),
                salt=str(item["salt"]),
                password_hash=str(item["password_hash"]),
                identity=IdentityContext(
                    user_id=str(item["user_id"]),
                    display_name=str(item.get("display_name", item["user_id"])),
                    vendor=str(item.get("vendor", "")),
                    region=str(item.get("region", "")),
                    department=str(item.get("department", "")),
                    role=str(item.get("role", "")),
                    permissions=list(item.get("permissions", [])),
                    status=str(item.get("status", "active")),
                ),
            ))
        return accounts
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.error("Could not load authentication user file %s: %s", path, exc)
        return []


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(settings.SQLITE_PATH)


def _init_db() -> None:
    try:
        with _connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY, identity_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS revoked_tokens (
                    token TEXT PRIMARY KEY, revoked_at REAL NOT NULL
                )"""
            )
    except sqlite3.Error as exc:
        logger.warning("Could not initialize authentication tables: %s", exc)


_init_db()


def authenticate(username: str, password: str, vendor: Optional[str] = None) -> IdentityContext:
    """Verify credentials and return trusted, server-owned policy attributes."""
    username = (username or "").strip()
    password = (password or "").strip()
    requested_vendor = (vendor or "").strip()
    if not username or not password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    for account in _load_accounts():
        if not secrets.compare_digest(username.casefold(), account.username.casefold()):
            continue
        if requested_vendor and not secrets.compare_digest(
            requested_vendor.casefold(), account.identity.vendor.casefold()
        ):
            break
        password_ok = (
            bool(settings.AUTH_PASSWORD)
            and secrets.compare_digest(password, settings.AUTH_PASSWORD or "")
        ) or verify_password(password, account.password_hash, account.salt)
        if password_ok:
            return account.identity
        break
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")


def create_jwt(identity: IdentityContext) -> str:
    now = int(time.time())
    payload = {
        "sub": identity.user_id,
        "display_name": identity.display_name,
        "vendor": identity.vendor,
        "region": identity.region,
        "department": identity.department,
        "role": identity.role,
        "permissions": identity.permissions,
        "status": identity.status,
        "iat": now,
        "exp": now + settings.JWT_EXPIRATION_SECONDS,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt(token: str) -> IdentityContext:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.") from exc
    return IdentityContext(
        user_id=payload["sub"], display_name=payload.get("display_name", payload["sub"]),
        vendor=payload.get("vendor", ""), region=payload.get("region", ""),
        department=payload.get("department", ""), role=payload.get("role", ""),
        permissions=payload.get("permissions", []), status=payload.get("status", "active"),
        session_token=token,
    )


def create_session(response: Response, identity: IdentityContext) -> str:
    token = create_jwt(identity)
    expires_at = time.time() + settings.JWT_EXPIRATION_SECONDS
    identity_with_token = identity.model_copy(update={"session_token": token})
    _sessions[token] = (identity_with_token, expires_at)
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO auth_sessions (token, identity_json, expires_at) VALUES (?, ?, ?)",
                (token, identity_with_token.model_dump_json(), expires_at),
            )
    except sqlite3.Error as exc:
        logger.warning("Could not persist authentication session: %s", exc)
    response.set_cookie(
        key=SESSION_COOKIE, value=token, max_age=settings.JWT_EXPIRATION_SECONDS,
        httponly=True, secure=False, samesite="lax", path="/",
    )
    return token


def _extract_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    header_token = request.headers.get("X-Session-Token", "").strip()
    return header_token or request.cookies.get(SESSION_COOKIE)


def _is_revoked(token: str) -> bool:
    try:
        with _connect() as conn:
            return conn.execute("SELECT 1 FROM revoked_tokens WHERE token = ?", (token,)).fetchone() is not None
    except sqlite3.Error:
        return False


def clear_session(request: Request, response: Response) -> None:
    token = _extract_token(request)
    if token:
        _sessions.pop(token, None)
        try:
            with _connect() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
                conn.execute("INSERT OR REPLACE INTO revoked_tokens (token, revoked_at) VALUES (?, ?)", (token, time.time()))
        except sqlite3.Error as exc:
            logger.warning("Could not revoke authentication session: %s", exc)
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_identity(request: Request, optional: bool = False) -> Optional[IdentityContext]:
    token = _extract_token(request)
    if not token:
        if optional:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required.")
    if _is_revoked(token):
        if optional:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has been logged out. Please sign in again.")
    now = time.time()
    record = _sessions.get(token)
    if not record:
        try:
            with _connect() as conn:
                row = conn.execute(
                    "SELECT identity_json, expires_at FROM auth_sessions WHERE token = ?", (token,)
                ).fetchone()
            if row and row[1] >= now:
                identity = IdentityContext.model_validate_json(row[0])
                record = (identity, row[1])
                _sessions[token] = record
        except sqlite3.Error as exc:
            logger.warning("Could not recover authentication session: %s", exc)
    # A signed token is still valid after a restart even if the database is
    # unavailable; it is verified cryptographically before being accepted.
    if not record:
        try:
            identity = decode_jwt(token)
            record = (identity, now + settings.JWT_EXPIRATION_SECONDS)
            _sessions[token] = record
        except HTTPException:
            if optional:
                return None
            raise
    identity, expires_at = record
    if expires_at < now:
        _sessions.pop(token, None)
        try:
            with _connect() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        except sqlite3.Error:
            pass
        if optional:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    try:
        # Re-validate cached sessions too, so expired or tampered tokens are
        # never trusted merely because they were previously cached.
        return decode_jwt(token)
    except HTTPException:
        if optional:
            return None
        raise
