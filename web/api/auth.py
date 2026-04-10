"""Bearer token authentication for local API access."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request


async def verify_token(request: Request, authorization: str = Header(default="")) -> None:
    """Validate bearer token against the stored auth token.

    Skip auth in development when no token file exists.
    """
    token = getattr(request.app.state, "auth_token", None)
    if not token:
        # No token configured — dev mode, allow all
        return

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    provided = authorization[7:]
    if provided != token:
        raise HTTPException(status_code=403, detail="Invalid token")
