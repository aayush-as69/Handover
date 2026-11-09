"""Model output is untrusted. These replies are all wrong in ways real providers produce."""

import json

import httpx
import pytest

from app.extract import ExtractionError
from app.extract.llm import OpenAICompatibleExtractor, parse_model_output
from tests.test_extract import GOOD, view


def llm(handler):
    return OpenAICompatibleExtractor(
        base_url="https://llm.example/v1", api_key="k" * 8, model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(body, status=200):
    return lambda request: httpx.Response(status, json=body)


def choice(content, **extra):
    return {"choices": [{"message": {"content": content}, **extra}]}


def run(handler):
    return llm(handler).extract([view()])


def claim(**over):
    base = {"statement": "Use Postgres for storage", "type": "decision",
            "evidence": [{"chunk_id": 1, "snippet": "Use Postgres"}]}
    base.update(over)
    return base


# ------------------------------------------------------------ reply envelope


def test_content_split_into_parts_is_joined():
    half = len(GOOD) // 2
    parts = [{"type": "text", "text": GOOD[:half]}, {"type": "text", "text": GOOD[half:]}]
    out = run(reply(choice(parts)))
    assert len(out.result.claims) == 1


@pytest.mark.parametrize("content", [12345, {"a": 1}, [1, 2], [{"no_text": 1}], True])
def test_content_of_the_wrong_type_is_refused_not_crashed(content):
    with pytest.raises(ExtractionError, match="unexpected response"):
        run(reply(choice(content)))


def test_null_content_is_treated_as_empty_and_skipped():
    out = run(reply(choice(None)))
    assert out.result.claims == [] and any("could not be used" in w for w in out.warnings)


@pytest.mark.parametrize("body", [[], "text", {"choices": []}, {"choices": ["x"]},
                                  {"choices": [{"message": "x"}]}, {"nope": 1}])
def test_malformed_envelopes_are_refused(body):
    with pytest.raises(ExtractionError, match="unexpected response"):
        run(reply(body))


def test_a_truncated_reply_is_not_used():
    with pytest.raises(ExtractionError, match="cut off"):
        run(reply(choice(GOOD[:30], finish_reason="length")))


def test_an_enormous_reply_is_refused():
    with pytest.raises(ExtractionError, match="unreasonably large"):
        run(reply(choice("x" * 500_000)))


# ------------------------------------------------------------ claim contents


@pytest.mark.parametrize("bad", [
    claim(evidence=[{"chunk_id": True, "snippet": "Use Postgres"}]),       # boolean
    claim(evidence=[{"chunk_id": "1", "snippet": "Use Postgres"}]),        # string number
    claim(evidence=[{"chunk_id": 1.0, "snippet": "Use Postgres"}]),        # float
    claim(evidence=[{"chunk_id": 1, "snippet": ["Use Postgres"]}]),        # list
    claim(evidence=[{"chunk_id": 1, "snippet": 5}]),
    claim(evidence=[{"chunk_id": 1, "snippet": "\x00\x01"}]),              # only control chars
    claim(evidence="Use Postgres"),
    claim(evidence=[{"chunk_id": 1, "snippet": "x" * 3000}]),
    claim(evidence=[{"chunk_id": 1, "snippet": "ok text"}] * 11),
    claim(statement=123), claim(statement="   "), claim(statement="x" * 2000),
    claim(statement=["Use Postgres"]),
    claim(type="not-a-type"), claim(type=5), claim(type=None),
    claim(owner=["Riya"]), claim(topic=7), claim(value="v" * 500),
    "just a string", 42, None, ["nested"],
])
def test_each_bad_claim_is_dropped_and_the_good_one_kept(bad):
    content = json.dumps({"claims": [bad, claim()]})
    claims, invalid = parse_model_output(content)
    assert invalid == 1 and [c.statement for c in claims] == ["Use Postgres for storage"]


def test_control_characters_and_odd_whitespace_are_cleaned():
    claims, _ = parse_model_output(json.dumps({"claims": [claim(
        statement="Use\x00 Postgres\n\n  for\tstorage\x07", owner="  Riya\x00 ", topic="\x01")]}))
    c = claims[0]
    assert c.statement == "Use Postgres for storage" and c.owner == "Riya" and c.topic is None


def test_a_huge_claim_list_is_capped():
    many = [claim(statement=f"Decision number {i} about storage") for i in range(250)]
    claims, invalid = parse_model_output(json.dumps({"claims": many}))
    assert len(claims) == 200 and invalid == 50


@pytest.mark.parametrize("content", ['{"claims": "nope"}', '{"claims": null}', '"x"', "5", "null",
                                     '{"other": []}'])
def test_wrong_top_level_shapes_are_rejected(content):
    with pytest.raises(ValueError):
        parse_model_output(content)


def test_extractor_closes_only_a_client_it_created():
    import httpx
    from app.extract.llm import OpenAICompatibleExtractor
    mine = httpx.Client()
    OpenAICompatibleExtractor(base_url="http://x", api_key="k", model="m", client=mine).close()
    assert not mine.is_closed                      # caller-owned client is left alone
    own = OpenAICompatibleExtractor(base_url="http://x", api_key="k", model="m")
    with own:
        pass
    assert own._client.is_closed
    mine.close()
