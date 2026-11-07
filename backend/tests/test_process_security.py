"""Linux procfs regression; runnable with stdlib unittest in a minimal container."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]


class ProcessPrivacyTests(unittest.TestCase):
    def test_protection_runs_before_startup_services(self):
        module = ast.parse((BACKEND / "app/main.py").read_text())
        lifespan = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
        first = lifespan.body[1]  # After its docstring, before any service startup.
        self.assertIsInstance(first, ast.Expr)
        self.assertIsInstance(first.value, ast.Call)
        self.assertEqual(getattr(first.value.func, "id", None), "protect_process_environment")

    @unittest.skipUnless(sys.platform == "linux", "requires Linux procfs")
    def test_decoder_like_child_cannot_read_api_environment(self):
        # Isolated parent with only a dummy secret. The control read proves that
        # the deny comes from our startup protection, not unrelated procfs policy.
        parent = r'''
import os, subprocess, sys
from app.process_security import protect_process_environment
child = "import pathlib,sys; sys.stdout.buffer.write(pathlib.Path('/proc/' + sys.argv[1] + '/environ').read_bytes())"
def probe():
    return subprocess.run([sys.executable, '-I', '-c', child, str(os.getpid())],
                          env={}, close_fds=True, capture_output=True, timeout=5)
before = probe()
assert before.returncode == 0 and b'DUMMY_API_SECRET=private-fixture' in before.stdout
protect_process_environment()
after = probe()
assert after.returncode != 0 and b'PermissionError' in after.stderr
assert b'private-fixture' not in after.stdout
'''
        result = subprocess.run([sys.executable, "-c", parent], cwd=BACKEND,
                                env={"DUMMY_API_SECRET": "private-fixture"},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
