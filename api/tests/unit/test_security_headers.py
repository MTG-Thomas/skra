"""
Unit tests for security headers middleware.

Tests that all security headers are correctly added to HTTP responses.
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.core.security_headers import SecurityHeadersMiddleware, add_security_headers


@pytest.fixture
def app_with_security_headers():
    """Create a test app with security headers middleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    @app.get("/error")
    def error_endpoint():
        return JSONResponse({"detail": "Test error"}, status_code=500)

    return app


@pytest.fixture
def client(app_with_security_headers):
    """Create a test client."""
    return TestClient(app_with_security_headers)


class TestSecurityHeadersMiddleware:
    """Tests for security headers middleware."""

    def test_x_content_type_options_header(self, client):
        """Test X-Content-Type-Options header is set to nosniff."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_header(self, client):
        """Test X-Frame-Options header is set to DENY."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_x_xss_protection_header(self, client):
        """Test X-XSS-Protection header is set for legacy browsers."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["X-XSS-Protection"] == "1; mode=block"

    def test_referrer_policy_header(self, client):
        """Test Referrer-Policy header is set."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_cross_origin_resource_policy_header(self, client):
        """Test Cross-Origin-Resource-Policy is set for the API boundary."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["Cross-Origin-Resource-Policy"] == "cross-origin"

    def test_cache_headers_prevent_storing_api_responses(self, client):
        """Test API responses are not stored by shared or browser caches."""
        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"

    def test_permissions_policy_header(self, client):
        """Test Permissions-Policy header is set with safe defaults."""
        response = client.get("/test")
        assert response.status_code == 200
        permissions_policy = response.headers["Permissions-Policy"]
        assert "camera=()" in permissions_policy
        assert "microphone=()" in permissions_policy
        assert "geolocation=()" in permissions_policy
        assert "payment=()" in permissions_policy

    def test_csp_header_in_development(self, client, monkeypatch):
        """Test CSP header is more permissive in development."""
        from src.config import clear_settings_cache

        monkeypatch.setenv("SKRA_ENVIRONMENT", "development")
        clear_settings_cache()

        response = client.get("/test")
        assert response.status_code == 200
        csp = response.headers["Content-Security-Policy"]
        # Development CSP should allow unsafe-eval for Vite HMR
        assert "'unsafe-eval'" in csp
        assert "ws:" in csp or "wss:" in csp
        clear_settings_cache()

    def test_security_headers_on_error_response(self, client):
        """Test security headers are present even on error responses."""
        response = client.get("/error")
        assert response.status_code == 500
        # Security headers should still be present
        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers
        assert "Content-Security-Policy" in response.headers

    def test_all_security_headers_present(self, client):
        """Test that all expected security headers are present."""
        response = client.get("/test")
        assert response.status_code == 200

        required_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
            "Cross-Origin-Resource-Policy",
            "Cache-Control",
            "Pragma",
            "Expires",
            "Permissions-Policy",
            "Content-Security-Policy",
        ]

        for header in required_headers:
            assert header in response.headers, f"Missing security header: {header}"


class TestAddSecurityHeadersFunction:
    """Tests for the add_security_headers helper function."""

    def test_add_security_headers_function(self):
        """Test that add_security_headers function works correctly."""
        app = FastAPI()

        # Add the middleware using the helper function
        add_security_headers(app)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


class TestHSTSHeader:
    """Tests for HSTS (Strict-Transport-Security) header."""

    def test_hsts_header_in_production(self, monkeypatch):
        """Test HSTS header is set in production."""
        from src.config import clear_settings_cache

        monkeypatch.setenv("SKRA_ENVIRONMENT", "production")
        clear_settings_cache()

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "Strict-Transport-Security" in response.headers
        hsts = response.headers["Strict-Transport-Security"]
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
        clear_settings_cache()

    def test_hsts_header_not_in_development(self, client, monkeypatch):
        """Test HSTS header is NOT set in development (development is default in tests)."""
        from src.config import clear_settings_cache

        monkeypatch.setenv("SKRA_ENVIRONMENT", "development")
        clear_settings_cache()

        # Create new client with development settings
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        # HSTS should not be present in development
        assert "Strict-Transport-Security" not in response.headers
        clear_settings_cache()

    def test_exception_response_has_production_security_headers(self, monkeypatch):
        """Test production exception responses keep security headers."""
        from src.config import clear_settings_cache
        from src.main import create_app

        monkeypatch.setenv("SKRA_ENVIRONMENT", "production")
        clear_settings_cache()

        app = create_app()

        @app.get("/boom")
        def boom():
            raise RuntimeError("test failure")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")

        assert response.status_code == 500
        assert "Strict-Transport-Security" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers
        assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
        assert response.json()["message"] == "An unexpected error occurred"
        clear_settings_cache()


class TestCSPDirectives:
    """Tests for Content-Security-Policy directives."""

    def test_csp_default_src_self(self, client):
        """Test CSP default-src is 'self'."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp

    def test_csp_frame_ancestors_none(self, client):
        """Test CSP frame-ancestors is 'none' (prevents embedding)."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp

    def test_csp_object_src_none(self, client):
        """Test CSP object-src is 'none' (prevents Flash/Java)."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "object-src 'none'" in csp

    def test_csp_form_action_self(self, client):
        """Test CSP form-action is 'self'."""
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        assert "form-action 'self'" in csp
