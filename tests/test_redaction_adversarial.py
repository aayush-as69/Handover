"""Awkward ways credentials show up in real notes, chats and configs. Each fake secret must
vanish; ordinary prose containing the same words must survive."""
import pytest

from app.ingest.redact import redact

LEAKS_IF_NOT_MASKED = [
    ("db:\n  password: Tr0ub4dor&3xyz\n", "Tr0ub4dor&3xyz"),                          # yaml
    ("export STRIPE_SECRET=whsec_abc123def456ghi", "abc123def456ghi"),               # env export
    ("curl -H 'X-Api-Key: 8d969eef6ecad3c29a3a629280e686cf0c3f5d5a' https://x", "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a"),
    ("curl -u admin:S3cretPass99 https://api.example.com", "S3cretPass99"),
    ("curl --user=admin:S3cretPass99 https://api.example.com", "S3cretPass99"),
    ("password = 'my secret phrase here'", "secret phrase"),                          # spaces, quoted
    ('{\n  "client_secret":\n    "abcd1234efgh5678"\n}', "abcd1234efgh5678"),        # split lines
    ("PASSWORD=HunterHunter99", "HunterHunter99"),                                    # upper case
    ("api key is: ZXhhbXBsZWtleTEyMzQ1Njc4", "ZXhhbXBsZWtleTEyMzQ1Njc4"),
    ("https://x.com/cb?access_token=abc123def456ghi789&x=1", "abc123def456ghi789"),   # query string
    ("hey the password is Hunter2Hunter2 ok", "Hunter2Hunter2"),                      # said in chat
    ("temp password: Winter2026!", "Winter2026!"),
    ("mongodb+srv://user:p%40ss1234@cluster0.mongodb.net/db", "p%40ss1234"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n-----END OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1rZXk"),
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
    ("AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;", "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50u"),
    ("pwd:Zx9!qwerty", "Zx9!qwerty"),
    ("token = ghs_abcdefghijklmnopqrstuvwxyz0123456789", "ghs_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("password:\n  Hunter2Hunter2", "Hunter2Hunter2"),
    ("secret: c2VjcmV0LXZhbHVl", "c2VjcmV0LXZhbHVl"),
    ("password=abc12", "abc12"),                                                      # short password
    ("pass​word=Hunter2Hunter2", "Hunter2Hunter2"),                              # zero-width space
    ("ｐａｓｓｗｏｒｄ=Hunter2Hunter2", "Hunter2Hunter2"),                             # full-width letters
    ("PIN is 4821x9", "4821x9"),
]


@pytest.mark.parametrize("text,secret", LEAKS_IF_NOT_MASKED)
def test_disguised_or_awkward_credentials_are_masked(text, secret):
    r = redact(text)
    assert secret not in r.text, r.text
    assert r.redacted


PROSE = [
    "The password is required for every account.",
    "We store the password hash, never the password itself.",
    "The token is valid for 30 minutes.",
    "secret management is a roadmap item",
    "password: none",
    "password=null",
    "Please reset your password later today",
    "the API key is rotated quarterly",
    "Use a passphrase manager.",
    "Ask Meera about the secret santa plan",
]


@pytest.mark.parametrize("text", PROSE)
def test_ordinary_sentences_about_secrets_are_left_alone(text):
    r = redact(text)
    assert r.text == text and not r.redacted


def test_masking_is_idempotent_and_keeps_surrounding_text():
    once = redact("deploy with password=Hunter2Hunter2 then restart")
    assert once.text == "deploy with password=[REDACTED:secret] then restart"
    assert redact(once.text).text == once.text


def test_known_gap_is_documented_a_secret_split_by_spaces_in_prose_is_not_caught():
    """Honest limit: nothing links words spread through a sentence. Kept as a failing-by-design
    marker so the README's limitation stays true."""
    assert "H u n t e r 2" in redact("the pass word is H u n t e r 2 spelled out").text
