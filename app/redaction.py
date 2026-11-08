"""Field-level redaction: hide parts of a claim, not just whole claims.

Access rules decide which claims a role may see. Redaction goes further inside a visible
claim: a viewer can read "Sponsor contact: [email hidden]" without the address. The policy is
per role and mechanical (patterns), so a reviewer can preview exactly what each role gets.
Patterns lean towards hiding too much.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import Role

PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "phone": re.compile(r"(?<![\w.])(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}(?![\w])"),
    "amount": re.compile(r"(?:(?:INR|Rs\.?|USD|EUR)\s?|[₹$€£])\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|lakh|lakhs|crore|million|M))?\b", re.I),
}
LABELS = {"email": "[email hidden]", "phone": "[phone hidden]", "amount": "[amount hidden]"}

# What each role may NOT see inside claims it can otherwise read.
POLICY: dict[Role, tuple[str, ...]] = {
    Role.admin: (),
    Role.approver: (),
    Role.viewer: ("email", "phone"),
    Role.restricted: ("email", "phone", "amount"),
}


@dataclass
class Redacted:
    text: str
    hidden: set[str]


def _looks_like_date(m: re.Match, text: str) -> bool:
    return bool(re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}", m.group().strip()))


def redact(role: Role, text: str) -> Redacted:
    hidden: set[str] = set()
    out = text
    for kind in POLICY[role]:
        def sub(m: re.Match, kind=kind) -> str:
            if kind == "phone" and (_looks_like_date(m, out) or len(re.sub(r"\D", "", m.group())) < 8):
                return m.group()
            hidden.add(kind)
            return LABELS[kind]
        out = PATTERNS[kind].sub(sub, out)
    return Redacted(out, hidden)


def redact_text(role: Role, text: str | None) -> str:
    return redact(role, text).text if text else (text or "")
