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


class Settings:
    """Development (default) is forgiving. Production (APP_ENV=production) is strict."""

    def __init__(self, env=None) -> None:
        env = os.environ if env is None else env
        self.env = (env.get("APP_ENV") or "development").lower()
        self.database_url = _normalise_db_url(env.get("DATABASE_URL", "sqlite:///./handover.db"))
        self.secret_key = env.get("SECRET_KEY") or None
        self.demo_mode = (env.get("DEMO_MODE", "").lower() in ("1", "true", "yes", "on"))
        self.demo_password = env.get("DEMO_PASSWORD") or None
        cookie = env.get("COOKIE_SECURE")
        self.cookie_secure = (self.production if cookie in (None, "")
                              else cookie.lower() in ("1", "true", "yes", "on"))

    @property
    def production(self) -> bool:
        return self.env == "production"

    def validate(self) -> list[str]:
        """Raise ConfigError for unsafe production settings. Returns development warnings."""
        warnings: list[str] = []
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
