#!/usr/bin/env python3
"""
Health Check - One-shot health check without the full TUI

Usage:
    python -m tools.dashboard.health_check [--remote]
    python tools/dashboard/health_check.py

Checks:
    - API Health
    - Docker Containers
    - Celery Workers & Queues
    - NATS JetStream
    - Solana RPC & Programs

Perfect for CI/CD checks or quick terminal glances.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

try:
    from .config import DashboardConfig
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from tools.dashboard.config import DashboardConfig

# ============================================================================
# CONFIG
# ============================================================================
# ============================================================================

# ============================================================================
# ANSI COLORS
# ============================================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"


BEETLE = f"""{C.YELLOW}
    ,_    _,
    |\\\\__//|
    |  oo  |  Boulder Rollers
    \\  <>  /  Health Check
     `|--|`
     /|  |\\
    (_|  |_){C.RESET}
"""


def ok(text: str) -> str:
    return f"{C.GREEN}*{C.RESET} {text}"


def warn(text: str) -> str:
    return f"{C.YELLOW}!{C.RESET} {text}"


def err(text: str) -> str:
    return f"{C.RED}x{C.RESET} {text}"


def header(text: str) -> str:
    return f"\n{C.BOLD}{C.CYAN}{text}{C.RESET}"


def dim(text: str) -> str:
    return f"{C.DIM}{text}{C.RESET}"


def solana_label(rpc_url: str, config: DashboardConfig) -> str:
    if rpc_url == config.solana_rpc_mainnet:
        return "SOLANA (mainnet)"
    if rpc_url == config.solana_rpc_devnet:
        return "SOLANA (devnet)"
    return "SOLANA (custom)"


# ============================================================================
# CHECKS
# ============================================================================

async def check_api(base_url: str) -> list[tuple[str, bool, float]]:
    """Check API endpoints."""
    endpoints = [
        ("/health/db", "Database"),
        ("/metrics", "Metrics"),
        ("/leaderboard", "Leaderboard"),
        ("/segments/piles", "Segments"),
    ]

    results = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for path, name in endpoints:
            start = datetime.now()
            try:
                resp = await client.get(f"{base_url}{path}")
                latency = (datetime.now() - start).total_seconds() * 1000
                success = resp.status_code < 400
            except Exception:
                latency = 0
                success = False
            results.append((name, success, latency))

    return results


def check_docker(is_remote: bool, remote_host: str) -> list[tuple[str, str]]:
    """Check Docker containers."""
    if is_remote:
        cmd = ["ssh", remote_host, "docker", "ps", "-a", "--format", "{{.Names}}:{{.Status}}"]
    else:
        cmd = ["docker", "ps", "-a", "--format", "{{.Names}}:{{.Status}}"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if ':' in line:
                name, status = line.split(':', 1)
                containers.append((name, status))
        return containers
    except Exception as e:
        return [("error", str(e))]


def check_celery(is_remote: bool, config: DashboardConfig) -> tuple[int, int, str]:
    """Check Celery workers and queue. Returns (workers, queue_len, status)."""
    # Check queue length via Redis
    if is_remote:
        cmd = [
            "ssh",
            config.remote_host,
            "redis-cli",
            "-h",
            config.remote_redis_host,
            "-p",
            str(config.remote_redis_port),
            "LLEN",
            "celery",
        ]
    else:
        cmd = [
            "redis-cli",
            "-h",
            config.local_redis_host,
            "-p",
            str(config.local_redis_port),
            "LLEN",
            "celery",
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        queue_len = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    except Exception:
        queue_len = -1

    # Check workers (simplified - just check if celery process exists)
    if is_remote:
        cmd = [
            "ssh",
            config.remote_host,
            "docker",
            "ps",
            "--format",
            "{{.Names}}",
            "--filter",
            "name=celery",
        ]
    else:
        cmd = ["pgrep", "-f", "celery"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        workers = 1 if result.stdout.strip() else 0
    except Exception:
        workers = 0

    status = "online" if workers > 0 else "offline"
    return (workers, queue_len, status)


async def check_nats(base_url: str) -> tuple[bool, int, int]:
    """Check NATS JetStream. Returns (connected, streams, messages)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/jsz?streams=true")
            if resp.status_code != 200:
                return (False, 0, 0)

            data = resp.json()
            streams = 0
            messages = 0

            for account in data.get("account_details", []):
                for stream in account.get("stream_detail", []):
                    streams += 1
                    messages += stream.get("state", {}).get("messages", 0)

            # If no streams but server responds, still connected
            if streams == 0:
                resp = await client.get(f"{base_url}/varz")
                if resp.status_code == 200:
                    return (True, 0, 0)

            return (True, streams, messages)

    except Exception:
        return (False, 0, 0)


