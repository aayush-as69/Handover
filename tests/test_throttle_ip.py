"""Login throttling by username AND by client address (both kept in the database)."""
from app.config import Settings
from app.main import create_app
from app.security import MAX_FAILURES_PER_IP
from tests.test_web import PW, client, env, token  # noqa: F401


def attempt(c, user, password="wrong", ip=None):
    headers = {"x-forwarded-for": ip} if ip else {}
    return c.post("/login", data={"username": user, "password": password, "csrf": token(c)},
                  headers=headers).status_code


def test_one_address_trying_many_usernames_gets_blocked(env):
    app, _ = env
    c = client(app)
    codes = [attempt(c, f"nobody{i}") for i in range(MAX_FAILURES_PER_IP)]
    assert set(codes) == {401}
    assert attempt(c, "meera", PW) == 429          # even a correct password from that address


def test_other_addresses_are_unaffected(env):
    app, _ = env
    app.state.cfg.trust_proxy = True
    c = client(app)
    for i in range(MAX_FAILURES_PER_IP):
        attempt(c, f"nobody{i}", ip="9.9.9.9")
    assert attempt(c, "meera", PW, ip="9.9.9.9") == 429
    assert attempt(c, "meera", PW, ip="8.8.8.8") == 303


def test_a_successful_login_does_not_reset_the_address_count(env):
    app, _ = env
    c = client(app)
    for i in range(MAX_FAILURES_PER_IP - 1):
        attempt(c, f"nobody{i}")
    assert attempt(c, "meera", PW) == 303          # success...
    assert attempt(c, "nobody-x") == 401           # ...the 20th failure still counts
    assert attempt(c, "kabir", PW) == 429


def test_forged_forwarded_for_prefix_cannot_dodge_the_limit(env):
    app, _ = env
    app.state.cfg.trust_proxy = True
    c = client(app)
    # The proxy appends the real address last; a forged first entry changes nothing.
    for i in range(MAX_FAILURES_PER_IP):
        attempt(c, f"nobody{i}", ip=f"1.2.3.{i}, 7.7.7.7")
    assert attempt(c, "meera", PW, ip="6.6.6.6, 7.7.7.7") == 429


def test_forwarded_header_is_ignored_when_no_proxy_is_trusted(env):
    app, _ = env
    app.state.cfg.trust_proxy = False
    c = client(app)
    for i in range(MAX_FAILURES_PER_IP):
        attempt(c, f"nobody{i}", ip=f"1.2.3.{i}")  # each claims a different address
    assert attempt(c, "meera", PW, ip="5.5.5.5") == 429


def test_proxy_trust_defaults_follow_the_environment():
    assert Settings({"APP_ENV": "production"}).trust_proxy is True
    assert Settings({}).trust_proxy is False
    assert Settings({"TRUST_PROXY": "true"}).trust_proxy is True
