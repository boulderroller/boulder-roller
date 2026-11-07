"""Stored release admission, independent of projection freshness; never RPC."""
import os


def enabled(name):
    return os.getenv(name, "").strip().lower() in ("1", "true")


async def stored_network():
    from ..solana_direct import load_readonly_config
    from ..db_pool import get_pool
    from ..program_compatibility import STAGE1_OBSERVED_VERSION_SQL
    if enabled("SOLANA_STUB"):
        return None
    try:
        config = load_readonly_config()
        pool = await get_pool()
        async with pool.acquire() as connection:
            return await connection.fetchrow(f"""SELECT n.program,n.genesis FROM stage1_indexer_network n
                JOIN program_version_observations v ON v.genesis_hash=n.genesis AND v.program_id=n.program
                WHERE n.program=$1 AND {STAGE1_OBSERVED_VERSION_SQL}""", str(config.program_id))
    except Exception:
        return None


async def availability():
    reads, actions = enabled("STAGE1_UI_ENABLED"), enabled("STAGE1_ACTIONS_ENABLED")
    admitted = bool(await stored_network()) if reads or actions else False
    return {"live": reads and admitted, "actions": actions and admitted}
