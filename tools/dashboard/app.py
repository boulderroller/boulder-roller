#!/usr/bin/env python3
"""
BoulderRollers Backend Dashboard

A beautiful CLI dashboard for monitoring your backend services.
Built with Textual for that modern terminal aesthetic.

Usage:
    python -m tools.dashboard.app [--remote]

    --remote    Monitor production server via SSH

Monitors:
    - API Health & Prometheus Metrics
    - Docker Containers
    - Celery Workers & Task Queues
    - NATS JetStream
    - Solana RPC & Programs
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple, Any
import argparse
import httpx

from .config import DashboardConfig
from rich.console import RenderableType
from rich.markup import escape
from rich.style import Style
from rich.text import Text
from rich.table import Table
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    Placeholder,
    ProgressBar,
    RichLog,
    Rule,
    Select,
    Sparkline,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

METRICS_REFRESH_SECONDS = 5.0

# ============================================================================
# ASCII ART & STYLING
# ============================================================================

BEETLE_ASCII = r"""
    ___       ___
   /   \     /   \
  | o o |   | o o |
   \ = /     \ = /
    |_|_______|_|
   /   DUNG    \
  |  DASHBOARD  |
   \_____V_____/
"""

# ============================================================================
# DATA MODELS
# ============================================================================

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_line(cls, line: str) -> "LogLevel":
        upper = line.upper()
        if "ERROR" in upper or "EXCEPTION" in upper or "TRACEBACK" in upper:
            return cls.ERROR
        if "WARNING" in upper or "WARN" in upper:
            return cls.WARNING
        if "DEBUG" in upper:
            return cls.DEBUG
        if "CRITICAL" in upper:
            return cls.CRITICAL
        return cls.INFO


@dataclass
class LogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    raw: str

    @classmethod
    def from_line(cls, line: str) -> "LogEntry":
        level = LogLevel.from_line(line)
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
        if ts_match:
            try:
                ts = datetime.fromisoformat(ts_match.group(1).replace(' ', 'T'))
            except:
                ts = datetime.now()
        else:
            ts = datetime.now()
        return cls(timestamp=ts, level=level, message=line.strip(), raw=line)


@dataclass
class ContainerStatus:
    name: str
    status: str
    health: str
    cpu: str
    memory: str
    ports: str
    uptime: str


@dataclass
class ApiHealth:
    endpoint: str
    status: str
    latency_ms: float
    last_check: datetime


@dataclass
class CeleryWorker:
    name: str
    status: str
    active_tasks: int
    processed: int
    pool: str


@dataclass
class CeleryQueue:
    name: str
    messages: int
    consumers: int


@dataclass
class NatsStreamInfo:
    name: str
    messages: int
    bytes: int
    consumers: int
    subjects: List[str]


@dataclass
class SolanaHealth:
    rpc_url: str
    slot: int
    block_height: int
    epoch: int
    tps: float
    health: str


@dataclass
class SolanaProgramStatus:
    name: str
    program_id: str
    executable: bool
    lamports: int


# ============================================================================
# SERVICES
# ============================================================================

class LogTailer:
    """Tail log files locally or via SSH."""

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.config = config
        self.is_remote = is_remote
        self.entries: Deque[LogEntry] = deque(maxlen=1000)
        self._process: Optional[subprocess.Popen] = None

    async def start(self) -> asyncio.StreamReader:
        if self.is_remote:
            cmd = [
                "ssh",
                self.config.remote_host,
                "docker",
                "logs",
                "-f",
                "--tail",
                "100",
                "boulder-api",
            ]
        else:
            cmd = ["tail", "-f", "-n", "100", str(self.config.local_log_path)]

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return self._process.stdout

    def stop(self):
        if self._process:
            self._process.terminate()


class DockerMonitor:
    """Monitor Docker containers."""

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.config = config
        self.is_remote = is_remote

    async def _run(self, cmd: List[str], timeout: float) -> str:
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(result.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            result.kill()
            await result.communicate()
            raise
        return stdout.decode()

    async def _fetch_stats(self) -> Dict[str, Tuple[str, str]]:
        if self.is_remote:
            cmd = [
                "ssh",
                self.config.remote_host,
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
            ]
        else:
            cmd = [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
            ]

        stats = {}
        output = await self._run(cmd, timeout=4.0)
        for line in output.strip().split("\n"):
            if not line:
                continue
            name, cpu, mem = (part.strip() for part in line.split("|", 2))
            mem_used = mem.split("/", 1)[0].strip()
            stats[name] = (cpu, mem_used)
        return stats

    async def get_containers(self) -> List[ContainerStatus]:
        if self.is_remote:
            cmd = [
                "ssh",
                self.config.remote_host,
                "docker",
                "ps",
                "-a",
                "--format",
                "{{.Names}}|{{.Status}}|{{.Ports}}",
            ]
        else:
            cmd = [
                "docker",
                "ps",
                "-a",
                "--format",
                "{{.Names}}|{{.Status}}|{{.Ports}}",
            ]

        try:
            stdout = await self._run(cmd, timeout=4.0)
        except Exception as e:
            return [
                ContainerStatus(
                    name="Error",
                    status=str(e)[:50],
                    health="error",
                    cpu="--",
                    memory="--",
                    ports="",
                    uptime="",
                )
            ]

        try:
            stats = await self._fetch_stats()
        except Exception:
            stats = {}

        containers = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                name = parts[0]
                status_full = parts[1]
                ports = parts[2] if len(parts) > 2 else ""

                if "Up" in status_full:
                    status = "running"
                    health = "healthy" if "(healthy)" in status_full else "running"
                elif "Exited" in status_full:
                    status = "stopped"
                    health = "stopped"
                else:
                    status = "unknown"
                    health = "unknown"

                uptime_match = re.search(r"Up (.+?)(?:\s*\(|$)", status_full)
                uptime = uptime_match.group(1) if uptime_match else "N/A"

                cpu, mem = stats.get(name, ("--", "--"))

                containers.append(
                    ContainerStatus(
                        name=name,
                        status=status,
                        health=health,
                        cpu=cpu,
                        memory=mem,
                        ports=ports[:30] + "..." if len(ports) > 30 else ports,
                        uptime=uptime,
                    )
                )
        return containers


class HealthChecker:
    """Check API health endpoints."""

    ENDPOINTS = [
        ("/health/db", "Database"),
        ("/metrics", "Metrics"),
        ("/auth/nonce", "Auth"),
        ("/leaderboard", "Leaderboard"),
        ("/segments/piles", "Segments"),
    ]

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.is_remote = is_remote
        self.base_url = config.remote_api_base if is_remote else config.local_api_base

    async def check_all(self) -> List[ApiHealth]:
        results = []
        async with httpx.AsyncClient(timeout=5.0) as client:
            for path, name in self.ENDPOINTS:
                start = datetime.now()
                try:
                    resp = await client.get(f"{self.base_url}{path}")
                    latency = (datetime.now() - start).total_seconds() * 1000
                    status = "OK" if resp.status_code < 400 else f"ERR:{resp.status_code}"
                except httpx.TimeoutException:
                    latency = 5000
                    status = "TIMEOUT"
                except Exception as e:
                    latency = 0
                    status = f"ERR:{type(e).__name__}"

                results.append(ApiHealth(
                    endpoint=name,
                    status=status,
                    latency_ms=latency,
                    last_check=datetime.now(),
                ))
        return results


class MetricsParser:
    """Parse Prometheus metrics."""

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.is_remote = is_remote
        self.base_url = config.remote_api_base if is_remote else config.local_api_base
        self._history: Dict[str, Deque[float]] = {}

    async def fetch(self) -> Dict[str, List[float]]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/metrics")
                if resp.status_code != 200:
                    return {}

                text = resp.text
                snapshot: Dict[str, float] = {}

                for line in text.split("\n"):
                    if line.startswith("#") or not line.strip():
                        continue

                    match = re.match(
                        r"([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
                        line,
                    )
                    if match:
                        name, value = match.groups()
                        try:
                            val = float(value)
                        except ValueError:
                            continue
                        snapshot[name] = snapshot.get(name, 0.0) + val

                for name, val in snapshot.items():
                    if name not in self._history:
                        self._history[name] = deque(maxlen=60)
                    self._history[name].append(val)

                return {name: list(history) for name, history in self._history.items()}
        except Exception:
            return {}


def _latest_metric(metrics: Dict[str, List[float]], name: str) -> Optional[float]:
    values = metrics.get(name)
    if values:
        return values[-1]
    return None


def _rate_metric(
    metrics: Dict[str, List[float]], name: str, interval: float
) -> Optional[float]:
    values = metrics.get(name)
    if values and len(values) >= 2:
        return (values[-1] - values[-2]) / interval
    return None


def _rate_series(
    metrics: Dict[str, List[float]], name: str, interval: float
) -> List[float]:
    values = metrics.get(name)
    if not values or len(values) < 2:
        return []
    return [(values[i] - values[i - 1]) / interval for i in range(1, len(values))]


def _avg_latency_ms(
    metrics: Dict[str, List[float]], interval: float
) -> Optional[float]:
    sums = metrics.get("http_request_duration_seconds_sum")
    counts = metrics.get("http_request_duration_seconds_count")
    if sums and counts and len(sums) >= 2 and len(counts) >= 2:
        delta_sum = sums[-1] - sums[-2]
        delta_count = counts[-1] - counts[-2]
        if delta_count > 0:
            return (delta_sum / delta_count) * 1000
    if sums and counts and counts[-1] > 0:
        return (sums[-1] / counts[-1]) * 1000
    return None


def _format_bytes(value: Optional[float]) -> str:
    if value is None or value < 0:
        return "--"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{size:.0f}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"

class CeleryMonitor:
    """Monitor Celery workers and queues via Redis."""

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.is_remote = is_remote
        self.config = config
        self.redis_host = config.remote_redis_host if is_remote else config.local_redis_host
        self.redis_port = config.remote_redis_port if is_remote else config.local_redis_port

    async def get_workers(self) -> List[CeleryWorker]:
        """Get Celery worker status via celery inspect."""
        try:
            if self.is_remote:
                cmd = [
                    "ssh",
                    self.config.remote_host,
                    "docker",
                    "exec",
                    "boulder-api",
                    "celery",
                    "-A",
                    "app.celery_app",
                    "inspect",
                    "active",
                    "--json",
                ]
            else:
                cmd = ["celery", "-A", "app.celery_app", "inspect", "active", "--json"]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(__file__).parent.parent.parent / "backend"),
            )
            stdout, _ = await asyncio.wait_for(result.communicate(), timeout=5.0)

            try:
                data = json.loads(stdout.decode())
                workers = []
                for worker_name, tasks in data.items():
                    if worker_name == "error":
                        continue
                    workers.append(CeleryWorker(
                        name=worker_name.split('@')[-1] if '@' in worker_name else worker_name,
                        status="online",
                        active_tasks=len(tasks) if isinstance(tasks, list) else 0,
                        processed=0,
                        pool="prefork",
                    ))
                return workers if workers else [CeleryWorker("No workers", "offline", 0, 0, "")]
            except json.JSONDecodeError:
                return [CeleryWorker("celery", "unknown", 0, 0, "")]

        except asyncio.TimeoutError:
            return [CeleryWorker("timeout", "error", 0, 0, "")]
        except Exception as e:
            return [CeleryWorker("error", str(e)[:20], 0, 0, "")]

    async def get_queues(self) -> List[CeleryQueue]:
        """Get queue lengths from Redis."""
        try:
            if self.is_remote:
                cmd = [
                    "ssh",
                    self.config.remote_host,
                    "redis-cli",
                    "-h",
                    self.redis_host,
                    "-p",
                    str(self.redis_port),
                    "LLEN",
                    "celery",
                ]
            else:
                cmd = [
                    "redis-cli",
                    "-h",
                    self.redis_host,
                    "-p",
                    str(self.redis_port),
                    "LLEN",
                    "celery",
                ]

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(result.communicate(), timeout=3.0)

            try:
                queue_len = int(stdout.decode().strip())
            except:
                queue_len = 0

            return [CeleryQueue(name="celery", messages=queue_len, consumers=1)]

        except Exception as e:
            return [CeleryQueue(name="celery", messages=-1, consumers=0)]


class NatsMonitor:
    """Monitor NATS JetStream via HTTP monitoring endpoint."""

    def __init__(self, config: DashboardConfig, is_remote: bool = False):
        self.is_remote = is_remote
        self.base_url = config.remote_nats_monitor if is_remote else config.local_nats_monitor

    async def get_streams(self) -> List[NatsStreamInfo]:
        """Get JetStream stream info."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Get JetStream account info
                resp = await client.get(f"{self.base_url}/jsz?streams=true")
                if resp.status_code != 200:
                    return []

                data = resp.json()
                streams = []

                account_info = data.get("account_details", [])
                if account_info:
                    for account in account_info:
                        for stream in account.get("stream_detail", []):
                            config = stream.get("config", {})
                            state = stream.get("state", {})
                            streams.append(NatsStreamInfo(
                                name=stream.get("name", "unknown"),
                                messages=state.get("messages", 0),
                                bytes=state.get("bytes", 0),
                                consumers=state.get("consumer_count", 0),
                                subjects=config.get("subjects", []),
                            ))

                if not streams:
                    # Try to get basic server info at least
                    resp = await client.get(f"{self.base_url}/varz")
                    if resp.status_code == 200:
                        return [NatsStreamInfo("server_ok", 0, 0, 0, [])]

                return streams

        except httpx.ConnectError:
            return [NatsStreamInfo("disconnected", -1, 0, 0, [])]
        except Exception as e:
            return [NatsStreamInfo(f"error", -1, 0, 0, [])]

    async def get_server_info(self) -> Dict[str, Any]:
        """Get NATS server info."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/varz")
                if resp.status_code == 200:
                    return resp.json()
        except:
            pass
        return {}


class SolanaMonitor:
    """Monitor Solana RPC and program status."""

    def __init__(self, rpc_url: str, programs: List[Tuple[str, str]]):
        self.rpc_url = rpc_url
        self.programs = programs
        self._tps_history: Deque[float] = deque(maxlen=30)

    async def get_health(self) -> SolanaHealth:
        """Get Solana cluster health."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get slot
                slot_resp = await client.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSlot",
                })
                slot = slot_resp.json().get("result", 0)

                # Get block height
                height_resp = await client.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBlockHeight",
                })
                block_height = height_resp.json().get("result", 0)

                # Get epoch info
                epoch_resp = await client.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getEpochInfo",
                })
                epoch_data = epoch_resp.json().get("result", {})
                epoch = epoch_data.get("epoch", 0)

                # Get recent performance samples for TPS
                perf_resp = await client.post(self.rpc_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getRecentPerformanceSamples",
                    "params": [1],
                })
                perf_data = perf_resp.json().get("result", [])
                tps = 0.0
                if perf_data:
                    sample = perf_data[0]
                    num_txs = sample.get("numTransactions", 0)
                    num_slots = sample.get("numSlots", 1)
                    slot_time = 0.4  # ~400ms per slot
                    tps = num_txs / (num_slots * slot_time) if num_slots > 0 else 0

                self._tps_history.append(tps)

                # Check health endpoint
                try:
                    health_resp = await client.get(f"{self.rpc_url.replace('/api', '')}/health")
                    health = "OK" if health_resp.status_code == 200 else "DEGRADED"
                except:
                    health = "OK"  # Some RPCs don't have /health

                return SolanaHealth(
                    rpc_url=self.rpc_url,
                    slot=slot,
                    block_height=block_height,
                    epoch=epoch,
                    tps=tps,
                    health=health,
                )

        except Exception as e:
            return SolanaHealth(
                rpc_url=self.rpc_url,
                slot=0,
                block_height=0,
                epoch=0,
                tps=0,
                health=f"ERROR: {type(e).__name__}",
            )

    async def get_program_status(self) -> List[SolanaProgramStatus]:
        """Check if our programs are deployed and executable."""
        programs = self.programs

        results = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for name, program_id in programs:
                    try:
                        resp = await client.post(self.rpc_url, json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "getAccountInfo",
                            "params": [program_id, {"encoding": "base64"}],
                        })
                        data = resp.json().get("result", {})
                        value = data.get("value")

                        if value:
                            results.append(SolanaProgramStatus(
                                name=name,
                                program_id=program_id[:8] + "...",
                                executable=value.get("executable", False),
                                lamports=value.get("lamports", 0),
                            ))
                        else:
                            results.append(SolanaProgramStatus(
                                name=name,
                                program_id=program_id[:8] + "...",
                                executable=False,
                                lamports=0,
                            ))
                    except Exception:
                        results.append(SolanaProgramStatus(
                            name=name,
                            program_id=program_id[:8] + "...",
                            executable=False,
                            lamports=-1,
                        ))

        except Exception:
            for name, program_id in programs:
                results.append(SolanaProgramStatus(
                    name=name,
                    program_id=program_id[:8] + "...",
                    executable=False,
                    lamports=-1,
                ))

        return results

    def get_tps_history(self) -> List[float]:
        return list(self._tps_history)


