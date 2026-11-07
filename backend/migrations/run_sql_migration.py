#!/usr/bin/env python3
"""
Run SQL migrations using Supabase client.

Since Supabase REST API doesn't support raw SQL, this script uses
table operations to create the schema.

Usage:
    python -m migrations.run_sql_migration <migration_file>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repositories import get_supabase_client


def run_epoch_state_migration():
    """Create epoch state tables for epoch processor."""
    client = get_supabase_client()

    print("Running epoch_state migration...")

    # Check if epoch_state table exists by trying to query it
    try:
        result = client.table("epoch_state").select("id").limit(1).execute()
        print("epoch_state table already exists")
    except Exception as e:
        if "does not exist" in str(e) or "relation" in str(e).lower():
            print("Need to create epoch_state table via Supabase SQL Editor")
            print("Table does not exist - please run SQL manually")
            return False
        else:
            # Table exists, query just failed for other reason
            print(f"epoch_state check: {e}")

    # Try to insert the initial epoch state row
    try:
        # Check if row exists
        result = client.table("epoch_state").select("*").execute()
        if not result.data:
            # Insert initial row
            client.table("epoch_state").insert({
                "current_epoch": 0,
            }).execute()
            print("Inserted initial epoch_state row")
        else:
            print(f"epoch_state already has {len(result.data)} rows")
    except Exception as e:
        print(f"epoch_state insert/check failed: {e}")
        return False

    # Check epoch_distributions
    try:
        result = client.table("epoch_distributions").select("id").limit(1).execute()
        print("epoch_distributions table exists")
    except Exception as e:
        print(f"epoch_distributions check: {e}")
        if "does not exist" in str(e):
            return False

    # Check epoch_history
    try:
        result = client.table("epoch_history").select("epoch").limit(1).execute()
        print("epoch_history table exists")
    except Exception as e:
        print(f"epoch_history check: {e}")
        if "does not exist" in str(e):
            return False

    print("Migration check complete!")
    return True


if __name__ == "__main__":
    success = run_epoch_state_migration()
    sys.exit(0 if success else 1)
