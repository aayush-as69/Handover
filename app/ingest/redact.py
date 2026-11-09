"""Mask secrets before anything is stored, shown or sent to a model.

Redaction happens at ingestion, so a raw secret never reaches the database, the review screen
or the AI. The patterns lean towards masking too much: a false positive hides a harmless word,
a false negative leaks a credential.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# key = value / key: value (also JSON "key": "value", DB_PASSWORD=..., client_secret=...), where
# the key name suggests a credential. The key may be part of a longer name joined by _ or -.
_KEYWORDS = (r"api[_-]?key|apikey|secret|token|passwd|password|pwd|passphrase|credentials?|"
             r"access[_-]?key|private[_-]?key|auth(?:orization)?")
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_-])*(?:" + _KEYWORDS + r")(?:[_-][A-Za-z0-9]+)*)"
    r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})"
)

_PLACEHOLDERS = {"none", "null", "true", "false", "todo", "tbd", "yes", "no", "n/a", "xxxx", "****", "redacted"}

# A short value is only masked when the key plainly means a password (not for "token: 30m").
_PASSWORDY = re.compile(
    r"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_-])*(?:password|passwd|pwd|passphrase|secret)"
    r"(?:[_-][A-Za-z0-9]+)*)([\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{4,5})(?![^\s\"',;])"
)
# password = 'a phrase with spaces' (value quoted, so it may contain spaces)
_QUOTED = re.compile(
    r"(?i)(?<![A-Za-z0-9])((?:[A-Za-z0-9]+[_-])*(?:" + _KEYWORDS + r")(?:[_-][A-Za-z0-9]+)*)"
    r"(\s*[:=]\s*)([\"'])([^\"'\n]{6,200})\3"
)
# Said in a sentence: "the password is Hunter2Hunter2". Needs a digit, capital or symbol so that
# ordinary prose such as "the password is required" is left alone.
_SPOKEN = re.compile(
    r"(?i)\b(password|passcode|passphrase|pwd|pin|secret|api key|token)\s+(?:is|was|=)\s*:?\s*"
    r"([^\s\"',;]{6,})"
)
# curl -u user:password / --user user:password
_CURL_USER = re.compile(r"(?i)(\s(?:-u|--user)[ =]+)([^\s:]+):([^\s]{3,})")

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


# An unlabelled credential still looks random: a long unbroken run of mixed characters. Hashes,
# UUIDs and ordinary identifiers are recognised and left alone.
_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/_=.-])[A-Za-z0-9+/_=-]{24,}(?![A-Za-z0-9+/_=-])")
_HEX_HASH = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{56}|[0-9a-f]{64})$", re.I)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MIN_ENTROPY = 4.0          # bits per character; random base62 of 24+ chars is about 4.3-5.5


def _entropy(token: str) -> float:
    n = len(token)
    return -sum(c / n * math.log2(c / n) for c in Counter(token).values())


def looks_random(token: str) -> bool:
    if _HEX_HASH.match(token) or _UUID.match(token) or token.startswith("[REDACTED"):
        return False
    if any(len(piece) >= 4 and piece.isalpha() and (piece.islower() or piece.istitle())
           for piece in re.split(r"[^A-Za-z0-9]+", token)):
        return False                                  # paths and names built from real words
    classes = sum([any(c.islower() for c in token), any(c.isupper() for c in token),
                   any(c.isdigit() for c in token), any(c in "+/_=-" for c in token)])
    if classes < 3 or not any(c.isdigit() for c in token):
        return False                                  # words, slugs and identifiers
    return _entropy(token) >= MIN_ENTROPY


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad"))


def redact(text: str) -> RedactionResult:
    """Mask secrets. Text disguised with invisible characters or full-width letters is also
    checked in its plain form; if that reveals a secret, the plain, masked text is kept."""
    plain = unicodedata.normalize("NFKC", text.translate(_INVISIBLE))
    result = _redact(text)
    if plain != text:
        disguised = _redact(plain)
        if len(disguised.kinds) > len(result.kinds):
            return disguised
    return result


def _redact(text: str) -> RedactionResult:
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

    def _mask_short(match: re.Match) -> str:
        value = match.group(3)
        if value.startswith("[REDACTED:") or value.lower() in _PLACEHOLDERS:
            return match.group(0)
        kinds.append("secret")
        return f"{match.group(1)}{match.group(2)}[REDACTED:secret]"

    text = _PASSWORDY.sub(_mask_short, text)

    def _mask_quoted(match: re.Match) -> str:
        if match.group(4).startswith("[REDACTED:") or match.group(4).lower() in _PLACEHOLDERS:
            return match.group(0)
        kinds.append("secret")
        return f"{match.group(1)}{match.group(2)}{match.group(3)}[REDACTED:secret]{match.group(3)}"

    text = _QUOTED.sub(_mask_quoted, text)

    def _mask_spoken(match: re.Match) -> str:
        value = match.group(2)
        if value.startswith("[REDACTED:") or value.lower() in _PLACEHOLDERS:
            return match.group(0)
        if not any(c.isdigit() or c.isupper() or not c.isalnum() for c in value):
            return match.group(0)                    # plain lowercase word: ordinary prose
        kinds.append("secret")
        return match.group(0).replace(value, "[REDACTED:secret]")

    text = _SPOKEN.sub(_mask_spoken, text)

    def _mask_curl(match: re.Match) -> str:
        kinds.append("credential_url")
        return f"{match.group(1)}{match.group(2)}:[REDACTED:credential_url]"

    text = _CURL_USER.sub(_mask_curl, text)

    def _mask_random(match: re.Match) -> str:
        if not looks_random(match.group(0)):
            return match.group(0)
        kinds.append("high_entropy")
        return "[REDACTED:high_entropy]"

    text = _CANDIDATE.sub(_mask_random, text)
    return RedactionResult(text=text, kinds=kinds)
