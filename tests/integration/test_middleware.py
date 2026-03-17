"""
Integration tests for the auth gate middleware (app/main.py: auth_gate).

Tests the redirect chain enforced on every non-exempt request:
  1. No master.salt → /first-run
  2. Salt exists + app locked → /unlock
  3. Exempt paths always pass through (no redirect)
  4. /health always returns 200

The app lifespan is NOT started in these tests — app.state and os.path.exists
are controlled directly via fixtures and monkeypatch.
"""



# ---------------------------------------------------------------------------
# Health check — always accessible, bypasses middleware entirely
# ---------------------------------------------------------------------------

class TestHealthCheck:
    async def test_health_returns_200(self, client):
        r = await client.get("/health")
        assert r.status_code == 200

    async def test_health_returns_ok_json(self, client):
        r = await client.get("/health")
        assert r.json() == {"status": "ok"}

    async def test_health_accessible_when_locked(self, client, no_salt):
        # Even with no setup done, health check must pass
        r = await client.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Step 1: No master.salt → redirect to /first-run
# ---------------------------------------------------------------------------

class TestNoSaltRedirects:
    async def test_root_redirects_to_first_run(self, client, no_salt):
        r = await client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"

    async def test_settings_redirects_to_first_run(self, client, no_salt):
        r = await client.get("/settings", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"

    async def test_reports_redirects_to_first_run(self, client, no_salt):
        r = await client.get("/reports", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"

    async def test_api_sync_redirects_to_first_run(self, client, no_salt):
        r = await client.post("/api/sync/trigger", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"

    async def test_setup_redirects_to_first_run(self, client, no_salt):
        r = await client.get("/setup", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"


# ---------------------------------------------------------------------------
# Step 2: Salt exists + app locked → redirect to /unlock
# ---------------------------------------------------------------------------

class TestLockedAppRedirects:
    async def test_root_redirects_to_unlock(self, client, salt_exists):
        r = await client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/unlock"

    async def test_settings_redirects_to_unlock(self, client, salt_exists):
        r = await client.get("/settings", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/unlock"

    async def test_reports_redirects_to_unlock(self, client, salt_exists):
        r = await client.get("/reports", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/unlock"

    async def test_api_sync_redirects_to_unlock(self, client, salt_exists):
        r = await client.post("/api/sync/trigger", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/unlock"


# ---------------------------------------------------------------------------
# Exempt paths — middleware must NOT redirect these, regardless of state
# ---------------------------------------------------------------------------

class TestExemptPaths:
    async def test_first_run_exempt_before_setup(self, client, no_salt):
        r = await client.get("/first-run", follow_redirects=False)
        # Must reach the router — not redirected to /first-run itself
        assert r.headers.get("location") != "/first-run"

    async def test_first_run_exempt_when_locked(self, client, salt_exists):
        r = await client.get("/first-run", follow_redirects=False)
        assert r.headers.get("location") != "/unlock"

    async def test_unlock_exempt_when_locked(self, client, salt_exists):
        r = await client.get("/unlock", follow_redirects=False)
        assert r.headers.get("location") != "/unlock"

    async def test_recovery_exempt_when_locked(self, client, salt_exists):
        r = await client.get("/recovery", follow_redirects=False)
        assert r.headers.get("location") != "/unlock"

    async def test_static_prefix_exempt(self, client, no_salt):
        # /static/ prefix is always exempt — even a 404 for a missing file
        # is fine; the important thing is no redirect to /first-run
        r = await client.get("/static/nonexistent.css", follow_redirects=False)
        assert r.headers.get("location") != "/first-run"


# ---------------------------------------------------------------------------
# Redirect target is consistent regardless of method
# ---------------------------------------------------------------------------

class TestMethodAgnosticRedirects:
    async def test_post_also_redirected(self, client, no_salt):
        r = await client.post("/setup", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"

    async def test_put_also_redirected(self, client, no_salt):
        r = await client.put("/settings", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/first-run"