# ============================================================================
# WIDGETS
# ============================================================================

class LogViewer(RichLog):
    """Enhanced log viewer with filtering."""

    filter_level = reactive(LogLevel.INFO)
    filter_text = reactive("")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, highlight=True, markup=True, **kwargs)
        self._all_entries: Deque[LogEntry] = deque(maxlen=500)

    def add_entry(self, entry: LogEntry):
        self._all_entries.append(entry)
        self._render_entry(entry)

    def _render_entry(self, entry: LogEntry):
        level_order = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]
        if level_order.index(entry.level) < level_order.index(self.filter_level):
            return

        if self.filter_text and self.filter_text.lower() not in entry.message.lower():
            return

        colors = {
            LogLevel.DEBUG: "dim",
            LogLevel.INFO: "white",
            LogLevel.WARNING: "yellow",
            LogLevel.ERROR: "red bold",
            LogLevel.CRITICAL: "red bold reverse",
        }

        ts = entry.timestamp.strftime("%H:%M:%S")
        level_str = f"[{entry.level.value:8}]"

        text = Text()
        text.append(f"{ts} ", style="cyan")
        text.append(level_str, style=colors.get(entry.level, "white"))
        text.append(f" {entry.message}", style=colors.get(entry.level, "white"))

        self.write(text)

    def refresh_view(self):
        self.clear()
        for entry in self._all_entries:
            self._render_entry(entry)


