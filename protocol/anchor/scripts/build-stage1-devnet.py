#!/usr/bin/env python3
"""Build the real devnet ELF and its isolated, explicitly selected IDL."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.anchor/stage1-devnet'


def main():
    # Never compile an ELF from the IDL-only wrapper copy.
    protected = [ROOT / 'target/deploy/boulder_rollers.so', ROOT / 'idl/boulder_rollers.json',
                 ROOT / 'clients/typescript/boulder_rollers.ts', ROOT / 'abi/v0x4d.json', ROOT / 'abi/v0x4e.json',
                 ROOT.parents[1] / 'backend/idl/boulder_rollers.json',
                 ROOT.parents[1] / 'web/portal/public/idl/boulder_rollers.json']
    before = {p: hashlib.sha256(p.read_bytes()).digest() for p in protected}
    (OUT / 'deploy').mkdir(parents=True, exist_ok=True)
    (OUT / 'idl').mkdir(exist_ok=True)
    subprocess.run(['cargo', 'build-sbf', '--manifest-path', str(ROOT / 'programs/boulder_rollers/Cargo.toml'),
                    '--features', 'stage1-devnet', '--sbf-out-dir', str(OUT / 'deploy')], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='stage1-devnet-idl-', dir=ROOT / '.anchor') as directory:
        work = Path(directory)
        parser = work / 'programs/boulder_rollers'
        shutil.copytree(ROOT / 'programs/boulder_rollers/src', parser / 'src')
        for file in ['Cargo.toml', 'Cargo.lock', 'Anchor.toml']:
            shutil.copy2(ROOT / file, work / file)
        manifest = (ROOT / 'programs/boulder_rollers/Cargo.toml').read_text().replace('default = ["no-idl"]', 'default = ["no-idl", "stage1-devnet"]')
        (parser / 'Cargo.toml').write_text(manifest)
        source = parser / 'src/lib.rs'
        source.write_text(source.read_text().replace('pub mod boulder_rollers {',
            'pub mod boulder_rollers {\n' + (parser / 'src/stage1_devnet_idl.rs').read_text(), 1))
        (work / 'tests').symlink_to(ROOT / 'tests', target_is_directory=True)
        subprocess.run(['anchor', 'idl', 'build', '--out', str(OUT / 'idl/boulder_rollers.json')], cwd=parser,
                       env=dict(os.environ, CARGO_TARGET_DIR=str(ROOT / 'target')), check=True)
    assert all(hashlib.sha256(p.read_bytes()).digest() == digest for p, digest in before.items()), 'Canonical artifact changed'
    generated = (OUT / 'idl/boulder_rollers.json').read_bytes()
    committed = ROOT / 'idl/boulder_rollers.devnet.json'
    if '--write-idl' in sys.argv:
        committed.write_bytes(generated)
    else:
        assert generated == committed.read_bytes(), 'Devnet IDL stale; regenerate with --write-idl'
    print('Devnet ELF and isolated IDL built; canonical artifacts unchanged', flush=True)


if __name__ == '__main__':
    main()
