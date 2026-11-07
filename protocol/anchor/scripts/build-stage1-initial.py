#!/usr/bin/env python3
"""Build a pinned historical ELF in an isolated Cargo target for cutover tests."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = '7960ec61b8f1c93ede2c5177a0661a5f2030dd9a'  # Last 1c commit, before governance and the city tail.
PREVIOUS_REVISION = '5931e4540474f658cc9e1be6951674281e548530'  # Release base: the 0x4D program on main.
LEGACY_REVISION = '70ec4bc3117a7e244ad9e173b5062abcdf39488d'  # Last main commit at 0x4C, before Stage 1 merged.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    which = parser.add_mutually_exclusive_group()
    which.add_argument('--previous-version', action='store_true', help='Build the 0x4D release base for the version advance')
    which.add_argument('--legacy-version', action='store_true', help='Build the 0x4C program for the service cutover history')
    args = parser.parse_args()
    revision, label, out = ((PREVIOUS_REVISION, '0x4D', 'stage1-previous') if args.previous_version else
                            (LEGACY_REVISION, '0x4C', 'stage1-legacy') if args.legacy_version else (REVISION, '1c', 'stage1-initial'))
    out = ROOT / '.anchor' / out / 'deploy'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage1-initial-source-', dir=ROOT / '.anchor') as directory:
        work = Path(directory)
        archive = work / 'source.tar'
        with archive.open('wb') as output:
            subprocess.run(['git', 'archive', revision, 'protocol/anchor'], cwd=ROOT.parents[1], stdout=output, check=True)
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                destination = work / member.name
                assert destination.resolve().is_relative_to(work.resolve()) and (member.isfile() or member.isdir())
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.extractfile(member).read())
        old = work / 'protocol/anchor'
        subprocess.run(['cargo', 'build-sbf', '--manifest-path', str(old / 'programs/boulder_rollers/Cargo.toml'),
                        '--sbf-out-dir', str(out)], cwd=old, env=dict(os.environ, CARGO_TARGET_DIR=str(work / 'cargo-target')), check=True)
    binary = out / 'boulder_rollers.so'
    print(f'Actual {label} {revision}: {hashlib.sha256(binary.read_bytes()).hexdigest()} {binary}', flush=True)


if __name__ == '__main__':
    main()
