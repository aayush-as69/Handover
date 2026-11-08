import os


def _normalise_db_url(url: str) -> str:
    # Hosts hand out "postgres://" or "postgresql://"; SQLAlchemy needs the driver named (psycopg 3).
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings:
    def __init__(self) -> None:
        self.database_url = _normalise_db_url(
            os.environ.get("DATABASE_URL", "sqlite:///./handover.db")
        )


settings = Settings()
