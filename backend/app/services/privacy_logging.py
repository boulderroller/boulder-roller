"""Readable operational exceptions without rider wallets, email or URL tokens."""
from __future__ import annotations

import logging
import re
import traceback

_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WALLET = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")
_URL = re.compile(r"https?://[^\s'\"<>]+")
_TOKEN = re.compile(r"(?i)(bearer\s+|(?:token|secret|password|authorization)[=:]\s*)[^\s,;]+")
_COORDINATE = re.compile(r"(?<![\w.])-?\d{1,3}\.\d{4,}(?![\w.])")


def scrub_log_text(value: object) -> str:
    text = str(value)
    for pattern in (_EMAIL, _WALLET, _URL, _TOKEN, _COORDINATE):
        text = pattern.sub("[redacted]", text)
    return text


def install_exception_redaction() -> None:
    """Retain exc_info for Sentry and stack frames, sanitize rendered tracebacks."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_privacy_exceptions", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if record.exc_info:
            record.exc_text = scrub_log_text("".join(traceback.format_exception(*record.exc_info)))
        return record

    factory._privacy_exceptions = True
    logging.setLogRecordFactory(factory)


install_exception_redaction()
