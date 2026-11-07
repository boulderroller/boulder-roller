"""An allowlist for outbound diagnostics, including background exceptions.

Free text cannot be reliably scrubbed for a rider's name. Keep error types,
stack locations, opaque ids and status codes; omit bodies, locals and messages.
The portal mirrors this boundary in sentryPrivacy.ts.
"""
from __future__ import annotations

import re
import math
import ast
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


_OPAQUE_ID = re.compile(r"(?:[0-9a-fA-F]{16,32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z")
_ROUTE_PARTS = frozenset("api v1 v2 auth invite validate verify privy admin access geocoding search privacy zones settings users me rides media init complete followers following compliance export account preflight status health profile avatar notifications".split())
_IDS = frozenset("id user_id ride_id media_id object_id request_id event_id trace_id span_id parent_span_id".split())
_STATUS_KEYS = frozenset("status_code http.status_code status response.status_code".split())
_ENUMS = {
    "level": {"fatal", "error", "warning", "info", "debug", "log"},
    "method": {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"},
    "op": {"http.client", "http.server", "db", "db.sql.query", "navigation", "pageload", "ui.action", "queue.task"},
    "category": {"http", "fetch", "xhr", "console", "navigation", "ui.click", "ui.input"},
    "type": {"http", "default", "navigation", "user", "system", "error"},
    "status": {"ok", "unknown_error", "internal_error", "invalid_argument", "not_found", "unavailable", "cancelled", "deadline_exceeded"},
    "error_code": set("storage_uploaded storage_upload_failed storage_downloaded storage_download_failed storage_signed storage_sign_failed storage_absent storage_deleted storage_delete_failed storage_size_failed storage_check_failed storage_upload_signed storage_upload_sign_failed auth_identity_conflict".split()),
}
_ENUMS["http.method"] = _ENUMS["method"]


def _error_type(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"(?:[A-Za-z_][A-Za-z_0-9]{0,80})?(?:Error|Exception|Timeout)", value))


@lru_cache(maxsize=256)
def _literal_templates(filename: str) -> frozenset[str]:
    """Only checked-in source literals may title logging events."""
    path = Path(filename).resolve()
    if not path.is_relative_to(Path(__file__).resolve().parents[2]):
        return frozenset()
    try:
        tree = ast.parse(path.read_text())
        result = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"debug", "info", "warning", "error", "exception", "critical", "log"}:
                continue
            index = 1 if node.func.attr == "log" else 0
            if len(node.args) > index and isinstance(node.args[index], ast.Constant) and isinstance(node.args[index].value, str):
                result.add(node.args[index].value)
        return frozenset(result)
    except (OSError, SyntaxError):
        return frozenset()


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("", "http", "https"):
            return None
        path = "/".join(
            part if not part or part in _ROUTE_PARTS or _OPAQUE_ID.fullmatch(part) else "[Filtered]"
            for part in parts.path.split("/")
        )
        # Userinfo, query and fragment can all contain credentials.
        return urlunsplit((parts.scheme, parts.hostname or "", path, "", ""))
    except ValueError:
        return None


def _diagnostics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in _IDS and isinstance(item, str) and _OPAQUE_ID.fullmatch(item):
            result[key] = item
        elif key in _STATUS_KEYS and isinstance(item, int) and 100 <= item <= 599:
            result[key] = item
        elif key in _ENUMS and isinstance(item, str) and item in _ENUMS[key]:
            result[key] = item
        elif key == "error_type" and _error_type(item):
            result[key] = item
        elif key in {"url", "http.url"}:
            url = _safe_url(item)
            if url is not None:
                result[key] = url
    return result


