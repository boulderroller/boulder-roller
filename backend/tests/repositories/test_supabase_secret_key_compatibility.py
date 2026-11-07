"""Compatibility coverage for Supabase's modern server-side API keys."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.config import load_supabase_settings
from app.repositories.base import _build_supabase_client
from app.supabase_client import (
    create_backend_supabase_client,
    server_api_headers,
)


@pytest.fixture(autouse=True)
def clear_supabase_caches():
    """Keep a failed test from leaking its configured client into another test."""
    load_supabase_settings.cache_clear()
    _build_supabase_client.cache_clear()
    yield
    _build_supabase_client.cache_clear()
    load_supabase_settings.cache_clear()


def test_server_api_headers_keep_bearer_auth_for_legacy_jwt_keys():
    legacy_key = "header.payload.signature"

    assert server_api_headers(legacy_key) == {
        "apikey": legacy_key,
        "Authorization": f"Bearer {legacy_key}",
    }


def test_server_api_headers_do_not_project_modern_secrets_as_bearer_tokens():
    modern_key = "sb_secret_" + "x" * 40

    assert server_api_headers(modern_key) == {"apikey": modern_key}


def test_legacy_jwt_keys_continue_through_the_supabase_sdk(monkeypatch):
    legacy_key = "header.payload.signature"
    sentinel = object()
    received = {}

    def fake_create_client(url, key, *, options):
        received.update(url=url, key=key, options=options)
        return sentinel

    monkeypatch.setattr("app.supabase_client.create_client", fake_create_client)

    client = create_backend_supabase_client(
        "https://example.supabase.co",
        legacy_key,
    )

    assert client is sentinel
    assert received["url"] == "https://example.supabase.co"
    assert received["key"] == legacy_key


def test_repository_client_accepts_modern_supabase_secret_key(monkeypatch):
    modern_key = "sb_secret_" + "x" * 40
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", modern_key)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    client = _build_supabase_client()

    assert client is not None
    assert client.postgrest.session.headers["apikey"] == modern_key
    assert "authorization" not in client.postgrest.session.headers
    assert client.storage.session.headers["apikey"] == modern_key
    assert "authorization" not in client.storage.session.headers


def test_executed_data_rpc_and_storage_requests_never_bearer_modern_secret():
    modern_key = "sb_secret_" + "x" * 40
    received = []

    class CaptureHandler(BaseHTTPRequestHandler):
        def _capture(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            received.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

        do_GET = _capture
        do_POST = _capture

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        client = create_backend_supabase_client(base_url, modern_key)

        client.table("users").select("id").execute()
        client.rpc("get_current_epoch", {}).execute()
        client.storage.from_("ride-uploads").list()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert [request["path"].split("?")[0] for request in received] == [
        "/rest/v1/users",
        "/rest/v1/rpc/get_current_epoch",
        "/storage/v1/object/list/ride-uploads",
    ]
    for request in received:
        assert request["headers"]["apikey"] == modern_key
        assert "authorization" not in request["headers"]