async def check_solana(rpc_url: str, programs: list[tuple[str, str]]) -> dict:
    """Check Solana RPC and programs."""
    result = {
        "connected": False,
        "slot": 0,
        "epoch": 0,
        "tps": 0,
        "programs": {},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get slot
            resp = await client.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1, "method": "getSlot"
            })
            result["slot"] = resp.json().get("result", 0)
            result["connected"] = True

            # Get epoch
            resp = await client.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1, "method": "getEpochInfo"
            })
            result["epoch"] = resp.json().get("result", {}).get("epoch", 0)

            # Get TPS
            resp = await client.post(rpc_url, json={
                "jsonrpc": "2.0", "id": 1, "method": "getRecentPerformanceSamples",
                "params": [1]
            })
            samples = resp.json().get("result", [])
            if samples:
                sample = samples[0]
                txs = sample.get("numTransactions", 0)
                slots = sample.get("numSlots", 1)
                result["tps"] = txs / (slots * 0.4) if slots > 0 else 0

            # Check programs
            for name, program_id in programs:
                try:
                    resp = await client.post(rpc_url, json={
                        "jsonrpc": "2.0", "id": 1,
                        "method": "getAccountInfo",
                        "params": [program_id, {"encoding": "base64"}]
                    })
                    value = resp.json().get("result", {}).get("value")
                    if value and value.get("executable"):
                        result["programs"][name] = "deployed"
                    elif value:
                        result["programs"][name] = "exists"
                    else:
                        result["programs"][name] = "not_found"
                except:
                    result["programs"][name] = "error"

    except Exception as e:
        result["error"] = str(e)

    return result


