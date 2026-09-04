"""Structured logging module with API key redaction."""

import logging
import os
import re
import sys

# Collect secrets from environment for redaction
def _collect_secrets() -> list:
    secrets = []
    for var in ("FRED_API_KEY",):
        val = os.environ.get(var)
        if val:
            secrets.append(val)
    return secrets


class RedactFilter(logging.Filter):
    """Filter that redacts known API keys and secret-looking strings from log records."""

    def __init__(self):
        super().__init__()
        self._secrets = _collect_secrets()

    def _redact_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        # Also redact generic apikey query params in URLs
        text = re.sub(r"(apikey|api_key|key)=[^&\s]+", r"\1=[REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact_text(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._redact_text(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def get_logger(name: str = "finance") -> logging.Logger:
    """Return a configured logger with API key redaction enabled."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        handler.addFilter(RedactFilter())
        logger.addHandler(handler)

    # Ensure any logger created by name gets the redaction filter too (idempotent)
    if not any(isinstance(f, RedactFilter) for f in logger.filters):
        logger.addFilter(RedactFilter())

    return logger
