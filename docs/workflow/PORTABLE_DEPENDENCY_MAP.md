# Portable dependency map

This map records the sovereign-shard dependency boundary as of the optional
cloud-capability isolation pass. The cloud deployment remains valid. Portable
mode must boot and keep the core IDE/J workflow available without silently
initializing cloud infrastructure.

## Runtime profile

`J_CLOUD_PROFILE=portable` selects the shard-local substrate.
`J_CLOUD_ROOT` is the root anchor; all portable runtime-owned paths derive
from it:

- `data/` via `J_CLOUD_DB`, default `<root>/data/jcloud.db`
- `workspace/` via `WORKSPACE_ROOT`, default `<root>/workspace`
- `data/snapshots/` via `J_CLOUD_SNAPSHOT_ROOT`
- `data/training/exports/` via `TRAINING_LOCAL_ROOT`
- `models/`, `logs/`, `config/`, and `runtime/` are reserved portable roots
  for the release assembly layer

Portable cloud adapters are disabled by default. They must be explicitly
listed in `J_CLOUD_ENABLE_CLOUD_ADAPTERS`, for example:

```text
J_CLOUD_ENABLE_CLOUD_ADAPTERS=github,tavily
```

Cloud profile keeps the existing environment contract:

- `MONGO_URL`
- `DB_NAME`
- `EMERGENT_LLM_KEY`
- `OVERRIDE_PASSWORD`

## Classification

| Surface | Classification | Portable behavior |
| --- | --- | --- |
| Local filesystem project CRUD | CORE LOCAL | Uses `<root>/workspace`; no network required. |
| SQLite persistence | CORE LOCAL | Uses `<root>/data/jcloud.db`; Mongo is not initialized in portable mode. |
| Local auth/session | CORE LOCAL | `/auth/local/init`, `/auth/local/login`, `/auth/me`, and logout operate locally. |
| Local LLM endpoint | CORE LOCAL | `llm_chain` forces `LOCAL_LLM_BASE_URL` + `LOCAL_LLM_MODEL`. |
| Five Masters / governance scan | CORE LOCAL | Local Python code paths; no cloud dependency for static checks. |
| Chronicle | CORE LOCAL | Persists through the selected DB and workspace files. |
| Local Git status/log/commit | OPTIONAL LOCAL | Uses workspace Git CLI; GitHub is not required. |
| Local snapshots | CORE LOCAL | Portable snapshots write tarballs under `<root>/data/snapshots`. |
| GitHub API | OPTIONAL CLOUD | Disabled in portable mode unless `github` adapter is explicitly enabled. |
| Tavily web search | OPTIONAL CLOUD | Shared Tavily key is ignored in portable mode unless `tavily` is explicitly enabled. |
| Voice STT/TTS | OPTIONAL CLOUD | Routes lazily import speech SDKs and return unavailable unless `voice` is enabled. |
| R2 snapshots | OPTIONAL CLOUD | Cloud profile unchanged; portable mode uses local snapshots unless `r2` is enabled. |
| Resend email | OPTIONAL CLOUD | Email reports disabled in portable mode unless `resend` is enabled. |
| Modal training | OPTIONAL CLOUD | Training dispatch is unavailable in portable mode unless `modal` is enabled. |
| Hosted OAuth | MANDATORY CLOUD for cloud auth only | `/auth/session` is disabled in portable mode. |
| Hosted frontend/backend URLs | UNRESOLVED | Portable launcher sets local React/backend env; production docs still contain hosted URLs. |
| Bundled Python/Node/runtime | MANDATORY HOST DEPENDENCY until assembled | Launch script expects `runtime/python` and `runtime/node` inside shard root. |

## Startup import audit

Portable startup must not import optional cloud SDKs merely by importing the
FastAPI app:

- Motor is imported only on the cloud DB path.
- `emergentintegrations` speech classes are imported only inside voice calls.
- Boto3/botocore are imported only when R2 operations are actually used.
- Modal is imported only inside Modal dispatch/cancel paths.
- Resend import remains guarded and email sends are capability-gated.

## Remaining blockers before true USB/offline release

- Bundle Python, Node, backend packages, frontend packages, and Git under
  `<root>/runtime` or provide a verified assembly process.
- Build a first-run portable frontend flow into the release artifact rather
  than relying on dev-server environment injection alone.
- Provide local replacements or explicit disabled UI states for Tavily,
  GitHub, Resend, Modal, and voice.
- Relocate key-vault material from `backend/.keys_secret` to shard-local
  `config/` or `data/`.
- Verify full FastAPI startup in a dependency-complete portable environment.
- Run browser/E2E verification for first boot, login, IDE open, project CRUD,
  local snapshot, restart, and local LLM response.
