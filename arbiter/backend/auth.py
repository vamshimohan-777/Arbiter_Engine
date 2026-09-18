"""Demo authentication with server-validated, trusted policy context.

This is intentionally a demo session implementation, not production SSO.  The
session token is opaque and stored only in an HttpOnly cookie; the client never
gets authority to choose vendor, region, department, or role.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import HTTPException, Request, Response, status

from schemas import IdentityContext

SESSION_COOKIE = "arbiter_session"
SESSION_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class _DemoAccount:
    username: str
    password: str
    identity: IdentityContext


_ACCOUNTS = [
    _DemoAccount("vendor-a-analyst", "arbiter-demo", IdentityContext(
        user_id="demo-vendor-a-001", display_name="Vendor A Analyst", vendor="Vendor A",
        region="India", department="Analytics", role="Analyst", permissions=["ask_policy"],
    )),
    _DemoAccount("vendor-x-analyst", "arbiter-demo", IdentityContext(
        user_id="demo-vendor-x-001", display_name="Vendor X Analyst", vendor="Vendor X",
        region="India", department="Analytics", role="Analyst", permissions=["ask_policy"],
    )),
    _DemoAccount("vendor-x-security", "arbiter-demo", IdentityContext(
        user_id="demo-vendor-x-security-001", display_name="Vendor X Security Officer", vendor="Vendor X",
        region="India", department="Security", role="Security Officer", permissions=["ask_policy"],
    )),
    _DemoAccount("vendor-y-analyst", "arbiter-demo", IdentityContext(
        user_id="demo-vendor-y-001", display_name="Vendor Y Analyst", vendor="Vendor Y",
        region="US", department="Analytics", role="Analyst", permissions=["ask_policy"],
    )),
    _DemoAccount("vendor-y-finance-eu", "arbiter-demo", IdentityContext(
        user_id="demo-vendor-y-finance-eu-001", display_name="Vendor Y Finance Analyst", vendor="Vendor Y",
        region="EU", department="Finance", role="Analyst", permissions=["ask_policy"],
    )),
]

_sessions: Dict[str, tuple[IdentityContext, float]] = {}


def authenticate(username: str, password: str, vendor: Optional[str] = None) -> IdentityContext:
    for account in _ACCOUNTS:
        if (
            secrets.compare_digest(username, account.username)
            and secrets.compare_digest(password, account.password)
            and (not vendor or vendor.casefold() == account.identity.vendor.casefold())
        ):
            return account.identity
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid demo credentials.")


def create_session(response: Response, identity: IdentityContext) -> None:
    token = secrets.token_urlsafe(32)
    _sessions[token] = (identity, time.time() + SESSION_TTL_SECONDS)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=False,  # Local demo; deploy behind HTTPS with this enabled.
        samesite="lax",
        path="/",
    )


def clear_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_identity(request: Request) -> IdentityContext:
    token = request.cookies.get(SESSION_COOKIE)
    record = _sessions.get(token or "")
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required.")
    identity, expires_at = record
    if expires_at < time.time():
        _sessions.pop(token or "", None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    return identity
