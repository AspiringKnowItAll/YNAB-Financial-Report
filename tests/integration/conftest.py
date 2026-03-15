"""
Integration test fixtures.

Uses httpx.ASGITransport to send requests directly to the FastAPI ASGI app
without starting a real server. The app lifespan (DB migrations, scheduler)
is intentionally NOT triggered — each test fixture sets only what it needs.
"""

import os

import httpx
import pytest

from app.main import app

_real_exists = os.path.exists


@pytest.fixture
def no_salt(monkeypatch):
    """Simulate a fresh install: master.salt does not exist."""
    monkeypatch.setattr(
        "os.path.exists",
        lambda p: False if p == "/data/master.salt" else _real_exists(p),
    )


@pytest.fixture
def salt_exists(monkeypatch):
    """Simulate a configured install: master.salt exists on disk."""
    monkeypatch.setattr(
        "os.path.exists",
        lambda p: True if p == "/data/master.salt" else _real_exists(p),
    )


@pytest.fixture
async def client():
    """
    Async HTTP test client backed by the FastAPI ASGI app.

    The lifespan is NOT started — we control app.state directly in tests.
    """
    app.state.master_key = None  # App starts locked
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.state.master_key = None  # Reset after test
