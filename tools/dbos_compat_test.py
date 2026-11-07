#!/usr/bin/env python3
"""DBOS compatibility test against Supabase Postgres (direct connection).

Tests whether DBOS can:
1. Connect via the DIRECT Postgres port (5432), not PgBouncer (6543)
2. Initialize its system tables
3. Run a trivial durable workflow

Usage:
    # Set env var with direct connection string (port 5432):
    export DATABASE_URL="postgresql://postgres.<project>:<password>@<host>:5432/postgres"

    # Or pass it as an argument:
    python tools/dbos_compat_test.py "postgresql://postgres.<project>:<password>@<host>:5432/postgres"

IMPORTANT:
    - DBOS requires direct Postgres connections (port 5432), NOT PgBouncer (6543).
    - Supabase PgBouncer in transaction mode does not support advisory locks or
      prepared statements that DBOS relies on.
    - The direct connection string can be found in Supabase Dashboard:
      Settings -> Database -> Connection string -> URI (Direct)

Results are printed to stdout. Exit code 0 = success, 1 = failure.
"""

import os
import sys
import time
import traceback


def get_connection_string() -> str:
    """Get the direct Postgres connection string."""
    # Check CLI argument first
    if len(sys.argv) > 1:
        return sys.argv[1]

    # Then check env var
    url = os.getenv("DATABASE_URL", "")
    if url:
        return url

    # Fallback: construct from Supabase project ref
    # The project ref from CLAUDE.md: qzkqjevawthyboymqrle
    # Direct connection uses port 5432 (not 6543 which is PgBouncer)
    password = os.getenv("SUPABASE_DB_PASSWORD", "")
    if password:
        return (
            f"postgresql://postgres.qzkqjevawthyboymqrle:{password}"
            f"@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        )

    print("ERROR: No database connection string found.")
    print("Set DATABASE_URL env var or pass as CLI argument.")
    print("Use the DIRECT connection string (port 5432), not PgBouncer (6543).")
    sys.exit(1)


def check_dbos_installed() -> bool:
    """Check if dbos package is installed."""
    try:
        import dbos  # noqa: F401
        version = getattr(dbos, "__version__", "unknown")
        print(f"[OK] dbos package found (version: {version})")
        return True
    except ImportError:
        print("[FAIL] dbos package not installed.")
        print("  Install with: pip install dbos")
        return False


def check_connection(conn_str: str) -> bool:
    """Verify basic Postgres connectivity."""
    try:
        import psycopg2
        conn = psycopg2.connect(conn_str, connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        print(f"[OK] Postgres connection succeeded.")
        print(f"     Version: {version[:80]}")
        return True
    except ImportError:
        print("[WARN] psycopg2 not installed; skipping raw connection test.")
        print("  Install with: pip install psycopg2-binary")
        return True  # Don't block on missing optional dep
    except Exception as e:
        print(f"[FAIL] Postgres connection failed: {e}")
        return False


def check_port(conn_str: str) -> bool:
    """Warn if using PgBouncer port (6543) instead of direct (5432)."""
    if ":6543" in conn_str:
        print("[WARN] Connection string uses port 6543 (PgBouncer).")
        print("  DBOS likely requires direct connections (port 5432).")
        print("  PgBouncer in transaction mode does not support:")
        print("    - Advisory locks (pg_advisory_lock)")
        print("    - Prepared statements")
        print("    - LISTEN/NOTIFY")
        return False
    elif ":5432" in conn_str:
        print("[OK] Connection string uses port 5432 (direct).")
        return True
    else:
        print("[INFO] Could not determine port from connection string.")
        return True


def check_advisory_locks(conn_str: str) -> bool:
    """Test advisory lock support (DBOS dependency)."""
    try:
        import psycopg2
        conn = psycopg2.connect(conn_str, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()

        # Try session-level advisory lock
        cur.execute("SELECT pg_try_advisory_lock(12345);")
        result = cur.fetchone()[0]
        if result:
            cur.execute("SELECT pg_advisory_unlock(12345);")
            print("[OK] Advisory locks work (session-level).")
        else:
            print("[WARN] Advisory lock returned false (possibly held by another session).")

        # Try transaction-level advisory lock
        conn.autocommit = False
        cur.execute("SELECT pg_advisory_xact_lock(99999);")
        conn.rollback()
        print("[OK] Advisory locks work (transaction-level).")

        cur.close()
        conn.close()
        return True
    except ImportError:
        print("[SKIP] psycopg2 not installed; cannot test advisory locks.")
        return True
    except Exception as e:
        print(f"[FAIL] Advisory lock test failed: {e}")
        print("  This strongly suggests PgBouncer in transaction mode,")
        print("  which is incompatible with DBOS.")
        return False


def test_dbos_init(conn_str: str) -> bool:
    """Attempt to initialize DBOS with the connection string."""
    try:
        from dbos import DBOS, DBOSConfig

        # Configure DBOS with the database connection
        config = DBOSConfig(
            name="boulder-rollers-compat-test",
            system_database_url=conn_str,
            run_admin_server=False,
        )

        # Initialize DBOS (creates system tables)
        print("[INFO] Initializing DBOS (creating system tables)...")
        dbos = DBOS(config=config)
        print("[OK] DBOS initialized successfully.")

        # Cleanup
        DBOS.destroy()
        print("[OK] DBOS destroyed cleanly after init.")

        return True
    except Exception as e:
        print(f"[FAIL] DBOS initialization failed: {e}")
        traceback.print_exc()
        try:
            from dbos import DBOS
            DBOS.destroy()
        except Exception:
            pass
        return False


def test_dbos_workflow(conn_str: str) -> bool:
    """Run a trivial DBOS workflow."""
    try:
        from dbos import DBOS, DBOSConfig

        config = DBOSConfig(
            name="boulder-rollers-workflow-test",
            system_database_url=conn_str,
            run_admin_server=False,
        )

        dbos = DBOS(config=config)

        @DBOS.workflow()
        def trivial_workflow(x: int) -> int:
            return x + 1

        @DBOS.step()
        def trivial_step(x: int) -> int:
            return x * 2

        @DBOS.workflow()
        def step_workflow(x: int) -> int:
            doubled = trivial_step(x)
            return doubled + 1

        # Launch DBOS
        DBOS.launch()

        # Test simple workflow
        print("[INFO] Running trivial workflow...")
        result = trivial_workflow(41)
        assert result == 42, f"Expected 42, got {result}"
        print(f"[OK] Trivial workflow returned {result} (expected 42).")

        # Test workflow with step
        print("[INFO] Running workflow with step...")
        result2 = step_workflow(10)
        assert result2 == 21, f"Expected 21, got {result2}"
        print(f"[OK] Step workflow returned {result2} (expected 21).")

        # Cleanup
        DBOS.destroy()
        print("[OK] DBOS destroyed cleanly.")

        return True
    except Exception as e:
        print(f"[FAIL] DBOS workflow test failed: {e}")
        traceback.print_exc()
        try:
            DBOS.destroy()
        except Exception:
            pass
        return False


def main():
    print("=" * 60)
    print("DBOS Compatibility Test — Supabase Direct Connection")
    print("=" * 60)
    print()

    conn_str = get_connection_string()
    # Mask password in output
    display_str = conn_str
    if "@" in conn_str and ":" in conn_str:
        parts = conn_str.split("@")
        pre_at = parts[0]
        if ":" in pre_at:
            user_part = pre_at.rsplit(":", 1)[0]
            display_str = f"{user_part}:****@{'@'.join(parts[1:])}"
    print(f"Connection: {display_str}")
    print()

    results = {}

    # Step 1: Check port
    print("--- Step 1: Port Check ---")
    results["port"] = check_port(conn_str)
    print()

    # Step 2: Check raw connection
    print("--- Step 2: Raw Connection ---")
    results["connection"] = check_connection(conn_str)
    print()

    # Step 3: Check advisory locks
    print("--- Step 3: Advisory Locks ---")
    results["advisory_locks"] = check_advisory_locks(conn_str)
    print()

    # Step 4: Check DBOS is installed
    print("--- Step 4: DBOS Package ---")
    results["installed"] = check_dbos_installed()
    print()

    if not results["installed"]:
        print("Cannot proceed without dbos package. Install with: pip install dbos")
        print()
        print("SUMMARY: INCOMPLETE (dbos not installed)")
        sys.exit(1)

    if not results["connection"]:
        print("Cannot proceed without database connection.")
        print()
        print("SUMMARY: FAILED (no database connectivity)")
        sys.exit(1)

    # Step 5: DBOS init
    print("--- Step 5: DBOS Initialization ---")
    results["init"] = test_dbos_init(conn_str)
    print()

    if not results["init"]:
        print("DBOS initialization failed. Cannot test workflows.")
        print()
        _print_summary(results)
        sys.exit(1)

    # Step 6: DBOS workflow
    print("--- Step 6: DBOS Workflow ---")
    results["workflow"] = test_dbos_workflow(conn_str)
    print()

    _print_summary(results)
    sys.exit(0 if all(results.values()) else 1)


def _print_summary(results: dict):
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for step, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {step:20s}: {status}")
    print()
    if all(results.values()):
        print("RESULT: DBOS is compatible with Supabase direct connection.")
        print()
        print("Next steps:")
        print("  1. Add 'dbos' to backend/requirements.txt")
        print("  2. Configure DATABASE_URL in .env (direct port 5432)")
        print("  3. Use @DBOS.workflow() for ride processing pipeline")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"RESULT: DBOS compatibility issues found: {', '.join(failed)}")
        print()
        print("Troubleshooting:")
        if "port" in failed:
            print("  - Use direct connection (port 5432), not PgBouncer (6543)")
        if "advisory_locks" in failed:
            print("  - Advisory locks failed. Ensure direct connection, not PgBouncer.")
        if "init" in failed:
            print("  - DBOS could not create system tables. Check permissions.")
        if "workflow" in failed:
            print("  - Workflow execution failed. Check DBOS logs for details.")


if __name__ == "__main__":
    main()
