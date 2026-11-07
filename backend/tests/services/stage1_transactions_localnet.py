"""Real local RPC + PostgreSQL through the HTTP action routes.

Authentication is an explicit local wallet fixture. No provider login, real
ride, or elapsed-world claim is made. Operation writes use the production
Balance sink with a test-only PostgreSQL adapter for its PostgREST transport.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import subprocess
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlparse
import uuid


class LocalOperationTable:
    def __init__(self, dsn):
        self.dsn, self.filters, self.row, self.method = dsn, [], None, "select"

    def table(self, name):
        if name != "balance_operations": raise ValueError("local operation table only")
        return LocalOperationTable(self.dsn)

    def insert(self, row): self.row, self.method = row, "insert"; return self
    def upsert(self, row): self.row, self.method = row, "upsert"; return self
    def select(self, *args, **kwargs): return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def limit(self, limit): return self

    def execute(self):
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extras import Json, RealDictCursor
        with psycopg2.connect(self.dsn) as c, c.cursor(cursor_factory=RealDictCursor) as cursor:
            if self.row is not None:
                columns = list(self.row)
                query = sql.SQL("INSERT INTO balance_operations ({}) VALUES ({})").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)), sql.SQL(",").join(sql.Placeholder() for _ in columns))
                if self.method == "upsert":
                    query += sql.SQL(" ON CONFLICT (operation_id) DO UPDATE SET ") + sql.SQL(",").join(
                        sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in columns if k != "operation_id")
                cursor.execute(query, [Json(v) if isinstance(v, dict) else v for v in self.row.values()])
                return SimpleNamespace(data=[self.row])
            query = sql.SQL("SELECT * FROM balance_operations WHERE ") + sql.SQL(" AND ").join(
                sql.SQL("{}=%s").format(sql.Identifier(k)) for k, _ in self.filters)
            cursor.execute(query, [v for _, v in self.filters])
            return SimpleNamespace(data=[dict(r) for r in cursor.fetchall()])


async def execute(request):
    import asyncpg
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    from solders.message import to_bytes_versioned
    from fastapi import FastAPI
    import httpx
    from app.db_pool import close_pool
    from app.dependencies import AuthenticatedUser, get_current_user, get_repository
    from app.routes import stage1, balance_operations
    from tests.services.stage1_keeper_schema import schema
    from tests.services.stage1_keeper_localnet import seed_canon
    from app.middleware.rate_limiter import rate_limiter
    from solana.rpc.providers.async_http import AsyncHTTPProvider

    dsn = os.environ["STAGE1_KEEPER_TEST_DSN"]
    if urlparse(dsn).hostname != "127.0.0.1" or not urlparse(dsn).path.startswith("/keeper_"):
        raise ValueError("disposable local database only")
    connection = await asyncpg.connect(dsn)
    original_rpc = AsyncHTTPProvider.make_request
    counts, probes = Counter(), []
    async def counted_rpc(self, body, parser):
        counts[type(body).__name__] += 1
        return await original_rpc(self, body, parser)
    AsyncHTTPProvider.make_request = counted_rpc
    rate_limiter._kv_init_attempted = True  # Real local fallback limiter, no NATS dependency.
    try:
        if request["action"] == "initialize":
            await schema(connection)
            await seed_canon(connection, request["canon_id"])
            # Replace the empty account-deletion bootstrap stub with canonical migration 172.
            assert await connection.fetchval("SELECT count(*) FROM balance_operations") == 0
            await connection.execute("DROP TABLE balance_operations")
            await connection.execute((Path(__file__).parents[2] / "sql/172_balance_operations.sql").read_text())
            return {"initialized": True}
        signer = Keypair.from_bytes(bytes(json.loads(Path(request["signer_path"]).read_text())))
        wallet = str(signer.pubkey())
        user = await connection.fetchval("SELECT user_id FROM br_get_or_create_active_user($1,$2)", uuid.uuid5(uuid.NAMESPACE_OID, wallet), wallet)
        app = FastAPI()
        app.include_router(stage1.router, prefix="/stage1")
        app.include_router(balance_operations.router, prefix="/balance/operations")
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=wallet, user_id=str(user), device_id="localnet-fixture")
        app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=LocalOperationTable(dsn))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localnet") as client:
            async def http(method, path, **kwargs):
                before = counts.copy()
                result = await client.request(method, path, **kwargs)
                delta = counts - before
                probes.append({"path": path, "method": method, "rpc": dict(delta), "total": sum(delta.values())})
                return result
            path = "/stage1/me/" + request["action"]
            body = request.get("payload", {})
            intent = request.get("client_intent")
            if request["action"] == "registration": intent = {"kind": "stage1_registration"}
            if request["action"] == "self-claim":
                discovered = await http("GET", "/stage1/me/claims")
                assert discovered.status_code == 200, discovered.text
                available = [entry["reference"] for entry in discovered.json()["claims"]]
                assert all(ref in available for ref in body["claims"]), discovered.text
                warm = await http("GET", "/stage1/me/claims")
                assert warm.status_code == 200 and warm.json() == discovered.json(), warm.text
                assert probes[-1]["total"] == 2, probes[-1]  # Live config + genesis gate only.
                selected = [entry["intent"] for entry in discovered.json()["claims"] if entry["reference"] in body["claims"]]
                intent = {**selected[0], "claims": [leaf for entry in selected for leaf in entry["claims"]]}
                if body.get("lookup_table"): intent["single"] = True
            response = await http("POST", path + "/prepare", json=body)
            if request.get("expect_status"):
                assert response.status_code == request["expect_status"], response.text
                return {"status": response.status_code}
            assert response.status_code == 200, response.text
            prepared = response.json()["prepared_transaction"]
            checked = {}
            if intent is not None:
                # Person input / independently fetched discovery context above,
                # never the prepare response's echoed intent.
                check = {"rpc": request["rpc"], "wallet": wallet, "intent": intent,
                         "prepared": {**prepared, "lastValidBlockHeight": prepared["last_valid_block_height"]}}
                checked = json.loads(subprocess.check_output(["node", "--no-warnings", "--experimental-strip-types", os.environ["STAGE1_PORTAL_CHECK"]],
                    input=json.dumps(check), text=True, timeout=60, env={**os.environ, "NODE_OPTIONS": ""}))
                check["lookups"] = checked["lookups"]
                checked.update(json.loads(subprocess.check_output([os.environ["STAGE1_NATIVE_CHECK"]], input=json.dumps(check), text=True, timeout=60)))
            tx = VersionedTransaction.from_bytes(base64.b64decode(prepared["transaction"]))
            signatures = list(tx.signatures)
            signatures[list(tx.message.account_keys).index(signer.pubkey())] = signer.sign_message(to_bytes_versioned(tx.message))
            tx = VersionedTransaction.populate(tx.message, signatures)
            response = await http("POST", path, json={**body, "signed_transaction": base64.b64encode(bytes(tx)).decode(),
                "last_valid_block_height": prepared["last_valid_block_height"], "client_request_id": str(uuid.uuid4())})
            assert response.status_code == 200, response.text
            operation = response.json()["operation"]
            assert operation["confirmation_status"] in ("confirmed", "finalized"), operation
            read = await http("GET", "/balance/operations/" + operation["operation_id"])
            assert read.status_code == 200 and read.json()["operation_id"] == operation["operation_id"], read.text
            return {"operation": operation, "read": read.json(), "prepared": prepared, "client_checks": checked, "rpc_requests": probes}
    finally:
        AsyncHTTPProvider.make_request = original_rpc
        await close_pool()
        await connection.close()


if __name__ == "__main__":
    request = json.load(sys.stdin)
    rpc = urlparse(request["rpc"])
    if rpc.scheme != "http" or rpc.hostname != "127.0.0.1": raise ValueError("localnet only")
    os.environ.update(SOLANA_RPC_URL=request["rpc"], BOULDER_ROLLERS_PROGRAM_ID=request["program"],
        FEE_PAYER_KEYPAIR=request["payer_path"], BACKEND_AUTHORITY_KEYPAIR=request["payer_path"], EXPECTED_BACKEND_AUTHORITY="",
        STAGE1_ACTIONS_ENABLED="true", DATABASE_URL=os.environ["STAGE1_KEEPER_TEST_DSN"],
        ACCESS_TOKEN_SECRET="localnet-only", REFRESH_TOKEN_SECRET="localnet-only", ENVIRONMENT="test")
    print(json.dumps(asyncio.run(execute(request))))
