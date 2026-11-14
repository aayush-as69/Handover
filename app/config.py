import os


def _normalise_db_url(url: str) -> str:
    # Hosts hand out "postgres://" or "postgresql://"; SQLAlchemy needs the driver named (psycopg 3).
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class ConfigError(RuntimeError):
    """The server is configured unsafely for its environment. It refuses to start."""


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None or raw == "" else raw.lower() in ("1", "true", "yes", "on")


WEAK_PASSWORDS = {"password", "password1", "12345678", "123456789", "demo", "demo1234", "changeme",
                  "letmein123", "qwertyuiop"}


def _flag_in(env, name: str, default: bool) -> bool:
    raw = env.get(name)
    return default if raw is None or raw == "" else raw.lower() in ("1", "true", "yes", "on")


class Settings:
    """Development (default) is forgiving. Production (APP_ENV=production) is strict."""

    def __init__(self, env=None) -> None:
        env = os.environ if env is None else env
        self.env = (env.get("APP_ENV") or "development").lower()
        self.database_url = _normalise_db_url(env.get("DATABASE_URL", "sqlite:///./handover.db"))
        self.secret_key = env.get("SECRET_KEY") or None
        self.demo_mode = (env.get("DEMO_MODE", "").lower() in ("1", "true", "yes", "on"))
        self.demo_password = env.get("DEMO_PASSWORD") or None
        self.edge_shared_secret = env.get("EDGE_SHARED_SECRET") or None
        cookie = env.get("COOKIE_SECURE")
        self.rate_limit_per_min = int(env.get("RATE_LIMIT_PER_MIN") or 300)        # 0 turns it off
        self.job_mode = (env.get("JOB_MODE") or "thread").lower()      # thread | queue
        self.metrics_token = env.get("METRICS_TOKEN") or None
        self.login_rate_per_min = int(env.get("LOGIN_RATE_PER_MIN") or 30)
        self.migrate_on_startup = _flag_in(env, "MIGRATE_ON_STARTUP", True)
        proxy = env.get("TRUST_PROXY")
        self.trust_proxy = (self.production if proxy in (None, "") else proxy.lower() in ("1", "true", "yes", "on"))
        self.cookie_secure = (self.production if cookie in (None, "")
                              else cookie.lower() in ("1", "true", "yes", "on"))

    @property
    def production(self) -> bool:
        return self.env == "production"

    def validate(self) -> list[str]:
        """Raise ConfigError for unsafe production settings. Returns development warnings."""
        warnings: list[str] = []
        if self.job_mode not in ("thread", "queue"):
            raise ConfigError(f"JOB_MODE must be thread or queue, not {self.job_mode!r}")
        if self.env not in ("development", "production", "test"):
            raise ConfigError(f"APP_ENV must be development or production, not {self.env!r}")
        if self.production:
            problems = []
            if not self.secret_key or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to at least 32 random characters")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE cannot be off in production")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must point at PostgreSQL, not SQLite")
            if self.edge_shared_secret and len(self.edge_shared_secret) < 32:
                problems.append("EDGE_SHARED_SECRET must be at least 32 characters when configured")
            if self.demo_mode:
                pw = self.demo_password or ""
                if len(pw) < 10 or pw.lower() in WEAK_PASSWORDS:
                    problems.append("DEMO_PASSWORD must be at least 10 characters and not a common password")
            if problems:
                raise ConfigError("Refusing to start in production: " + "; ".join(problems) + ".")
        else:
            if not self.secret_key:
                warnings.append("SECRET_KEY is not set: sessions end whenever the server restarts.")
            if self.demo_mode and not self.demo_password:
                warnings.append("DEMO_MODE needs DEMO_PASSWORD; demo users will not be able to log in.")
        return warnings


settings = Settings()
