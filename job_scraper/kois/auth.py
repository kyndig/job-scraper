from __future__ import annotations

REVIEW_TOKEN_COOKIE = "kois_review_token"
UNPROTECTED_PATHS = {
    "/health",
    "/ui/login",
    "/openapi.json",
    "/docs",
    "/redoc",
}


def extract_review_token(authorization: str | None, cookie: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    if cookie:
        return cookie
    return None


def review_access_decision(
    path: str, provided: str | None, expected: str | None
) -> str:
    if not expected:
        return "allow"
    if path in UNPROTECTED_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
        return "allow"
    if provided == expected:
        return "allow"
    if path.startswith("/ui"):
        return "login"
    return "unauthorized"
