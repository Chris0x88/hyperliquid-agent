"""FastAPI application factory for the Dashboard backend."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.api.dependencies import get_data_dir
from web.api.routers import account, health, daemon, thesis, config, watchlist, authority, logs, news, strategies, charts, alerts


AUTH_TOKEN_PATH = Path(__file__).resolve().parent.parent / ".auth_token"


def _ensure_auth_token() -> str:
    """Generate a bearer token on first launch, persist to .auth_token."""
    if AUTH_TOKEN_PATH.exists():
        return AUTH_TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(48)
    AUTH_TOKEN_PATH.write_text(token)
    AUTH_TOKEN_PATH.chmod(0o600)
    return token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    app.state.auth_token = _ensure_auth_token()
    app.state.data_dir = get_data_dir()
    yield


def create_app() -> FastAPI:
    """Factory that returns a configured FastAPI instance."""
    app = FastAPI(
        title="HyperLiquid Dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — local-only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(account.router, prefix="/api/account", tags=["account"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(daemon.router, prefix="/api/daemon", tags=["daemon"])
    app.include_router(thesis.router, prefix="/api/thesis", tags=["thesis"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
    app.include_router(authority.router, prefix="/api/authority", tags=["authority"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
    app.include_router(news.router, prefix="/api/news", tags=["news"])
    app.include_router(strategies.router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(charts.router, prefix="/api/charts", tags=["charts"])
    app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])

    return app
