"""Replace manifested exports with anonymous witnesses on the shared keeper volume."""
import hashlib
import fcntl
import os
from pathlib import Path
import re
import tempfile
from contextlib import contextmanager

from .stage1_keeper_merkle import canonical


@contextmanager
def export_lock(directory, job_id):
    """Persistent inode shared by publishers and every deletion worker."""
    if not re.fullmatch('[0-9a-f]{64}', job_id):
        raise ValueError('invalid keeper export job')
    fd = os.open(Path(directory) / f'.{job_id}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def redact_export(manifest, root, *, validate=None, record=None):
    directory = Path(root)
    path = Path(manifest["path"])
    # An unavailable/unmounted volume is not evidence that its files vanished.
    if not directory.is_dir() or directory.is_symlink() or directory.resolve() != directory:
        raise ValueError("keeper export volume unavailable")
    if path.parent != directory or path.name != f"{manifest['job_id']}.json" or path.is_symlink():
        raise ValueError("invalid keeper export manifest path")
    with export_lock(directory, manifest['job_id']):
        # The production caller rechecks the current lease and exact manifest
        # only after acquiring the lock. Hold it through the receipt write so
        # a delayed old worker cannot restore a later person's erased identity.
        if validate is not None:
            validate()
        redacted_digest = _redact_locked(manifest, directory, path)
        if record is not None:
            record(redacted_digest)
        return redacted_digest


def _redact_locked(manifest, directory, path):
    data = canonical(manifest['payload']) + b'\n'
    redacted_digest = hashlib.sha256(data).hexdigest()
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() not in (manifest["digest"],redacted_digest):
        raise ValueError("keeper export digest changed")
    # Each temporary is scoped to this exact manifested job, including a crash
    # before the final hard link. Suspended jobs cannot create more temporaries.
    temporary = [p for p in directory.iterdir() if p.name.startswith(f".{manifest['job_id']}-")]
    for candidate in temporary:
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            raise ValueError("invalid keeper export file")
        candidate.unlink(missing_ok=True)
    # The surviving riders retain their complete proofs even when the API is
    # down. Erased paid leaves keep only their sum/tree witnesses. Retry accepts
    # either the exact old bytes or the exact redacted bytes after a crash.
    fd,name = tempfile.mkstemp(prefix=f".{manifest['job_id']}-",dir=directory)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return redacted_digest
