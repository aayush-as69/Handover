"""Login throttling: per account and address, per account overall, per address (accounts tried
and raw volume), plus a general request limiter. All stored in the database except the limiter."""
from app.config import Settings
from app.security import (MAX_FAILURES, MAX_FAILURES_PER_IP, MAX_FAILURES_PER_USER,
                          MAX_USERNAMES_PER_IP, RateLimiter)
from tests.test_web import PW, client, env, token  # noqa: F401


def attempt(c, user, password="wrong", ip="1.1.1.1"):
    return c.post("/login", data={"username": user, "password": password, "csrf": token(c)},
                  headers={"x-forwarded-for": ip}).status_code


def proxied(app):
    app.state.cfg.trust_proxy = True
    for limiter in app.state.limiters:          # these tests are about lockout, not request rate
        limiter.limit = 0
    return client(app)


def test_one_address_guessing_one_account_is_blocked_but_other_addresses_are_not(env):
    app, _ = env
    c = proxied(app)
    for _ in range(MAX_FAILURES):
        assert attempt(c, "meera", ip="5.5.5.5") == 401
    assert attempt(c, "meera", PW, ip="5.5.5.5") == 429       # that address, that account
    assert attempt(c, "meera", PW, ip="6.6.6.6") == 303       # the real owner elsewhere is fine


def test_an_office_with_a_few_typos_is_not_locked_out(env):
    app, _ = env
    c = proxied(app)
    for user in ("meera", "kabir", "nobody1", "nobody2", "nobody3"):
        assert attempt(c, user, ip="7.7.7.7") == 401           # one typo each from one address
    assert attempt(c, "meera", PW, ip="7.7.7.7") == 303


def test_one_address_trying_many_accounts_is_blocked(env):
    app, _ = env
    c = proxied(app)
    for i in range(MAX_USERNAMES_PER_IP):
        assert attempt(c, f"nobody{i}", ip="8.8.8.8") == 401
    assert attempt(c, "meera", PW, ip="8.8.8.8") == 429
    assert attempt(c, "meera", PW, ip="9.9.9.9") == 303


def test_many_addresses_guessing_one_account_are_blocked_overall(env):
    app, _ = env
    c = proxied(app)
    for i in range(MAX_FAILURES_PER_USER):
        assert attempt(c, "meera", ip=f"10.0.0.{i}") == 401    # each address stays under its limit
    assert attempt(c, "meera", PW, ip="10.0.9.9") == 429


def test_raw_volume_from_one_address_is_capped(env):
    app, _ = env
    c = proxied(app)
    from app.security import record_login_failure_for
    with env[1]() as s:
        for _ in range(MAX_FAILURES_PER_IP):
            record_login_failure_for(s, "meera", "3.3.3.3")      # also trips the pair limit
    assert attempt(c, "kabir", PW, ip="3.3.3.3") == 429


def test_success_clears_the_persons_counters_not_the_addresses_volume(env):
    app, _ = env
    c = proxied(app)
    for _ in range(MAX_FAILURES - 1):
        attempt(c, "meera", ip="4.4.4.4")
    assert attempt(c, "meera", PW, ip="4.4.4.4") == 303
    for _ in range(MAX_FAILURES - 1):                           # the count started again
        attempt(c, "meera", ip="4.4.4.4")
    assert attempt(c, "meera", PW, ip="4.4.4.4") == 303


def test_forged_forwarded_for_prefix_cannot_dodge_the_limit(env):
    app, _ = env
    c = proxied(app)
    for i in range(MAX_FAILURES):
        attempt(c, "meera", ip=f"1.2.3.{i}, 7.7.7.7")          # proxy appended the real address
    assert attempt(c, "meera", PW, ip="6.6.6.6, 7.7.7.7") == 429


def test_forwarded_header_is_ignored_when_no_proxy_is_trusted(env):
    app, _ = env
    app.state.cfg.trust_proxy = False
    for limiter in app.state.limiters:
        limiter.limit = 0
    c = client(app)
    for i in range(MAX_FAILURES):
        attempt(c, "meera", ip=f"1.2.3.{i}")                   # each claims a different address
    assert attempt(c, "meera", PW, ip="5.5.5.5") == 429


def test_proxy_trust_and_rate_settings_follow_the_environment():
    assert Settings({"APP_ENV": "production"}).trust_proxy is True
    assert Settings({}).trust_proxy is False
    assert Settings({"RATE_LIMIT_PER_MIN": "10", "LOGIN_RATE_PER_MIN": "2"}).rate_limit_per_min == 10


# ------------------------------------------------------------ request rate limiter


def test_limiter_allows_up_to_the_limit_then_recovers():
    now = [0.0]
    lim = RateLimiter(3, 60, clock=lambda: now[0])
    assert [lim.allow("a") for _ in range(4)] == [True, True, True, False]
    assert lim.allow("b")                                       # other addresses unaffected
    now[0] = 61
    assert lim.allow("a")
    assert RateLimiter(0).allow("x")                            # 0 switches it off


def test_server_answers_429_with_retry_after_when_the_rate_is_exceeded(env):
    app, _ = env
    general, _logins = app.state.limiters
    general.limit = 5
    c = client(app)
    codes = [c.get("/login").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
    r = c.get("/login")
    assert r.headers["retry-after"] == "60"
    assert c.get("/health").status_code == 200                  # health checks are never limited


def test_login_posts_have_their_own_tighter_limit(env):
    app, _ = env
    _general, logins = app.state.limiters
    logins.limit = 3
    c = client(app)
    codes = [attempt(c, "nobody", ip="2.2.2.2") for _ in range(5)]
    assert codes[:3] == [401] * 3 and set(codes[3:]) == {429}
