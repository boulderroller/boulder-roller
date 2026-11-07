"""Construct the backend Supabase client for either supported server key format."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from postgrest import SyncPostgrestClient
from storage3 import SyncStorageClient
from supabase import Client, create_client
from supabase.lib.client_options import ClientOptions


MODERN_SECRET_PREFIX = "sb_secret_"


def server_api_headers(supabase_key: str) -> Dict[str, str]:
    """Return server API headers appropriate for the supplied key format."""
    headers = {"apikey": supabase_key}
    if not supabase_key.startswith(MODERN_SECRET_PREFIX):
        headers["Authorization"] = f"Bearer {supabase_key}"
    return headers


class ModernSecretClient:
    """Data and Storage client for a modern server-only Supabase secret key.

    Supabase-py 2.3 rejects non-JWT API keys before making a request. The
    application only uses the Data API and Storage API from its shared backend
    client, so those clients can receive the modern key directly via the
    ``apikey`` header. In particular, the secret is not projected as a bearer
    token.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        options: ClientOptions,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_key = supabase_key
        self.options = options

        headers: Dict[str, str] = {
            key: value
            for key, value in options.headers.items()
            if key.lower() != "authorization"
        }
        headers.update(server_api_headers(supabase_key))
        headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

        self._postgrest = SyncPostgrestClient(
            f"{self.supabase_url}/rest/v1",
            schema=options.schema,
            headers=dict(headers),
            timeout=options.postgrest_client_timeout,
        )
        self._storage = SyncStorageClient(
            f"{self.supabase_url}/storage/v1",
            headers=dict(headers),
            timeout=options.storage_client_timeout,
        )

    @property
    def postgrest(self) -> SyncPostgrestClient:
        return self._postgrest

    @property
    def storage(self) -> SyncStorageClient:
        return self._storage

    def table(self, table_name: str) -> Any:
        return self._postgrest.table(table_name)

    def from_(self, table_name: str) -> Any:
        return self._postgrest.from_(table_name)

    def rpc(self, function_name: str, params: Optional[Dict[Any, Any]] = None) -> Any:
        return self._postgrest.rpc(function_name, params or {})

    def schema(self, schema_name: str) -> SyncPostgrestClient:
        return self._postgrest.schema(schema_name)


BackendSupabaseClient = Union[Client, ModernSecretClient]


def create_backend_supabase_client(
    supabase_url: str,
    supabase_key: str,
    *,
    options: Optional[ClientOptions] = None,
) -> BackendSupabaseClient:
    """Create the shared backend client without misusing modern secret keys."""
    client_options = options or ClientOptions()
    if supabase_key.startswith(MODERN_SECRET_PREFIX):
        return ModernSecretClient(supabase_url, supabase_key, client_options)
    return create_client(supabase_url, supabase_key, options=client_options)
