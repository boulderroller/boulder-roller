"""A sequential validator must wait for its predecessor's TCP ports."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

SPEC = importlib.util.spec_from_file_location(
    'stage1_test_process', Path(__file__).resolve().parents[1] / 'scripts/stage1_test_process.py')
PROCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROCESS)


class ValidatorPortReadiness(unittest.TestCase):
    def test_suite_waits_until_the_previous_listener_releases_its_port(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            release = threading.Timer(0.2, listener.close)
            release.start()
            try:
                PROCESS.run_suite(
                    [sys.executable, '-c',
                     f'import socket; s=socket.socket(); s.bind(("0.0.0.0", {port})); s.close()'],
                    cwd=directory, env=os.environ, ports=(port,))
            finally:
                release.join()

    def test_still_occupied_port_fails_with_the_exact_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(TimeoutError, str(port)):
                PROCESS.wait_for_ports((port,), timeout=0.05, interval=0.01)


if __name__ == '__main__':
    unittest.main()
