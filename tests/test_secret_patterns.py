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
