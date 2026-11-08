"""LLM extractor for any provider that speaks the OpenAI chat-completions format.

That covers OpenAI, Google Gemini (OpenAI-compatible endpoint), Groq, OpenRouter, and many
self-hosted servers. Configure with environment variables:

    LLM_BASE_URL   e.g. https://generativelanguage.googleapis.com/v1beta/openai
    LLM_API_KEY    the provider's key
    LLM_MODEL      e.g. gemini-2.0-flash

Malformed model output never reaches the claim store: each claim is validated, bad ones are
dropped with a warning, and a batch whose JSON cannot be parsed is retried once.
"""

from __future__ import annotations

import json
import os
import re
from typing import Sequence

import httpx
from pydantic import ValidationError

from ..schemas import MAX_CLAIMS_PER_REPLY, ExtractedClaim, ExtractionResult
from .base import ChunkView, ExtractionError, ExtractorOutput
from .prompt import batch_chunks, build_messages


MAX_REPLY_CHARS = 400_000


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _reply_text(resp: httpx.Response) -> str:
    """Pull the text out of a chat-completions reply, accepting only well-formed shapes."""
    bad = ExtractionError("the LLM provider returned an unexpected response")
    try:
        body = resp.json()
        choice = body["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise bad
    if choice.get("finish_reason") == "length":
        raise ExtractionError("the model's reply was cut off (too long); try a smaller batch")
    if isinstance(content, list):          # some providers return a list of text parts
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            else:
                raise bad
        content = "".join(parts)
    if content is None:
        return ""
    if not isinstance(content, str):
        raise bad
    if len(content) > MAX_REPLY_CHARS:
        raise ExtractionError("the model's reply was unreasonably large and was refused")
    return content


def parse_model_output(content: str) -> tuple[list[ExtractedClaim], int]:
    """Return (valid claims, number of invalid claims). Raises ValueError if unparseable."""
    try:
        data = json.loads(_strip_fences(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply was not valid JSON ({exc.msg})")
    if isinstance(data, list):
        data = {"claims": data}
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise ValueError('reply must be a JSON object with a "claims" list')
    valid, invalid = [], 0
    if len(data["claims"]) > MAX_CLAIMS_PER_REPLY:
        invalid += len(data["claims"]) - MAX_CLAIMS_PER_REPLY
        data["claims"] = data["claims"][:MAX_CLAIMS_PER_REPLY]
    for item in data["claims"]:
        if not isinstance(item, dict):
            invalid += 1
            continue
        try:
            valid.append(ExtractedClaim.model_validate(item))
        except ValidationError:
            invalid += 1
    return valid, invalid


class OpenAICompatibleExtractor:
    remote = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        batch_chars: int = 12000,
        timeout: float = 90.0,
    ) -> None:
        self.name = f"llm:{model}"
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)
        self._batch_chars = batch_chars

    def _chat(self, messages: list[dict], json_mode: bool = True) -> str:
        payload = {"model": self._model, "messages": messages, "temperature": 0}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.post(
                self._url, json=payload, headers={"Authorization": f"Bearer {self._key}"}
            )
        except httpx.HTTPError:
            raise ExtractionError("could not reach the LLM provider")
        if resp.status_code in (401, 403):
            raise ExtractionError("the LLM provider rejected the API key")
        if resp.status_code == 429:
            raise ExtractionError("the LLM provider rate limit was reached; try again later")
        if resp.status_code == 400 and json_mode:
            return self._chat(messages, json_mode=False)  # some providers lack JSON mode
        if resp.status_code >= 400:
            raise ExtractionError(f"the LLM provider returned an error ({resp.status_code})")
        return _reply_text(resp)

    def _extract_batch(self, batch: Sequence[ChunkView], n: int) -> tuple[list[ExtractedClaim], list[str]]:
        messages = build_messages(batch)
        last_error = ""
        for attempt in range(2):
            content = self._chat(messages)
            try:
                claims, invalid = parse_model_output(content)
            except ValueError as exc:
                last_error = str(exc)
                messages = messages + [
                    {"role": "assistant", "content": content[:2000]},
                    {"role": "user",
                     "content": f"That reply was invalid: {last_error}. Reply with valid JSON only."},
                ]
                continue
            warnings = []
            if invalid:
                warnings.append(f"batch {n}: {invalid} malformed claim(s) from the model were dropped")
            return claims, warnings
        return [], [f"batch {n}: the model's reply could not be used ({last_error}); skipped"]

    def extract(self, chunks: Sequence[ChunkView]) -> ExtractorOutput:
        claims: list[ExtractedClaim] = []
        warnings: list[str] = []
        for n, batch in enumerate(batch_chunks(chunks, self._batch_chars), 1):
            got, warn = self._extract_batch(batch, n)
            claims += got
            warnings += warn
        return ExtractorOutput(ExtractionResult(claims=claims), warnings)


def llm_from_env(client: httpx.Client | None = None) -> OpenAICompatibleExtractor:
    names = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ExtractionError("set these environment variables first: " + ", ".join(missing))
    return OpenAICompatibleExtractor(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        client=client,
    )
