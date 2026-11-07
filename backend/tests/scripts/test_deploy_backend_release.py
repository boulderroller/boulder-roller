from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy-backend-release.sh"
COMPOSE_FILE = ROOT / "docker-compose.yml"
DEPLOY_SHA = "0123456789abcdef0123456789abcdef01234567"
RLS_APPROVAL_ENVIRONMENT = (
    "APPROVED_PUBLIC_DATA_API_RLS_SHA256",
    "APPROVED_PUBLIC_DATA_API_RLS_PROJECT_REF",
    "APPROVED_PUBLIC_DATA_API_RLS_CATALOG_SHA256",
)


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_release(
    tmp_path: Path,
    *,
    observatory_payload: dict[str, object],
    indexer_health_payload: dict[str, object] | None = None,
    chain_version: int = 76,
    chain_healthy: bool = True,
    backend_image_tags: tuple[str, ...] = (),
    images_in_use: tuple[str, ...] = (),
    running_containers: tuple[str, ...] = (),
    compose_ps: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"

    _write_executable(
        bin_dir / "docker",
        """#!/bin/sh
printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
case "$1" in
    compose) [ "$2" != ps ] || [ -z "$COMPOSE_PS" ] || printf '%s\n' $COMPOSE_PS ;;
    images) [ -z "$BACKEND_IMAGE_TAGS" ] || printf '%s\n' $BACKEND_IMAGE_TAGS ;;
    ps) [ -z "$RUNNING_CONTAINERS" ] || printf '%s\n' $RUNNING_CONTAINERS ;;
    rmi) case " $IMAGES_IN_USE " in *" $2 "*) exit 1 ;; esac ;;
esac
exit 0
""",
    )

    status_payload = json.dumps(
        {
            "version": DEPLOY_SHA,
            "environment_public": True,
            "invite_required": True,
            "auth_signature_bypass_effective": False,
            "dev_routes_enabled": False,
        }
    )
    encoded_observatory = json.dumps(observatory_payload)
    encoded_indexer_health = json.dumps(
        indexer_health_payload
        or {
            "status": "ok",
            "snapshot": {
                "status": "succeeded",
                "decode_failures": 0,
                "write_failures": 0,
                "fetch_failures": 0,
            },
        }
    )
    _write_executable(
        bin_dir / "curl",
        f"""#!/bin/sh
url=""
output=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o|--output) output="$2"; shift ;;
        -*) ;;
        *) url="$1" ;;
    esac
    shift
done
printf 'curl %s\n' "$url" >> "$COMMAND_LOG"
# Match curl's output-file mode used for the large observatory payload.
if [ -n "$output" ]; then
    exec > "$output"
fi
case "$url" in
    */health/db) printf '%s\n' '{{"status":"ok"}}' ;;
    */health/chain) {'true' if chain_healthy else 'exit 22'}; printf '%s\n' '{{"status":"ok","program_version":{chain_version}}}' ;;
    */status) printf '%s\n' '{status_payload}' ;;
    */health) printf '%s\n' '{encoded_indexer_health}' ;;
    */v1/observatory) printf '%s\n' '{encoded_observatory}' ;;
    */-/reload) ;;
    *) printf 'unexpected URL: %s\n' "$url" >&2; exit 22 ;;
esac
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "COMMAND_LOG": str(command_log),
            "BACKEND_IMAGE_TAGS": " ".join(backend_image_tags),
            "IMAGES_IN_USE": " ".join(images_in_use),
            "RUNNING_CONTAINERS": " ".join(running_containers),
            "COMPOSE_PS": " ".join(compose_ps),
            "PROMETHEUS_RELOAD_URL": "http://prometheus.test/-/reload",
            "API_HEALTH_ATTEMPTS": "1",
            "API_HEALTH_SLEEP_SECONDS": "0",
            "INDEXER_HEALTH_ATTEMPTS": "1",
            "INDEXER_HEALTH_SLEEP_SECONDS": "0",
            "API_HEALTH_URL": "http://api.test/health/db",
            "API_CHAIN_HEALTH_URL": "http://api.test/health/chain",
            "API_STATUS_URL": "http://api.test/status",
            "INDEXER_HEALTH_URL": "http://indexer.test/health",
            "INDEXER_OBSERVATORY_URL": "http://indexer.test/v1/observatory",
        }
    )
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), DEPLOY_SHA],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    commands = command_log.read_text(encoding="utf-8").splitlines()
    return result, commands


def test_release_rebuilds_and_restarts_indexer_after_migrations(
    tmp_path: Path,
) -> None:
    result, commands = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "spl_mint_supply",
                "spl_mint_supply_slot": 123456,
            }
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    build = commands.index("docker compose build api indexer")
    migrate = next(
        index
        for index, command in enumerate(commands)
        if "apply_sql_migrations.py" in command
    )
    restart = commands.index("docker compose up -d api indexer")
    assert build < migrate < restart
    assert "docker compose stop api indexer" in commands
    assert "docker compose rm -f api indexer" in commands
    assert "curl http://indexer.test/health" in commands
    assert "curl http://indexer.test/v1/observatory" in commands


def test_release_pauses_keeper_for_migrations_and_starts_it_after_health(
    tmp_path: Path,
) -> None:
    result, commands = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "spl_mint_supply",
                "spl_mint_supply_slot": 123456,
            }
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    pause = commands.index("docker compose stop keeper")
    migrate = next(
        index
        for index, command in enumerate(commands)
        if "apply_sql_migrations.py" in command
    )
    observatory = commands.index("curl http://indexer.test/v1/observatory")
    start = commands.index("docker compose up -d --no-deps keeper")
    assert pause < migrate < observatory < start
    assert commands.index("docker compose rm -f keeper") < start
    assert "Backend and indexer release verified" in result.stdout


@pytest.mark.parametrize("chain_version", [76, 77])
def test_release_requires_backend_chain_health_after_database_health(
    tmp_path: Path, chain_version: int,
) -> None:
    result, commands = _run_release(
        tmp_path, chain_version=chain_version,
        observatory_payload={"supply": {
            "circulating": "91000000000", "circulating_source": "spl_mint_supply",
            "spl_mint_supply_slot": 123456,
        }},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands.index("curl http://api.test/health/db") < commands.index("curl http://api.test/health/chain")
    assert commands.index("curl http://api.test/health/chain") < commands.index("docker image prune -f")


def test_release_refuses_failed_backend_chain_health_before_success_or_cleanup(tmp_path: Path) -> None:
    result, commands = _run_release(tmp_path, chain_healthy=False, observatory_payload={"supply": {
        "circulating": "91000000000", "circulating_source": "spl_mint_supply",
        "spl_mint_supply_slot": 123456,
    }})
    assert result.returncode != 0
    assert "Backend chain health check failed" in result.stdout
    assert "docker image prune -f" not in commands


def test_release_that_fails_after_the_switch_restores_the_previous_release(tmp_path: Path) -> None:
    previous = "fedcba9876543210fedcba9876543210fedcba98"
    result, commands = _run_release(
        tmp_path,
        chain_healthy=False,
        compose_ps=(f"boulder-repo-backend:{previous}",),
        observatory_payload={"supply": {
            "circulating": "91000000000", "circulating_source": "spl_mint_supply",
            "spl_mint_supply_slot": 123456,
        }},
    )
    assert result.returncode != 0
    switch = commands.index("docker compose up -d api indexer")
    restore = commands.index("docker compose up -d --no-build --no-deps api indexer")
    assert switch < restore
    assert f"restoring {previous}" in result.stdout
    assert "docker compose up -d --no-build --no-deps keeper" in commands[restore:]
    assert "curl http://127.0.0.1:9093/api/v2/alerts" in commands[restore:]
    assert "docker image prune -f" not in commands


def test_release_keeps_this_image_and_two_rollbacks_and_prunes_the_rest(
    tmp_path: Path,
) -> None:
    rollback_one, rollback_two, old = ("b" * 40, "c" * 40, "d" * 40)
    result, commands = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "spl_mint_supply",
                "spl_mint_supply_slot": 123456,
            }
        },
        # Newest first, as docker images lists them.
        backend_image_tags=(DEPLOY_SHA, rollback_one, rollback_two, "<none>", old, "dev"),
        images_in_use=(f"boulder-repo-backend:{old}",),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    removed = [command for command in commands if command.startswith("docker rmi ")]
    assert removed == [
        f"docker rmi boulder-repo-backend:{old}",
        "docker rmi boulder-repo-backend:dev",
    ]
    assert f"Kept boulder-repo-backend:{old}" in result.stdout
    verified = commands.index("curl http://indexer.test/v1/observatory")
    assert commands.index("docker image prune -f") > verified
    assert "docker builder prune -f --filter until=168h" in commands


@pytest.mark.parametrize("monitoring", [False, True])
def test_release_reloads_alert_rules_only_where_prometheus_runs(
    tmp_path: Path, monitoring: bool
) -> None:
    result, commands = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "spl_mint_supply",
                "spl_mint_supply_slot": 123456,
            }
        },
        running_containers=("boulder-repo-api-1", "prometheus") if monitoring else ("boulder-repo-api-1",),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert ("curl http://prometheus.test/-/reload" in commands) is monitoring
    assert ("Prometheus rules reloaded" in result.stdout) is monitoring


def _published_ports(compose: str) -> list[str]:
    ports: list[str] = []
    in_ports = False
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped == "ports:":
            in_ports = True
        elif in_ports and stripped.startswith("- "):
            ports.append(stripped[2:].strip().strip('"'))
        elif in_ports and stripped and not stripped.startswith("#"):
            in_ports = False
    return ports


def test_only_caddy_publishes_ports_beyond_loopback() -> None:
    app = _published_ports(COMPOSE_FILE.read_text(encoding="utf-8"))
    monitoring = _published_ports(
        (ROOT / "infrastructure" / "monitoring" / "docker-compose.monitoring.yml")
        .read_text(encoding="utf-8")
    )

    caddy = {"80:80", "443:443", "443:443/udp"}
    assert caddy <= set(app)
    assert len(monitoring) == 6
    for port in app + monitoring:
        assert port in caddy or port.startswith("127.0.0.1:"), port


def test_release_rejects_noncanonical_circulating_supply_source(
    tmp_path: Path,
) -> None:
    result, _ = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "legacy_derived",
                "spl_mint_supply_slot": 123456,
            }
        },
    )

    assert result.returncode == 1
    assert "circulating source" in result.stdout


def test_release_rejects_snapshot_writer_failures_even_when_health_returns_200(
    tmp_path: Path,
) -> None:
    result, _ = _run_release(
        tmp_path,
        observatory_payload={
            "supply": {
                "circulating": "91000000000",
                "circulating_source": "spl_mint_supply",
                "spl_mint_supply_slot": 123456,
            }
        },
        indexer_health_payload={
            "status": "ok",
            "snapshot": {
                "status": "failed",
                "decode_failures": 0,
                "write_failures": 1,
                "fetch_failures": 0,
            },
        },
    )

    assert result.returncode == 1
    assert "snapshot" in result.stdout.lower()
    assert "write failures" in result.stdout.lower()


def test_indexer_receives_the_configured_dung_mint() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    indexer = compose.split("\n  indexer:\n", maxsplit=1)[1].split(
        "\nvolumes:\n", maxsplit=1
    )[0]

    assert "DUNG_MINT_ADDRESS: ${DUNG_MINT_ADDRESS:-" in indexer


def test_api_container_receives_rls_migration_approval_environment() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    api = compose.split("\n  api:\n", maxsplit=1)[1].split(
        "\n  nats:\n", maxsplit=1
    )[0]

    for variable in RLS_APPROVAL_ENVIRONMENT:
        assert f"{variable}: ${{{variable}:-}}" in api


def test_compose_resolves_rls_approval_values_for_one_off_migration_container() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker compose is unavailable")

    sentinels = {
        variable: f"sentinel-{index}"
        for index, variable in enumerate(RLS_APPROVAL_ENVIRONMENT, start=1)
    }
    env = os.environ.copy()
    env.update(sentinels)
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "compose" in result.stderr.lower():
        pytest.skip("docker compose plugin is unavailable")
    assert result.returncode == 0, result.stderr

    api_environment = json.loads(result.stdout)["services"]["api"]["environment"]
    for variable, sentinel in sentinels.items():
        assert api_environment[variable] == sentinel


def test_both_release_entrypoints_use_compose_backed_migration_container() -> None:
    deploy = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    staging = (ROOT / "scripts" / "hooks" / "staging-ops.sh").read_text(
        encoding="utf-8"
    )
    migration_command = "docker compose run --rm --no-deps api"
    assert migration_command in deploy
    assert migration_command in staging