class ContainerTable(DataTable):
    def on_mount(self):
        self.add_columns("St", "Container", "Health", "CPU", "Mem", "Uptime")
        self.cursor_type = "row"


class HealthTable(DataTable):
    def on_mount(self):
        self.add_columns("Endpoint", "Status", "Latency")
        self.cursor_type = "row"


class CeleryTable(DataTable):
    def on_mount(self):
        self.add_columns("Worker", "Status", "Active", "Queue")
        self.cursor_type = "row"


class NatsTable(DataTable):
    def on_mount(self):
        self.add_columns("Stream", "Msgs", "Consumers")
        self.cursor_type = "row"


class SolanaPanel(Static):
    """Panel showing Solana RPC status."""

    def compose(self) -> ComposeResult:
        yield Static("Slot: --", id="sol-slot")
        yield Static("Epoch: --", id="sol-epoch")
        yield Static("TPS: --", id="sol-tps")
        yield Sparkline([], id="spark-tps")


class ProgramTable(DataTable):
    def on_mount(self):
        self.add_columns("Program", "ID", "Status")
        self.cursor_type = "row"


# ============================================================================
# SCREENS
# ============================================================================

class HelpScreen(ModalScreen):
    """Help overlay."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("""
[bold cyan]BoulderRollers Dashboard - Keyboard Shortcuts[/]

