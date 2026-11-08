"""Mask secrets before anything is stored, shown or sent to a model.

Redaction happens at ingestion, so a raw secret never reaches the database, the review screen
or the AI. The patterns lean towards masking too much: a false positive hides a harmless word,
a false negative leaks a credential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# key = value / key: value, where the key name suggests a credential.
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|passwd|password|pwd)\b(\s*[:=]\s*)(\S{6,})"
)

_PATTERNS = [
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("stripe_key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
    ),
]


@dataclass
class RedactionResult:
    text: str
    kinds: list[str] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.kinds)


def redact(text: str) -> RedactionResult:
    kinds: list[str] = []

    for kind, pattern in _PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        kinds.extend([kind] * n)

    def _mask(match: re.Match) -> str:
        if match.group(3).startswith("[REDACTED:"):
            return match.group(0)  # already masked by a more specific pattern
        kinds.append("secret")
        return f"{match.group(1)}{match.group(2)}[REDACTED:secret]"

    text = _ASSIGNMENT.sub(_mask, text)
    return RedactionResult(text=text, kinds=kinds)
