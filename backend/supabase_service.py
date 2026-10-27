"""Server-side Supabase Auth and PostgREST helpers."""

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

DAILY_REQUEST_LIMIT = 5
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AppUser:
    id: str
    email: str
    is_admin: bool
    is_allowed: bool

    @property
    def rate_limit_exempt(self) -> bool:
        return self.is_admin or self.is_allowed


def _settings() -> tuple[str, str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not anon_key or not service_key:
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return url, anon_key, service_key


def _service_headers(service_key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _service_request(method: str, path: str, **kwargs: Any) -> Any:
    url, _, service_key = _settings()
    try:
        response = requests.request(
            method,
            f"{url}/rest/v1/{path}",
            headers=_service_headers(service_key, prefer=kwargs.pop("prefer", None)),
            timeout=10,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Supabase database request failed.") from exc
    if not response.ok:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase database request failed ({response.status_code}).",
        )
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Supabase returned an invalid response.") from exc


def _is_allowed(email: str) -> bool:
    rows = _service_request(
        "GET",
        "allowed_users",
        params={"select": "email", "email": f"eq.{email.lower()}"},
    )
    return bool(rows)


def _is_admin(email: str) -> bool:
    rows = _service_request(
        "GET",
        "admin_users",
        params={"select": "email", "email": f"eq.{email.lower()}"},
    )
    return bool(rows)


def _restriction_enabled() -> bool:
    rows = _service_request(
        "GET",
        "app_settings",
        params={"select": "restrict_sign_in", "id": "eq.main"},
    )
    if not rows:
        raise HTTPException(status_code=503, detail="Supabase app settings are not initialized.")
    return bool(rows[0]["restrict_sign_in"])


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AppUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in to continue.")

    url, anon_key, _ = _settings()
    try:
        response = requests.get(
            f"{url}/auth/v1/user",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {credentials.credentials}",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Supabase authentication is unavailable.") from exc
    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Your session is invalid or expired.")
    if not response.ok:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase authentication failed ({response.status_code}).",
        )
    try:
        user_data = response.json()
        user_id = str(user_data["id"])
        email = str(user_data["email"]).strip().lower()
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Supabase returned an invalid user session.") from exc

    app_metadata = user_data.get("app_metadata")
    providers = app_metadata.get("providers", []) if isinstance(app_metadata, dict) else []
    primary_provider = app_metadata.get("provider") if isinstance(app_metadata, dict) else None
    has_google_identity = primary_provider == "google" or (
        isinstance(providers, list) and "google" in providers
    )
    is_admin = (
        _is_admin(email)
        and bool(user_data.get("email_confirmed_at"))
        and has_google_identity
    )
    is_allowed = is_admin or _is_allowed(email)
    if _restriction_enabled() and not is_allowed:
        raise HTTPException(
            status_code=403,
            detail="Sign-in is currently limited to users on the allowed-users list.",
        )
    return AppUser(id=user_id, email=email, is_admin=is_admin, is_allowed=is_allowed)


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


def get_rate_limit_status(user: AppUser) -> dict[str, Any]:
    rows = _service_request(
        "POST",
        "rpc/get_agent_call_status",
        json={
            "p_user_id": user.id,
            "p_email": user.email,
            "p_enforce_limits": not user.rate_limit_exempt,
        },
    )
    if not rows:
        raise HTTPException(status_code=503, detail="Supabase did not return usage status.")
    return rows[0]


def claim_agent_call(user: AppUser) -> dict[str, Any]:
    rows = _service_request(
        "POST",
        "rpc/claim_agent_call",
        json={
            "p_user_id": user.id,
            "p_email": user.email,
            "p_enforce_limits": not user.rate_limit_exempt,
        },
    )
    if not rows:
        raise HTTPException(status_code=503, detail="Supabase did not return a rate-limit decision.")
    decision = rows[0]
    if not decision["allowed"]:
        retry_after = int(decision["retry_after_seconds"])
        daily_limited = decision["limit_reason"] == "daily_limit"
        raise HTTPException(
            status_code=429,
            detail={
                "message": (
                    "You have reached the limit of 5 debates for today."
                    if daily_limited
                    else "You can start another debate after your cooldown ends."
                ),
                "retry_after_seconds": retry_after,
                "available_at": decision["available_at"],
                "daily_request_count": decision["daily_requests"],
                "daily_limit": decision["daily_limit"],
                "daily_remaining": decision["daily_remaining"],
                "daily_reset_at": decision["daily_reset_at"],
                "total_requests": decision["total_requests"],
                "limit_reason": decision["limit_reason"],
            },
            headers={"Retry-After": str(retry_after)},
        )
    return decision


def get_admin_state() -> dict[str, Any]:
    settings = _service_request(
        "GET",
        "app_settings",
        params={"select": "restrict_sign_in", "id": "eq.main"},
    )
    if not settings:
        raise HTTPException(status_code=503, detail="Supabase app settings are not initialized.")
    allowed_users = _service_request(
        "GET",
        "allowed_users",
        params={"select": "email", "order": "email.asc"},
    )
    return {
        "restrict_sign_in": bool(settings[0]["restrict_sign_in"]),
        "allowed_users": [row["email"] for row in allowed_users],
    }


def update_restriction(enabled: bool) -> None:
    _service_request(
        "PATCH",
        "app_settings",
        params={"id": "eq.main"},
        json={"restrict_sign_in": enabled},
        prefer="return=minimal",
    )


def add_allowed_user(email: str) -> None:
    _service_request(
        "POST",
        "allowed_users",
        json={"email": email.strip().lower()},
        prefer="resolution=merge-duplicates,return=minimal",
    )


def remove_allowed_user(email: str) -> None:
    _service_request(
        "DELETE",
        "allowed_users",
        params={"email": f"eq.{quote(email.strip().lower(), safe='@.-_+')}"},
        prefer="return=minimal",
    )