def _timing(value: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in ("start_timestamp", "timestamp"):
        item = value.get(key)
        if isinstance(item, (int, float)) and math.isfinite(item):
            result[key] = item
        elif isinstance(item, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", item):
            try:
                datetime.fromisoformat(item)
                result[key] = item
            except ValueError:
                pass
    return result


def _source_path(value: str) -> str:
    try:
        path = unquote(urlsplit(value).path)
    except ValueError:
        return "[Filtered]"
    parts = path.split("/")
    safe_dirs = {"src", "app", "routes", "services", "components", "lib", "backend", "web", "portal", "assets", "static", "build"}
    result = []
    for index, part in enumerate(parts):
        source_file = index == len(parts) - 1 and re.fullmatch(r"[\w.-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|swift|rs)", part)
        result.append(part if part in safe_dirs or source_file or not part else "[Filtered]")
    return "/".join(result)


def _stacktrace(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    frames = []
    for frame in value.get("frames", []):
        if not isinstance(frame, dict):
            continue
        clean = {key: frame[key] for key in ("function", "module", "lineno", "colno", "in_app") if key in frame}
        for key in ("filename", "abs_path"):
            path = frame.get(key)
            if isinstance(path, str):
                # Keep source locations, never URL tokens or local home names.
                clean[key] = _source_path(path)
        frames.append(clean)
    return {"frames": frames}


def scrub_sentry_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    # Sentry's fixed envelope metadata is SDK supplied, not rider input.
    result = {key: event[key] for key in (
        "event_id", "timestamp", "start_timestamp", "platform", "level", "release", "dist", "environment", "logger", "type",
    ) if key in event}
    logentry = event.get("logentry")
    record = _hint.get("log_record")
    # SDK logging events retain the unformatted template separately from args.
    # Never send the formatted text, arbitrary capture_message text, or fstrings.
    if (isinstance(logentry, dict) and record is not None
            and record.msg in _literal_templates(record.pathname)):
        template = logentry.get("message")
        if isinstance(template, str) and template == record.msg:
            from .privacy_logging import scrub_log_text
            params = logentry.get("params") or ()
            result["logentry"] = {"message": scrub_log_text(template), "params": (
                {key: "[Filtered]" for key in re.findall(r"%\(([A-Za-z_][A-Za-z_0-9]*)\)", template)
                 if key in params} if isinstance(params, dict)
                else ["[Filtered]" for _ in params])}
    for key in ("extra", "tags", "user"):
        if key in event:
            result[key] = _diagnostics(event[key])
    request = event.get("request")
    if isinstance(request, dict):
        result["request"] = _diagnostics(request)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        result["contexts"] = {key: _diagnostics(contexts[key]) for key in ("trace", "response") if key in contexts}
    if "transaction" in event:
        name = event["transaction"]
        if (event.get("transaction_info", {}).get("source") == "route" and isinstance(name, str)
                and re.fullmatch(r"/(?:[A-Za-z0-9_./-]|\{[A-Za-z_][A-Za-z0-9_:]*\})*", name)):
            result["transaction"] = name
            result["transaction_info"] = {"source": "route"}
        else:
            result["transaction"] = _safe_url(name) or "[Filtered]"
    exception = event.get("exception")
    if isinstance(exception, dict):
        result["exception"] = {"values": []}
        for value in exception.get("values", []):
            if isinstance(value, dict):
                clean = {"type": value["type"]} if _error_type(value.get("type")) else {}
                mechanism = value.get("mechanism")
                if isinstance(mechanism, dict) and isinstance(mechanism.get("handled"), bool):
                    clean["mechanism"] = {"type": "generic", "handled": mechanism["handled"]}
                if "stacktrace" in value:
                    clean["stacktrace"] = _stacktrace(value["stacktrace"])
                result["exception"]["values"].append(clean)
    if "stacktrace" in event:
        result["stacktrace"] = _stacktrace(event["stacktrace"])
    threads = event.get("threads")
    if isinstance(threads, dict) and isinstance(threads.get("values"), list):
        result["threads"] = {"values": [{"stacktrace": _stacktrace(thread.get("stacktrace"))}
                                      for thread in threads["values"] if isinstance(thread, dict)]}
    # Python uses {values: [...]}; browser SDKs use an array.
    breadcrumbs = event.get("breadcrumbs", {})
    crumbs = breadcrumbs.get("values", []) if isinstance(breadcrumbs, dict) else breadcrumbs
    if isinstance(crumbs, list):
        result["breadcrumbs"] = {"values": [
            {**_diagnostics(crumb), **_timing(crumb), "data": _diagnostics(crumb.get("data"))}
            for crumb in crumbs if isinstance(crumb, dict)
        ]}
    if isinstance(event.get("spans"), list):
        result["spans"] = [
            {**_diagnostics(span), **_timing(span), "data": _diagnostics(span.get("data"))}
            for span in event["spans"] if isinstance(span, dict)
        ]
    return result
