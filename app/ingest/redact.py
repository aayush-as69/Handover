"""Mask secrets before anything is stored, shown or sent to a model.

Redaction happens at ingestion, so a raw secret never reaches the database, the review screen
or the AI. The patterns lean towards masking too much: a false positive hides a harmless word,
a false negative leaks a credential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# key = value / key: value (also JSON "key": "value", DB_PASSWORD=..., client_secret=...), where
# the key name suggests a credential. The key may be part of a longer name joined by _ or -.
_KEYWORDS = (r"api[_-]?key|apikey|secret|token|passwd|password|pwd|passphrase|credentials?|"
             r"access[_-]?key|private[_-]?key|auth(?:orization)?")
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_-])*(?:" + _KEYWORDS + r")(?:[_-][A-Za-z0-9]+)*)"
    r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})"
)

_PATTERNS = [
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("slack_webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("llm_api_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("basic_auth", re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/]{12,}={0,2}")),
    # scheme://user:password@host  (databases, brokers, git remotes)
    ("credential_url", re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@]+:[^\s@/]{3,}@[^\s/]+")),
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
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
