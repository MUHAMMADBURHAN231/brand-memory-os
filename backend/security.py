"""Authentication and request-security primitives for Brand Memory OS."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import socket
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlparse

import bcrypt
from fastapi import HTTPException, Request, Response

SESSION_COOKIE = "bmos_session"
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "14"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
PASSWORD_MIN_LENGTH = 10


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db, response: Response, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires_at = utcnow() + timedelta(days=SESSION_DAYS)
    await db.sessions.insert_one({
        "token_hash": hash_token(token), "user_id": user_id, "csrf_token": csrf,
        "expires_at": expires_at, "created_at": utcnow(),
    })
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
        secure=COOKIE_SECURE, samesite="lax", path="/",
    )
    return csrf


async def get_session(db, request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Authentication required")
    session = await db.sessions.find_one({
        "token_hash": hash_token(token), "expires_at": {"$gt": utcnow()},
    }, {"_id": 0})
    if not session:
        raise HTTPException(401, "Session expired")
    return session


async def require_user(db, request: Request, *, csrf: bool = False) -> dict:
    session = await get_session(db, request)
    if csrf and request.headers.get("X-CSRF-Token") != session.get("csrf_token"):
        raise HTTPException(403, "Invalid CSRF token")
    user = await db.users.find_one({"id": session["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "Account unavailable")
    user["csrf_token"] = session["csrf_token"]
    return user


async def destroy_session(db, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.sessions.delete_one({"token_hash": hash_token(token)})
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", secure=COOKIE_SECURE)


def validate_public_url(value: str) -> str:
    """Reject non-HTTP, credentialed, localhost and private-network URLs (SSRF)."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("Use a public http(s) website URL")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Private network URLs are not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Website hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private network URLs are not allowed")
    return raw


class RateLimiter:
    """Redis-backed multi-instance limiter with a safe single-process fallback."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._redis = None
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            from redis.asyncio import from_url
            self._redis = from_url(redis_url, encoding="utf-8", decode_responses=True)

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        if self._redis is not None:
            redis_key = f"bmos:rate:{key}"
            count = await self._redis.incr(redis_key)
            if count == 1:
                await self._redis.expire(redis_key, window_seconds)
            if count > limit:
                raise HTTPException(429, "Too many requests; try again later")
            return
        import time
        current = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= current - window_seconds:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(429, "Too many requests; try again later")
            events.append(current)


limiter = RateLimiter()
