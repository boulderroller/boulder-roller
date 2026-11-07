"""Own one local test process group and its replay directory; never sweep /tmp."""
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import tempfile
import time


def _live_group(group):
    rows = subprocess.check_output(['ps', '-axo', 'pgid=,stat='], text=True)
    return any(int(parts[0]) == group and not parts[1].startswith('Z')
               for row in rows.splitlines() if len(parts := row.split()) == 2)


def wait_for_ports(ports, *, timeout=75, interval=0.1):
    """Wait for configured TCP ports to become reusable before startup."""
    ports = tuple(ports)
    if len(set(ports)) != len(ports) or any(not 0 < port < 65536 for port in ports):
        raise ValueError(f'Invalid or overlapping validator TCP ports: {ports}')
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        blocked = []
        with ExitStack() as sockets:
            for port in ports:
                listener = sockets.enter_context(socket.socket())
                try:
                    listener.bind(('0.0.0.0', port))
                except OSError as error:
                    if error.errno != errno.EADDRINUSE:
                        raise
                    blocked.append(port)
            if not blocked:
                return
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Validator TCP ports still unavailable after {timeout}s: {blocked}')
        if not announced:
            print(f'Waiting for validator TCP ports to be released: {blocked}', flush=True)
            announced = True
        time.sleep(interval)


def run_suite(command, *, cwd, env, ports):
    """Fail a successful suite if it leaked, and clean on failure/SIGINT/SIGTERM.

    SIGKILL of this outer supervisor cannot run cleanup. All normal exits and
    handled interruptions stop this suite's descendants before deleting files.
    """
    # A dead process group does not imply its TCP ports are immediately reusable.
    # Do not allocate a replay directory or start the next validator until ready.
    wait_for_ports(ports)

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    process = None
    # macOS's default per-user temp path plus two directory levels exceeds
    # the validator admin RPC Unix-socket path limit. Keep this owned root short.
    directory = tempfile.mkdtemp(prefix='stage1-suite-', dir='/tmp')
    safe_to_remove = True
    try:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=dict(env, STAGE1_REPLAY_ROOT=directory), start_new_session=True)
            safe_to_remove = False
            result = process.wait()
        finally:
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            if process is not None:
                for sig, seconds in ((signal.SIGTERM, 8), (signal.SIGKILL, 5)):
                    if not _live_group(process.pid):
                        break
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        # A signal failure never permits deleting live files.
                        # Allow a bounded wait for an already-exiting group.
                        for _ in range(10):
                            if not _live_group(process.pid):
                                break
                            time.sleep(0.1)
                        else:
                            raise
                        break
                    deadline = time.monotonic() + seconds
                    while _live_group(process.pid) and time.monotonic() < deadline:
                        time.sleep(0.1)
                process.wait(timeout=5)
                if _live_group(process.pid):
                    raise RuntimeError(f'Test process group did not stop; retained {directory}')
                safe_to_remove = True
        leftovers = list(Path(directory).iterdir())
        if result:
            raise subprocess.CalledProcessError(result, command)
        if leftovers:
            raise RuntimeError(f'Suite leaked {len(leftovers)} replay entries (removed by supervisor)')
        print('Replay cleanup check: zero owned ledgers remain', flush=True)
    finally:
        if safe_to_remove:
            shutil.rmtree(directory)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
