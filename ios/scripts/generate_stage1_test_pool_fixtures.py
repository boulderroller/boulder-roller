"""Offline native vectors using the production builder with its fixture seam.

No RPC, signing, or submission. Run with the backend Python environment.
"""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/scripts')]
# Imports need auth configuration; these offline-only constants are never used
# to authenticate or contact a server.
os.environ.setdefault('ACCESS_TOKEN_SECRET', 'offline-stage1-fixture-access-secret-00000000')
os.environ.setdefault('REFRESH_TOKEN_SECRET', 'offline-stage1-fixture-refresh-secret-0000000')
import generate_stage1_transaction_fixtures as vectors
from solders.pubkey import Pubkey

mint = str(Pubkey(bytes([88] * 32)))
provider = str(Pubkey(bytes([77] * 32)))
# Preserve the three pinned pools and include the configured fourth provider.
vectors.PROVIDERS[mint] = provider
vectors.JITO = mint
vectors.USDC = mint  # Exercise cash claims in the configured pool's mint too.
rows = asyncio.run(vectors.build_records())
for row in rows:
    row['testPool'] = {'mint': mint, 'provider': provider}
path = ROOT / 'ios/BoulderRollerTests/Fixtures/stage1-testpool-transactions.json'
path.write_text(json.dumps(rows, indent=2) + '\n')
print(f'{len(rows)} offline test-pool vectors: {path}')
