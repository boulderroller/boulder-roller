"""Offline release boundary tests; validator outcomes are tested separately."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "scripts/check-deployable-artifact.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

class ArtifactBoundary(unittest.TestCase):
    def test_default_idl_has_no_devnet_registration_or_account(self):
        idl = json.loads((ROOT / 'idl/boulder_rollers.json').read_text())
        self.assertNotIn('registerStage1TestPool', [x['name'] for x in idl['instructions']])
        self.assertNotIn('Stage1TestPool', [x['name'] for x in idl['accounts']])

    def test_dispatch_without_marker_is_still_devnet_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / 'program.so'
            elf.write_bytes(b'\x7fELF' + guard.pubkey(guard.PRODUCTION_ID) + b'global:register_stage1_test_pool')
            with self.assertRaises(ValueError): guard.check(elf, 'mainnet-beta')
            self.assertEqual(len(guard.check(elf, 'devnet')), 64)

    def test_test_setup_helpers_are_never_deployable(self):
        idl = json.loads((ROOT / 'idl/boulder_rollers.json').read_text())
        names = [x['name'] for x in idl['instructions']]
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / 'program.so'
            for dispatch in guard.SMOKE_DISPATCH:
                camel = ''.join(p if i == 0 else p.title() for i, p in enumerate(dispatch[7:].decode().split('_')))
                self.assertNotIn(camel, names)
                elf.write_bytes(b'\x7fELF' + guard.pubkey(guard.PRODUCTION_ID) + dispatch)
                for cluster in ['mainnet-beta', 'devnet']:
                    with self.assertRaises(ValueError): guard.check(elf, cluster)

    def test_three_builds_and_explicit_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / "program.so"
            base = b"\x7fELF" + guard.pubkey(guard.PRODUCTION_ID)
            for marker, allowed in [(b"", ["mainnet-beta", "devnet"]),
                                    (b"BOULDERROLLER_STAGE1_DEVNET_TEST_POOL", ["devnet"]),
                                    (b"BOULDERROLLER_STAGE1_LOCALNET_ONLY", [])]:
                elf.write_bytes(base + marker)
                for cluster in ["mainnet-beta", "devnet", "localnet", "unknown"]:
                    if cluster in allowed:
                        self.assertEqual(len(guard.check(elf, cluster)), 64)
                    else:
                        with self.assertRaises(ValueError): guard.check(elf, cluster)

if __name__ == "__main__": unittest.main()