[bold]Navigation[/]
  [cyan]Tab[/]       Switch between panels
  [cyan]1-4[/]       Jump to specific tab

[bold]Filtering[/]
  [cyan]/[/]         Focus search filter
  [cyan]d[/]         Show DEBUG and above
  [cyan]i[/]         Show INFO and above
  [cyan]w[/]         Show WARNING and above
  [cyan]e[/]         Show ERROR and above

[bold]Actions[/]
  [cyan]r[/]         Refresh all monitors
  [cyan]c[/]         Clear log view
  [cyan]p[/]         Pause/resume log tailing

[bold]General[/]
  [cyan]?[/]         Show this help
  [cyan]q[/]         Quit

[bold]Monitors[/]
  API Health    - FastAPI endpoints
  Containers    - Docker status
  Celery        - Workers & queues (via Redis)
  NATS          - JetStream streams
  Solana        - RPC health & programs

[dim]Press any key to close...[/]
""", id="help-text"),
            id="help-container",
        )


# ============================================================================
# MAIN APP
# ============================================================================

class DashboardApp(App):
    """BoulderRollers Backend Dashboard."""

    CSS = """
    Screen {
        background: #1a1a2e;
    }

    #main-container {
        height: 100%;
    }

    #status-row {
        height: 3;
        background: #16213e;
        border-bottom: solid #0f3460;
        padding: 0 2;
    }

    .status-label {
        color: #6b7280;
    }

    .status-value {
        color: #32cd32;
    }

    .status-value.error {
        color: #dc143c;
    }

    .status-value.warn {
        color: #ff8c00;
    }

    #content-area {
        height: 1fr;
    }

    #left-panel {
        width: 55%;
        border-right: solid #0f3460;
    }

    #right-panel {
        width: 45%;
        padding: 1;
    }

    #log-container {
        height: 1fr;
        border: solid #0f3460;
        background: #0d1117;
    }

    #filter-bar {
        height: 3;
        background: #16213e;
        padding: 0 1;
    }

    #filter-input {
        width: 25;
    }

    .filter-btn {
        min-width: 6;
        margin: 0 1;
    }

    .filter-btn.active {
        background: #daa520;
        color: #1a1a2e;
    }

    RichLog {
        background: #0d1117;
        scrollbar-background: #16213e;
        scrollbar-color: #0f3460;
    }

    DataTable {
        height: auto;
        max-height: 8;
        background: #0d1117;
        margin: 0 0 1 0;
    }

    DataTable > .datatable--header {
        background: #16213e;
        color: #daa520;
    }

    DataTable > .datatable--cursor {
        background: #0f3460;
    }

    .section-title {
        color: #daa520;
        text-style: bold;
        padding: 1 0 0 0;
    }

    .subsection {
        color: #9ca3af;
        padding: 0 0 0 0;
    }

    .metric-label {
        color: #6b7280;
    }

    Sparkline {
        height: 2;
        margin: 0 0 1 0;
    }

    Sparkline > .sparkline--min-color {
        color: #228b22;
    }

    Sparkline > .sparkline--max-color {
        color: #dc143c;
    }

    #help-container {
        background: #16213e;
        border: double #daa520;
        padding: 2;
        margin: 2 4;
        height: auto;
    }

    #help-text {
        color: #e5e5e5;
    }

    #mode-indicator {
        dock: right;
        width: auto;
        padding: 0 2;
        color: #daa520;
    }

    .paused {
        color: #ff8c00;
    }

    #sol-slot, #sol-epoch, #sol-tps {
        color: #9ca3af;
        padding: 0;
    }

    .solana-ok {
        color: #32cd32;
    }

    .solana-err {
        color: #dc143c;
    }

    #right-scroll {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("slash", "focus_filter", "Filter"),
        Binding("r", "refresh", "Refresh"),
        Binding("c", "clear_logs", "Clear"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("d", "filter_debug", "Debug"),
        Binding("i", "filter_info", "Info"),
        Binding("w", "filter_warning", "Warn"),
        Binding("e", "filter_error", "Error"),
    ]

    is_remote = reactive(False)
    is_paused = reactive(False)

    def __init__(
        self,
        config: DashboardConfig,
        is_remote: bool = False,
        solana_rpc_url: Optional[str] = None,
    ):
        super().__init__()
        self.config = config
        self.initial_remote = is_remote
        self.solana_rpc_url = solana_rpc_url or self.config.solana_rpc_devnet
        self.solana_label = self._derive_solana_label()
        self.log_tailer: Optional[LogTailer] = None
        self.docker_monitor: Optional[DockerMonitor] = None
        self.health_checker: Optional[HealthChecker] = None
        self.metrics_parser: Optional[MetricsParser] = None
        self.celery_monitor: Optional[CeleryMonitor] = None
        self.nats_monitor: Optional[NatsMonitor] = None
        self.solana_monitor: Optional[SolanaMonitor] = None

    def _derive_solana_label(self) -> str:
        if self.solana_rpc_url == self.config.solana_rpc_mainnet:
            return "SOLANA (mainnet)"
        if self.solana_rpc_url == self.config.solana_rpc_devnet:
            return "SOLANA (devnet)"
        return "SOLANA (custom)"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="main-container"):
            with Horizontal(id="status-row"):
                yield Static("MODE:", classes="status-label")
                yield Static("LOCAL", id="mode-value", classes="status-value")
                yield Static(" | ", classes="status-label")
                yield Static("API:", classes="status-label")
                yield Static("--", id="api-status", classes="status-value")
                yield Static(" | ", classes="status-label")
                yield Static("DOCKER:", classes="status-label")
                yield Static("--", id="container-count", classes="status-value")
                yield Static(" | ", classes="status-label")
                yield Static("CELERY:", classes="status-label")
                yield Static("--", id="celery-status", classes="status-value")
                yield Static(" | ", classes="status-label")
                yield Static("NATS:", classes="status-label")
                yield Static("--", id="nats-status", classes="status-value")
                yield Static(" | ", classes="status-label")
                yield Static("SOL:", classes="status-label")
                yield Static("--", id="sol-status", classes="status-value")
                yield Static("[LIVE]", id="mode-indicator")

            with Horizontal(id="content-area"):
                with Vertical(id="left-panel"):
                    with Horizontal(id="filter-bar"):
                        yield Input(placeholder="Search...", id="filter-input")
                        yield Button("D", id="btn-debug", classes="filter-btn")
                        yield Button("I", id="btn-info", classes="filter-btn active")
                        yield Button("W", id="btn-warn", classes="filter-btn")
                        yield Button("E", id="btn-error", classes="filter-btn")

                    with Container(id="log-container"):
                        yield LogViewer(id="log-viewer")

                with ScrollableContainer(id="right-scroll"):
                    with Vertical(id="right-panel"):
                        yield Static("CONTAINERS", classes="section-title")
                        yield ContainerTable(id="container-table")

                        yield Static("API HEALTH", classes="section-title")
                        yield HealthTable(id="health-table")

                        yield Static("METRICS", classes="section-title")
                        yield Static("RPS: --", id="metric-rps", classes="metric-label")
                        yield Static("Latency: --", id="metric-latency", classes="metric-label")
                        yield Static("Mem: --", id="metric-mem", classes="metric-label")
                        yield Static("CPU: --", id="metric-cpu", classes="metric-label")
                        yield Sparkline([], id="spark-rps")

                        yield Static("CELERY", classes="section-title")
                        yield CeleryTable(id="celery-table")

                        yield Static("NATS JETSTREAM", classes="section-title")
                        yield NatsTable(id="nats-table")

                        yield Static(self.solana_label, classes="section-title")
                        yield SolanaPanel(id="solana-panel")
                        yield ProgramTable(id="program-table")

        yield Footer()

    async def on_mount(self):
        self.is_remote = self.initial_remote

        # Initialize all monitors
        self.log_tailer = LogTailer(self.config, is_remote=self.is_remote)
        self.docker_monitor = DockerMonitor(self.config, is_remote=self.is_remote)
        self.health_checker = HealthChecker(self.config, is_remote=self.is_remote)
        self.metrics_parser = MetricsParser(self.config, is_remote=self.is_remote)
        self.celery_monitor = CeleryMonitor(self.config, is_remote=self.is_remote)
        self.nats_monitor = NatsMonitor(self.config, is_remote=self.is_remote)
        self.solana_monitor = SolanaMonitor(
            self.solana_rpc_url, self.config.program_list()
        )

        mode_value = self.query_one("#mode-value", Static)
        mode_value.update("REMOTE" if self.is_remote else "LOCAL")

        # Start background tasks
        self.start_log_tailing()
        self.set_interval(5.0, self.refresh_containers)
        self.set_interval(10.0, self.refresh_health)
        self.set_interval(METRICS_REFRESH_SECONDS, self.refresh_metrics)
        self.set_interval(10.0, self.refresh_celery)
        self.set_interval(8.0, self.refresh_nats)
        self.set_interval(15.0, self.refresh_solana)

        # Initial refresh
        await self.refresh_all()

    @work(exclusive=True, thread=True)
    async def start_log_tailing(self):
        try:
            stream = await self.log_tailer.start()
            log_viewer = self.query_one("#log-viewer", LogViewer)

            while True:
                if self.is_paused:
                    await asyncio.sleep(0.5)
                    continue

                line = await stream.readline()
                if not line:
                    break

                text = line.decode('utf-8', errors='replace').strip()
                if text:
                    entry = LogEntry.from_line(text)
                    self.call_from_thread(log_viewer.add_entry, entry)

        except Exception as e:
            log_viewer = self.query_one("#log-viewer", LogViewer)
            self.call_from_thread(
                log_viewer.write,
                Text(f"[Log tailing error: {e}]", style="red")
            )

    async def refresh_containers(self):
        containers = await self.docker_monitor.get_containers()
        table = self.query_one("#container-table", ContainerTable)
        table.clear()

        running = 0
        for c in containers:
            status_style = "green" if c.status == "running" else "red"
            health_style = "green" if c.health == "healthy" else ("yellow" if c.health == "running" else "red")

            table.add_row(
                Text("*" if c.status == "running" else "x", style=status_style),
                c.name[:15],
                Text(c.health[:8], style=health_style),
                c.cpu[:7],
                c.memory[:10],
                c.uptime[:10],
            )
            if c.status == "running":
                running += 1

        count = self.query_one("#container-count", Static)
        count.update(f"{running}/{len(containers)}")

    async def refresh_all(self):
        await self.refresh_containers()
        await self.refresh_health()
        await self.refresh_metrics()
        await self.refresh_celery()
        await self.refresh_nats()
        await self.refresh_solana()

    async def refresh_health(self):
        results = await self.health_checker.check_all()
        table = self.query_one("#health-table", HealthTable)
        table.clear()

        all_ok = True
        for h in results:
            status_style = "green" if h.status == "OK" else "red"
            latency_style = "green" if h.latency_ms < 100 else ("yellow" if h.latency_ms < 500 else "red")

            table.add_row(
                h.endpoint[:12],
                Text(h.status[:10], style=status_style),
                Text(f"{h.latency_ms:.0f}ms", style=latency_style),
            )
            if h.status != "OK":
                all_ok = False

        api_status = self.query_one("#api-status", Static)
        api_status.update("OK" if all_ok else "ERR")
        api_status.remove_class("error", "warn")
        if not all_ok:
            api_status.add_class("error")

    async def refresh_metrics(self):
        metrics = await self.metrics_parser.fetch()
        rps = _rate_metric(metrics, "http_requests_total", METRICS_REFRESH_SECONDS)
        latency_ms = _avg_latency_ms(metrics, METRICS_REFRESH_SECONDS)
        mem_bytes = _latest_metric(metrics, "process_resident_memory_bytes")
        cpu_rate = _rate_metric(metrics, "process_cpu_seconds_total", METRICS_REFRESH_SECONDS)

        rps_label = self.query_one("#metric-rps", Static)
        latency_label = self.query_one("#metric-latency", Static)
        mem_label = self.query_one("#metric-mem", Static)
        cpu_label = self.query_one("#metric-cpu", Static)

        rps_label.update(f"RPS: {rps:.2f}" if rps is not None else "RPS: --")
        latency_label.update(
            f"Latency: {latency_ms:.0f}ms" if latency_ms is not None else "Latency: --"
        )
        mem_label.update(f"Mem: {_format_bytes(mem_bytes)}")
        if cpu_rate is None:
            cpu_label.update("CPU: --")
        else:
            cpu_label.update(f"CPU: {cpu_rate * 100:.0f}%")

        spark = self.query_one("#spark-rps", Sparkline)
        spark.data = _rate_series(metrics, "http_requests_total", METRICS_REFRESH_SECONDS)

    async def refresh_celery(self):
        workers = await self.celery_monitor.get_workers()
        queues = await self.celery_monitor.get_queues()
        table = self.query_one("#celery-table", CeleryTable)
        table.clear()

        total_active = 0
        status_ok = True

        for w in workers:
            status_style = "green" if w.status == "online" else "red"
            if w.status != "online":
                status_ok = False

            queue_info = ""
            if queues:
                queue_info = f"{queues[0].messages}q"

            table.add_row(
                w.name[:12],
                Text(w.status[:8], style=status_style),
                str(w.active_tasks),
                queue_info,
            )
            total_active += w.active_tasks

        celery_status = self.query_one("#celery-status", Static)
        if status_ok:
            celery_status.update(f"{len(workers)}w")
            celery_status.remove_class("error", "warn")
        else:
            celery_status.update("ERR")
            celery_status.add_class("error")

    async def refresh_nats(self):
        streams = await self.nats_monitor.get_streams()
        table = self.query_one("#nats-table", NatsTable)
        table.clear()

        status_ok = True
        total_msgs = 0

        for s in streams:
            if s.messages < 0:
                status_ok = False
                table.add_row(
                    s.name[:12],
                    Text("--", style="red"),
                    "--",
                )
            else:
                total_msgs += s.messages
                table.add_row(
                    s.name[:12],
                    str(s.messages),
                    str(s.consumers),
                )

        nats_status = self.query_one("#nats-status", Static)
        if not streams or not status_ok:
            nats_status.update("OFF")
            nats_status.add_class("warn")
        else:
            nats_status.update(f"{len(streams)}s")
            nats_status.remove_class("error", "warn")

    async def refresh_solana(self):
        health = await self.solana_monitor.get_health()
        programs = await self.solana_monitor.get_program_status()

        # Update Solana panel
        slot_label = self.query_one("#sol-slot", Static)
        epoch_label = self.query_one("#sol-epoch", Static)
        tps_label = self.query_one("#sol-tps", Static)

        slot_label.update(f"Slot: {health.slot:,}")
        epoch_label.update(f"Epoch: {health.epoch}")
        tps_label.update(f"TPS: {health.tps:.0f}")

        # Update TPS sparkline
        spark = self.query_one("#spark-tps", Sparkline)
        spark.data = self.solana_monitor.get_tps_history()

        # Update programs table
        table = self.query_one("#program-table", ProgramTable)
        table.clear()

        all_ok = True
        for p in programs:
            if p.executable:
                status = Text("OK", style="green")
            elif p.lamports == 0:
                status = Text("NOT DEPLOYED", style="yellow")
                all_ok = False
            else:
                status = Text("ERROR", style="red")
                all_ok = False

            table.add_row(p.name[:12], p.program_id, status)

        # Update status bar
        sol_status = self.query_one("#sol-status", Static)
        sol_status.remove_class("error", "warn")
        if "ERROR" in health.health:
            sol_status.update("ERR")
            sol_status.add_class("error")
        elif not all_ok:
            sol_status.update("WARN")
            sol_status.add_class("warn")
        else:
            sol_status.update("OK")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            log_viewer = self.query_one("#log-viewer", LogViewer)
            log_viewer.filter_text = event.value
            log_viewer.refresh_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_levels = {
            "btn-debug": LogLevel.DEBUG,
            "btn-info": LogLevel.INFO,
            "btn-warn": LogLevel.WARNING,
            "btn-error": LogLevel.ERROR,
        }

        if event.button.id in button_levels:
            for btn_id in button_levels:
                btn = self.query_one(f"#{btn_id}", Button)
                btn.remove_class("active")
            event.button.add_class("active")

            log_viewer = self.query_one("#log-viewer", LogViewer)
            log_viewer.filter_level = button_levels[event.button.id]
            log_viewer.refresh_view()

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_focus_filter(self):
        self.query_one("#filter-input", Input).focus()

    async def action_refresh(self):
        await self.refresh_all()

    def action_clear_logs(self):
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.clear()
        log_viewer._all_entries.clear()

    def action_toggle_pause(self):
        self.is_paused = not self.is_paused
        indicator = self.query_one("#mode-indicator", Static)
        if self.is_paused:
            indicator.update("[PAUSED]")
            indicator.add_class("paused")
        else:
            indicator.update("[LIVE]")
            indicator.remove_class("paused")

    def action_filter_debug(self):
        self.query_one("#btn-debug", Button).press()

    def action_filter_info(self):
        self.query_one("#btn-info", Button).press()

    def action_filter_warning(self):
        self.query_one("#btn-warn", Button).press()

    def action_filter_error(self):
        self.query_one("#btn-error", Button).press()


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="BoulderRollers Backend Dashboard")
    parser.add_argument("--remote", "-r", action="store_true",
                        help="Monitor remote production server")
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

    app = DashboardApp(config=config, is_remote=args.remote, solana_rpc_url=solana_rpc_url)
    app.run()


if __name__ == "__main__":
    main()
