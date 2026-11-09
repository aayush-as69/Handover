import pytest

from app.ingest.redact import redact

# Fake values, built to match the formats; none is a real credential.
MASKED = [
    ("DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
    ('{"password": "s3cr3tvalue"}', "s3cr3tvalue"),
    ("client_secret: abcdefghij", "abcdefghij"),
    ("STRIPE_API_KEY = zz9988776655", "zz9988776655"),
    ("postgres://admin:pw12345@db.example.com:5432/app", "pw12345"),
    ("amqp://svc:rabbitpass@mq.internal/vhost", "rabbitpass"),
    ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345", "abcdefghijklmnopqrstuvwxyz012345"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==", "dXNlcjpwYXNzd29yZDEyMw"),
    ("key sk-ant-api03-abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
    ("key sk-proj-abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx"),
    ("AIza" + "A" * 35, "A" * 35),
    ("ASIA" + "B" * 16, "B" * 16),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "eyJzdWIiOiIxMjM0NTY3ODkwIn0"),
    ("https://hooks.slack.com/services/T0000000/B0000000/abcdefghijklmnop", "abcdefghijklmnop"),
    ("SG." + "a" * 22 + "." + "b" * 22, "a" * 22),
    ("npm_" + "c" * 36, "c" * 36),
    ("github_pat_" + "d" * 30, "d" * 30),
    ("sk_live_" + "e" * 20, "e" * 20),
    ("-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc123\n-----END PGP PRIVATE KEY BLOCK-----", "abc123"),
]


@pytest.mark.parametrize("text,secret", MASKED)
def test_secret_is_masked(text, secret):
    r = redact(f"note: {text} end")
    assert r.redacted and secret not in r.text


HARMLESS = [
    "The password reset flow works",
    "token expiry: 30m",
    "Author: Meera Iyer wrote the doc",
    "see https://github.com/org/repo/pull/12",
    "postgres://db.example.com:5432/app",          # no credentials in it
    "Authentication is handled by the login page",
    "We rotate the API key every quarter",
    "Basic idea: keep it simple",
]


@pytest.mark.parametrize("text", HARMLESS)
def test_ordinary_text_is_left_alone(text):
    r = redact(text)
    assert not r.redacted and r.text == text


# ------------------------------------------------ unlabelled random strings

RANDOM = [
    "9fK2xQ7pLm4Zr8TvB3nYc6WdHs1JaUe0",                 # base62 token
    "dGhpcyBpcyBhIHNlY3JldCB2YWx1ZSAxMjM0NTY3",         # base64 blob
    "Zm9vYmFyMTIzNDU2Nzg5MGFiY2RlZkdISUpL",
    "a8Fk3_Lm9Qz-X2vB7nYc6WdHs1JaUe0pR",                # url-safe token
]


@pytest.mark.parametrize("token", RANDOM)
def test_unlabelled_random_token_is_masked(token):
    r = redact(f"the deploy key was {token} for staging")
    assert token not in r.text and "high_entropy" in r.kinds


NOT_SECRETS = [
    "commit 3f786850e387550fdab836ed7e6dc881de23001b merged",        # git sha1
    "sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "request 550e8400-e29b-41d4-a716-446655440000 failed",           # uuid
    "see getUserAccountPermissionsHandler for details",              # identifier, no digits
    "branch feature-add-login-rate-limiting-to-the-api",             # slug
    "file docs/PRODUCTION_READINESS_REVIEW_NOTES.md",
    "short token abc123XYZ is fine",                                 # under 24 characters
    "the quick brown fox jumps over the lazy dog 1234567890",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",                      # long but low entropy
]


@pytest.mark.parametrize("text", NOT_SECRETS)
def test_hashes_ids_and_ordinary_text_are_not_mistaken_for_secrets(text):
    r = redact(text)
    assert not r.redacted and r.text == text



def test_paths_and_dated_file_names_are_not_masked():
    for text in ("notes/2026-10-03_sprint_review", "notes/2026-09-19_architecture_decisions_v2"):
        assert redact(text).text == text
