from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, Response


def _purge_backend_modules() -> None:
    for name in list(sys.modules):
        if name in {"config", "capabilities", "deps", "llm_chain", "sqlite_store", "routes.auth", "core.workspace_sync"}:
            sys.modules.pop(name, None)


def _portable_env(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("J_CLOUD_PROFILE", "portable")
    monkeypatch.setenv("J_CLOUD_ROOT", str(root))
    monkeypatch.setenv("LOCAL_LLM_MODEL", "llama-test")
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)


def test_portable_config_resolves_paths_under_shard_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "drive-e" / "J-cloud")
    _purge_backend_modules()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    config = importlib.import_module("config")

    assert config.settings.portable is True
    assert config.settings.db_path == config.settings.shard_root / "data" / "jcloud.db"
    assert config.settings.workspace_root == config.settings.shard_root / "workspace"
    assert config.settings.local_auth is True
    assert config.settings.local_llm_base_url == "http://127.0.0.1:8080/v1"


def test_portable_mode_uses_sqlite_and_not_mongo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "drive-g" / "J-cloud")
    _purge_backend_modules()
    deps = importlib.import_module("deps")

    assert deps.MONGO_URL is None
    assert deps.client.__class__.__name__ == "SQLiteClient"
    assert deps.db.path == tmp_path / "drive-g" / "J-cloud" / "data" / "jcloud.db"


@pytest.mark.asyncio
async def test_sqlite_persistence_survives_reopen(tmp_path: Path) -> None:
    from sqlite_store import SQLiteClient

    db_path = tmp_path / "shard" / "data" / "jcloud.db"
    client = SQLiteClient(db_path)
    db = client["jcloud_portable"]
    await db.projects.insert_one({"project_id": "proj_1", "user_id": "user_1", "name": "Shard"})
    client.close()

    reopened = SQLiteClient(db_path)
    found = await reopened["jcloud_portable"].projects.find_one({"project_id": "proj_1"}, {"_id": 0})
    reopened.close()

    assert found == {"project_id": "proj_1", "user_id": "user_1", "name": "Shard"}


@pytest.mark.asyncio
async def test_local_auth_init_login_me_and_logout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    _purge_backend_modules()
    deps = importlib.import_module("deps")
    auth = importlib.import_module("routes.auth")

    payload = {"email": "operator@local.shard", "password": "correct horse battery staple"}
    initialized = await auth.auth_local_init(payload, Response())
    assert initialized["session_token"]
    assert "password_hash" not in initialized["user"]

    stored = await deps.db.users.find_one({"email": "operator@local.shard"}, {"_id": 0})
    assert stored["password_hash"] != payload["password"]

    logged_in = await auth.auth_local_login(payload, Response())
    user = await deps.get_current_user(None, session_token=logged_in["session_token"], authorization=None)
    assert user["email"] == "operator@local.shard"
    assert "password_hash" not in user

    await auth.auth_logout(Response(), session_token=logged_in["session_token"], authorization=None)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(None, session_token=logged_in["session_token"], authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_portable_auth_session_rejects_emergent_oauth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    _purge_backend_modules()
    auth = importlib.import_module("routes.auth")

    with pytest.raises(HTTPException) as exc:
        await auth.auth_session({"session_id": "external"}, Response())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_portable_llm_uses_local_openai_compatible_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:18080/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "portable-model")
    _purge_backend_modules()
    llm_chain = importlib.import_module("llm_chain")

    calls = []

    async def fake_single_call(api_key_or_cfg, provider, model, system, user_text, session_id):
        calls.append((api_key_or_cfg, provider, model, system, user_text, session_id))
        return "local response"

    monkeypatch.setattr(llm_chain, "_single_call", fake_single_call)
    reply, meta = await llm_chain.chain_call("user_1", "chat", "system", "hello", "sess", max_passes=1)

    assert reply == "local response"
    assert meta["step_used"] == {"source": "local", "provider": "ollama", "model": "user-default"}
    assert calls[0][0] == {"base_url": "http://127.0.0.1:18080/v1", "default_model": "portable-model"}


def test_portable_config_disables_cloud_adapters_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    monkeypatch.setenv("TAVILY_API_KEY", "not-used-in-portable")
    monkeypatch.setenv("RESEND_API_KEY", "not-used-in-portable")
    monkeypatch.setenv("MODAL_TOKEN_ID", "not-used-in-portable")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "not-used-in-portable")
    _purge_backend_modules()
    config = importlib.import_module("config")

    assert config.settings.enabled_cloud_adapters == frozenset()
    assert config.settings.tavily_api_key == ""


def test_portable_cloud_adapters_require_explicit_enable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    monkeypatch.setenv("J_CLOUD_ENABLE_CLOUD_ADAPTERS", "github,tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "explicitly-enabled")
    _purge_backend_modules()
    config = importlib.import_module("config")

    assert config.settings.enabled_cloud_adapters == frozenset({"github", "tavily"})
    assert config.settings.tavily_api_key == "explicitly-enabled"


@pytest.mark.asyncio
async def test_local_workspace_snapshot_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _portable_env(monkeypatch, tmp_path / "J-cloud")
    _purge_backend_modules()
    deps = importlib.import_module("deps")
    workspace_sync = importlib.import_module("core.workspace_sync")

    project_root = tmp_path / "J-cloud" / "workspace" / "local_user" / "proj_local"
    project_root.mkdir(parents=True)
    (project_root / "main.py").write_text("print('shard')\n", encoding="utf-8")
    await deps.db.projects.insert_one({"project_id": "proj_local", "user_id": "local_user"})

    snap = await workspace_sync.snapshot_project(
        deps.db, user_id="local_user", project_id="proj_local", src_dir=project_root, force=True
    )
    assert snap["ok"] is True
    assert (tmp_path / "J-cloud" / "data" / "snapshots" / "workspaces" / "local_user" / "proj_local" / "latest.tar.gz").exists()

    restored = tmp_path / "restore"
    result = await workspace_sync.restore_project(
        deps.db, user_id="local_user", project_id="proj_local", dest_dir=restored
    )
    assert result["ok"] is True
    assert (restored / "main.py").read_text(encoding="utf-8") == "print('shard')\n"
