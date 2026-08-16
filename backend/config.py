"""Runtime profile configuration for cloud and portable J-cloud."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).parent
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class RuntimeConfig:
    profile: str
    shard_root: Path
    db_path: Path
    workspace_root: Path
    local_auth: bool
    local_llm_base_url: str
    local_llm_model: str
    mongo_url: str | None
    db_name: str
    emergent_llm_key: str
    tavily_api_key: str
    owner_user_id: str
    override_password: str
    training_local_root: Path
    snapshot_root: Path
    enabled_cloud_adapters: frozenset[str]

    @property
    def portable(self) -> bool:
        return self.profile == "portable"


def _default_root() -> Path:
    return BACKEND_DIR.parent.resolve()


def _path_env(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else fallback.resolve()


def _enabled_cloud_adapters(portable: bool) -> frozenset[str]:
    if not portable:
        return frozenset({"github", "tavily", "voice", "r2", "resend", "modal", "openai", "anthropic", "gemini"})
    raw = os.environ.get("J_CLOUD_ENABLE_CLOUD_ADAPTERS", "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def load_config() -> RuntimeConfig:
    profile = os.environ.get("J_CLOUD_PROFILE", "cloud").strip().lower()
    shard_root = _path_env("J_CLOUD_ROOT", _default_root())
    portable = profile == "portable"
    db_path = _path_env("J_CLOUD_DB", shard_root / "data" / "jcloud.db")
    workspace_root = _path_env("WORKSPACE_ROOT", shard_root / "workspace")
    local_auth = portable or os.environ.get("LOCAL_AUTH", "").strip() == "1"
    local_llm_base_url = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1").strip()
    local_llm_model = os.environ.get("LOCAL_LLM_MODEL", "local-j").strip()
    training_local_root = _path_env("TRAINING_LOCAL_ROOT", shard_root / "data" / "training" / "exports")
    snapshot_root = _path_env("J_CLOUD_SNAPSHOT_ROOT", shard_root / "data" / "snapshots")
    enabled_cloud_adapters = _enabled_cloud_adapters(portable)

    if portable:
        mongo_url = None
        db_name = os.environ.get("DB_NAME", "jcloud_portable")
        emergent_llm_key = os.environ.get("EMERGENT_LLM_KEY", "")
        override_password = os.environ.get("OVERRIDE_PASSWORD", "portable-override-not-configured")
    else:
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        emergent_llm_key = os.environ["EMERGENT_LLM_KEY"]
        override_password = os.environ["OVERRIDE_PASSWORD"]

    return RuntimeConfig(
        profile=profile,
        shard_root=shard_root,
        db_path=db_path,
        workspace_root=workspace_root,
        local_auth=local_auth,
        local_llm_base_url=local_llm_base_url,
        local_llm_model=local_llm_model,
        mongo_url=mongo_url,
        db_name=db_name,
        emergent_llm_key=emergent_llm_key,
        tavily_api_key=(os.environ.get("TAVILY_API_KEY", "") if (not portable or "tavily" in enabled_cloud_adapters) else ""),
        owner_user_id=os.environ.get("OWNER_USER_ID", "").strip(),
        override_password=override_password,
        training_local_root=training_local_root,
        snapshot_root=snapshot_root,
        enabled_cloud_adapters=enabled_cloud_adapters,
    )


settings = load_config()