def check_logs(is_remote: bool, config: DashboardConfig) -> tuple[int, int, int]:
    """Quick log analysis - returns (info, warn, error) counts."""
    if is_remote:
        cmd = ["ssh", config.remote_host, "docker", "logs", "--tail", "100", "boulder-api"]
    else:
        cmd = ["tail", "-100", str(config.local_log_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        text = result.stdout + result.stderr

        info = text.lower().count("info")
        warns = text.lower().count("warning") + text.lower().count("warn")
        errors = text.lower().count("error") + text.lower().count("exception")

        return (info, warns, errors)
    except Exception:
        return (0, 0, 0)


# ============================================================================
# MAIN
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Backend health check")
    parser.add_argument("--remote", "-r", action="store_true", help="Check remote server")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--remote-host", help="SSH host for remote monitoring")
    parser.add_argument("--local-log-path", help="Path to local log file")
    parser.add_argument("--local-api-base", help="Local API base URL")
    parser.add_argument("--remote-api-base", help="Remote API base URL")
    parser.add_argument("--local-redis-host", help="Local Redis host")
    parser.add_argument("--local-redis-port", type=int, help="Local Redis port")
    parser.add_argument("--remote-redis-host", help="Remote Redis host")
    parser.add_argument("--remote-redis-port", type=int, help="Remote Redis port")
    parser.add_argument("--local-nats-monitor", help="Local NATS monitor URL")
    parser.add_argument("--remote-nats-monitor", help="Remote NATS monitor URL")
    parser.add_argument("--solana-rpc", help="Override Solana RPC URL")
    parser.add_argument("--solana-mainnet", action="store_true", help="Use Solana mainnet RPC")
    args = parser.parse_args()

    config = DashboardConfig.from_env()
    if args.remote_host:
        config.remote_host = args.remote_host
    if args.local_log_path:
        config.local_log_path = Path(args.local_log_path)
    if args.local_api_base:
        config.local_api_base = args.local_api_base
    if args.remote_api_base:
        config.remote_api_base = args.remote_api_base
    if args.local_redis_host:
        config.local_redis_host = args.local_redis_host
    if args.local_redis_port is not None:
        config.local_redis_port = args.local_redis_port
    if args.remote_redis_host:
        config.remote_redis_host = args.remote_redis_host
    if args.remote_redis_port is not None:
        config.remote_redis_port = args.remote_redis_port
    if args.local_nats_monitor:
        config.local_nats_monitor = args.local_nats_monitor
    if args.remote_nats_monitor:
        config.remote_nats_monitor = args.remote_nats_monitor

    if args.solana_rpc:
        solana_rpc_url = args.solana_rpc
    elif args.solana_mainnet:
        solana_rpc_url = config.solana_rpc_mainnet
    else:
        solana_rpc_url = config.solana_rpc_devnet

    if not args.json:
        print(BEETLE)

    base_url = config.remote_api_base if args.remote else config.local_api_base
    nats_url = config.remote_nats_monitor if args.remote else config.local_nats_monitor
    mode = "REMOTE" if args.remote else "LOCAL"

    if not args.json:
        print(f"{C.DIM}Mode: {mode} | {datetime.now().strftime('%H:%M:%S')}{C.RESET}")

    all_results = {"mode": mode, "timestamp": datetime.now().isoformat()}
    all_ok = True

    # -------------------------------------------------------------------------
    # API Health
    # -------------------------------------------------------------------------
    if not args.json:
        print(header("API HEALTH"))

    api_results = await check_api(base_url)
    api_ok = all(r[1] for r in api_results)
    all_results["api"] = {"ok": api_ok, "endpoints": []}

    for name, success, latency in api_results:
        all_results["api"]["endpoints"].append({"name": name, "ok": success, "latency_ms": latency})
        if args.json:
            continue
        if success:
            color = C.GREEN if latency < 100 else C.YELLOW
            print(ok(f"{name:15} {color}{latency:6.0f}ms{C.RESET}"))
        else:
            print(err(f"{name:15} {C.RED}FAILED{C.RESET}"))
            all_ok = False

    # -------------------------------------------------------------------------
    # Docker Containers
    # -------------------------------------------------------------------------
    if not args.json:
        print(header("CONTAINERS"))

    containers = check_docker(args.remote, config.remote_host)
    containers_ok = all("Up" in status for name, status in containers if name != "error")
    all_results["docker"] = {"ok": containers_ok, "containers": []}

    for name, status in containers:
        all_results["docker"]["containers"].append({"name": name, "status": status})
        if args.json:
            continue
        if "Up" in status:
            print(ok(f"{name:15} {dim(status[:25])}"))
        elif name == "error":
            print(err(f"Docker error: {status}"))
            all_ok = False
        else:
            print(err(f"{name:15} {status[:25]}"))

    # -------------------------------------------------------------------------
    # Celery
    # -------------------------------------------------------------------------
    if not args.json:
        print(header("CELERY"))

    workers, queue_len, celery_status = check_celery(args.remote, config)
    celery_ok = celery_status == "online"
    all_results["celery"] = {"ok": celery_ok, "workers": workers, "queue": queue_len, "status": celery_status}

    if not args.json:
        if celery_ok:
            print(ok(f"Workers: {workers}  Queue: {queue_len} tasks"))
        else:
            print(warn(f"Workers: {workers}  {C.YELLOW}(offline or unavailable){C.RESET}"))

    # -------------------------------------------------------------------------
    # NATS JetStream
    # -------------------------------------------------------------------------
    if not args.json:
        print(header("NATS JETSTREAM"))

    nats_connected, nats_streams, nats_msgs = await check_nats(nats_url)
    all_results["nats"] = {"ok": nats_connected, "streams": nats_streams, "messages": nats_msgs}

    if not args.json:
        if nats_connected:
            print(ok(f"Streams: {nats_streams}  Messages: {nats_msgs}"))
        else:
            print(warn(f"NATS {C.YELLOW}disconnected{C.RESET}"))

    # -------------------------------------------------------------------------
    # Solana
    # -------------------------------------------------------------------------
    if not args.json:
        print(header(solana_label(solana_rpc_url, config)))

    sol = await check_solana(solana_rpc_url, config.program_list())
    sol_ok = sol["connected"] and all(s == "deployed" for s in sol["programs"].values())
    all_results["solana"] = sol

    if not args.json:
        if sol["connected"]:
            print(ok(f"Slot: {sol['slot']:,}  Epoch: {sol['epoch']}  TPS: {sol['tps']:.0f}"))
            for name, status in sol["programs"].items():
                if status == "deployed":
                    print(f"    {C.GREEN}*{C.RESET} {name}: deployed")
                elif status == "not_found":
                    print(f"    {C.YELLOW}!{C.RESET} {name}: {C.YELLOW}not deployed{C.RESET}")
                else:
                    print(f"    {C.RED}x{C.RESET} {name}: {C.RED}{status}{C.RESET}")
        else:
            print(err(f"Solana RPC {C.RED}unreachable{C.RESET}"))
            all_ok = False

    # -------------------------------------------------------------------------
    # Recent Logs
    # -------------------------------------------------------------------------
    if not args.json:
        print(header("RECENT LOGS"))

    info, warns, errors = check_logs(args.remote, config)
    all_results["logs"] = {"info": info, "warnings": warns, "errors": errors}

    if not args.json:
        err_style = C.RED if errors > 0 else C.DIM
        print(f"  {C.BLUE}INFO: {info:4}{C.RESET}  {C.YELLOW}WARN: {warns:4}{C.RESET}  {err_style}ERR: {errors:4}{C.RESET}")

    if errors > 0:
        all_ok = False

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    all_results["all_ok"] = all_ok and api_ok and containers_ok

    if args.json:
        print(json.dumps(all_results, indent=2, default=str))
    else:
        print(header("SUMMARY"))
        if all_ok and api_ok and containers_ok and celery_ok and sol_ok:
            print(f"  {C.BG_GREEN}{C.BOLD} ALL SYSTEMS GO {C.RESET}")
        elif errors > 0 or not api_ok:
            print(f"  {C.BG_RED}{C.BOLD} ERRORS DETECTED {C.RESET}")
        else:
            print(f"  {C.BG_YELLOW}{C.BOLD} DEGRADED {C.RESET}")
        print()

    # Exit code
    sys.exit(0 if all_results["all_ok"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
