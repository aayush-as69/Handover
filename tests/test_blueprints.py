"""The two Render blueprints must keep their promises: demo stays demo, production stays real."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def env_of(spec, groups):
    out = {}
    for item in spec.get("envVars", []):
        if "fromGroup" in item:
            out.update({e["key"]: e for e in groups[item["fromGroup"]]})
        else:
            out[item["key"]] = item
    return out


def test_demo_blueprint_is_the_free_demo_and_never_commits_the_password():
    bp = load("render.yaml")
    web = bp["services"][0]
    env = env_of(web, {})
    assert env["DEMO_MODE"]["value"] == "true" and env["DEMO_PASSWORD"].get("sync") is False
    assert "value" not in env["DEMO_PASSWORD"]


def test_production_blueprint_has_no_demo_and_a_worker_for_queue_mode():
    bp = load("render.production.yaml")
    groups = {g["name"]: g["envVars"] for g in bp["envVarGroups"]}
    web, worker = bp["services"]
    web_env, worker_env = env_of(web, groups), env_of(worker, groups)
    for env in (web_env, worker_env):
        assert env["DEMO_MODE"]["value"] == "false" and "DEMO_PASSWORD" not in env
        assert env["JOB_MODE"]["value"] == "queue" and env["APP_ENV"]["value"] == "production"
        assert env["COOKIE_SECURE"]["value"] == "true"
        assert env["DATABASE_URL"]["fromDatabase"]["name"] == bp["databases"][0]["name"]
    assert worker["type"] == "worker" and worker["startCommand"] == "python -m app.worker"
    assert web["startCommand"].startswith("uvicorn app.main:app") and web["healthCheckPath"] == "/ready"
    assert web_env["METRICS_TOKEN"].get("generateValue") is True
    assert bp["databases"][0]["plan"] not in ("free",) and web["plan"] != "free"
    # No secret value is written into the file.
    text = (ROOT / "render.production.yaml").read_text()
    assert "sync: false" in text and "sk-" not in text


def test_a_deployment_without_demo_has_a_way_to_create_the_first_admin(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, User
    from app.security import verify_password
    from app.users import change_password, create_user
    import pytest
    engine = create_engine(f"sqlite:///{tmp_path/'u.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        user = create_user(s, "Meera", "Meera Iyer", "admin", "a-long-private-pass")
        assert user.username == "meera" and verify_password("a-long-private-pass", user.password_hash)
        for bad in ("short", "changeme", "password1"):
            with pytest.raises(ValueError):
                create_user(s, "x", "X", "viewer", bad)
        with pytest.raises(ValueError, match="already exists"):
            create_user(s, "meera", "M", "viewer", "another-long-pass")
        before = user.session_version
        change_password(s, "meera", "a-different-long-pass")
        assert s.scalar(select(User.session_version)) == before + 1          # old cookies stop working
