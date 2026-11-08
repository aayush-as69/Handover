import os


def _normalise_db_url(url: str) -> str:
    # Some hosts hand out "postgres://", which SQLAlchemy does not accept.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


class Settings:
    def __init__(self) -> None:
        self.database_url = _normalise_db_url(
            os.environ.get("DATABASE_URL", "sqlite:///./handover.db")
        )


settings = Settings()
