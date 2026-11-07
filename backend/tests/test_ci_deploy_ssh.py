"""Backend CI's deploy step holds the droplet's root key and only runs on main,
so no pull request exercises it. These tests run the step's own script against
a stand-in ssh: the key lands in a 0600 file, only the pinned droplet host keys
are trusted, a non-zero remote exit fails the step, and the droplet receives
the exact command string appleboy/ssh-action used to send."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "backend-ci.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"
PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-key\n-----END OPENSSH PRIVATE KEY-----\n"
# Secrets as they might have been pasted: stray lines, carriage returns, whitespace.
KEY = "\n" + PEM.replace("\n", "\r\n") + " \n"
DROPLET_IP = " 203.0.113.7\n"
# The action sent `export DEPLOY_SHA='<sha>'`, a newline, then the trimmed script.
REMOTE_COMMAND = "\n".join(
    [
        f"export DEPLOY_SHA='{SHA}'",
        "set -eu",
        "cd /root/boulder-repo",
        "git fetch origin main",
        "git checkout main",
        'git reset --hard "$DEPLOY_SHA"',
        'export APP_VERSION="$DEPLOY_SHA"',
        "export ENVIRONMENT=production",
        "export APP_ENV=production",
        "# Current services: caddy, api, nats, indexer",
        "# Celery/Redis removed — March 2026",
        'scripts/deploy-backend-release.sh "$DEPLOY_SHA"',
    ]
)
# Records what the step hands ssh while the key directory still exists.
STAND_IN_SSH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
key = args[args.index("-i") + 1]
known_hosts = next(a.split("=", 1)[1] for a in args if a.startswith("UserKnownHostsFile="))
with open(os.environ["SSH_RECORD"], "w") as record:
    json.dump({"args": args, "key_mode": os.stat(key).st_mode & 0o777,
               "key": open(key).read(), "known_hosts": open(known_hosts).read()}, record)
sys.exit(int(os.environ["SSH_EXIT"]))
"""


def deploy_step() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow[workflow.index("      - name: Deploy to droplet") :]


def block(text: str, key: str) -> str:
    """The literal block scalar under `key: |`, dedented and clipped as YAML reads it."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"{key}: |") + 1
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body).rstrip("\n") + "\n"


@pytest.fixture
def known_hosts(tmp_path: Path) -> str:
    key = tmp_path / "host_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    return "droplet " + " ".join(key.with_suffix(".pub").read_text().split()[:2])


def run_step(workdir: Path, known_hosts: str, ssh_exit: int = 0, sha: str = SHA, key: str = KEY):
    step = deploy_step()
    (workdir / "bin").mkdir(parents=True)
    (workdir / "runner-temp").mkdir()
    (workdir / "bin" / "ssh").write_text(STAND_IN_SSH)
    (workdir / "bin" / "ssh").chmod(0o755)
    (workdir / "step.sh").write_text(block(step, "run"))
    record = workdir / "ssh.json"
    env = {
        "HOME": os.environ.get("HOME", str(workdir)),
        "PATH": f"{workdir / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(workdir / "runner-temp"),
        "DEPLOY_SHA": sha,
        "DROPLET_IP": DROPLET_IP,
        "DROPLET_SSH_KEY": key,
        "DROPLET_KNOWN_HOSTS": known_hosts,
        "REMOTE_SCRIPT": block(step, "REMOTE_SCRIPT"),
        "SSH_RECORD": str(record),
        "SSH_EXIT": str(ssh_exit),
    }
    # GitHub runs a `shell: bash` step as `bash --noprofile --norc -eo pipefail {0}`.
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(workdir / "step.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    return result, json.loads(record.read_text()) if record.exists() else None


def test_deploy_runs_the_release_over_openssh_trusting_only_pinned_host_keys(
    tmp_path: Path, known_hosts: str
) -> None:
    step = deploy_step()
    assert "uses:" not in step
    assert "timeout-minutes: 30" in step
    assert "DROPLET_SSH_KEY: ${{ secrets.DROPLET_SSH_KEY }}" in step
    assert "DROPLET_KNOWN_HOSTS: ${{ vars.DROPLET_KNOWN_HOSTS }}" in step
    assert "${{" not in block(step, "run")

    result, ssh = run_step(tmp_path / "deploy", known_hosts)

    assert result.returncode == 0, result.stderr
    ssh_dir = tmp_path / "deploy" / "runner-temp" / "droplet-ssh"
    # -F /dev/null keeps the runner's ssh_config (SendEnv LANG LC_*, any
    # KnownHostsCommand) out; GlobalKnownHostsFile=/dev/null leaves the pin alone.
    assert ssh["args"] == [
        "-F", "/dev/null", "-n", "-T", "-i", f"{ssh_dir}/key",
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30",
        "-o", "StrictHostKeyChecking=yes", "-o", f"HostKeyAlias={known_hosts.split()[0]}",
        "-o", f"UserKnownHostsFile={ssh_dir}/known_hosts",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=10",
        "--", "root@203.0.113.7", REMOTE_COMMAND,
    ]
    assert ssh["known_hosts"] == known_hosts + "\n"
    assert ssh["key_mode"] == 0o600
    assert ssh["key"] == PEM
    assert "Pinned droplet host keys:" in result.stdout
    assert not ssh_dir.exists()


def test_deploy_fails_on_remote_failure_missing_pin_or_key_or_unsafe_sha(
    tmp_path: Path, known_hosts: str
) -> None:
    result, ssh = run_step(tmp_path / "remote-failure", known_hosts, ssh_exit=3)
    assert result.returncode == 3 and ssh is not None

    result, ssh = run_step(tmp_path / "no-pin", "")
    assert result.returncode != 0 and ssh is None
    assert "DROPLET_KNOWN_HOSTS" in result.stdout + result.stderr

    result, ssh = run_step(tmp_path / "no-key", known_hosts, key="")
    assert result.returncode != 0 and ssh is None
    assert "DROPLET_SSH_KEY" in result.stdout + result.stderr

    result, ssh = run_step(tmp_path / "unsafe-sha", known_hosts, sha=f"{SHA}'; reboot; '")
    assert result.returncode != 0 and ssh is None
