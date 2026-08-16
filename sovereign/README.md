# J-cloud — Sovereign Shard

J-cloud can run as a self-contained Sovereign Shard from removable storage.

The portable target is intentionally local-first:

- the shard owns its runtime, configuration, workspace, logs, and local data;
- no cloud database is required for the local profile;
- no system-wide Python or Node installation is required when the portable runtime bundle is present;
- the local LLM endpoint is configurable, with llama.cpp/Ollama-compatible OpenAI APIs supported;
- the USB is treated as the deployment boundary, not as a network dependency.

## Target layout

```text
J-cloud-shard/
├── backend/
├── frontend/
├── runtime/
│   ├── python/
│   ├── node/
│   └── model-server/
├── models/
├── data/
├── workspace/
├── logs/
├── config/
├── scripts/
└── launch/
```

`runtime/`, `models/`, `data/`, `workspace/`, and `logs/` are deployment assets and are not required to live in Git. A release builder assembles them into the final USB image.

## Sovereignty boundary

The portable shard must not silently depend on:

- MongoDB Atlas or another remote database;
- Emergent OAuth;
- Emergent universal LLM credentials;
- hosted frontend/backend URLs;
- machine-global package installs;
- machine-global configuration files.

Cloud integrations remain available as explicit optional adapters. They are not prerequisites for booting the local shard.

## Local profile

The local profile uses:

- SQLite for identity, sessions, project metadata, chat history, telemetry, and shard state;
- filesystem workspaces under `workspace/`;
- local authentication instead of OAuth;
- a local OpenAI-compatible inference endpoint;
- localhost-only backend binding by default.

The first implementation pass should preserve the existing cloud architecture rather than rewrite it. The portable adapter sits at the dependency boundary and supplies equivalent interfaces to the existing route/core code.

## USB deployment contract

A release is considered portable only when a clean Windows machine with no project dependencies installed can:

1. plug in the USB;
2. run `launch\\J-cloud.bat`;
3. start the local backend and frontend;
4. open the IDE in a browser;
5. create a local user without OAuth;
6. create/read/write a project;
7. invoke J against the configured local model;
8. restart and retain local state;
9. shut down cleanly without leaving processes behind.

Internet access may be used to download a model during an explicit setup operation. It must not be required for normal operation once the shard is assembled.

## Release assembly

The release builder (`sovereign/build/assemble_shard.sh`) assembles a
relocatable artifact from the source tree. It:

1. Validates the source tree has all required components.
2. Audits for secrets (`.keys_secret`, `.env`, `*.pem`, `*.key`) and refuses
   to assemble if any are found.
3. Builds the frontend production artifact.
4. Copies backend source, frontend build, launch scripts, and documentation.
5. Generates a machine-readable manifest (`manifests/manifest.json`) with
   SHA-256 checksums for every file (`manifests/SHA256SUMS.txt`).
6. Validates the artifact with `validate_shard.sh`.

```bash
bash sovereign/build/assemble_shard.sh
```

The artifact is written to `sovereign/release/J-cloud-Sovereign/`.

### Validation

```bash
bash sovereign/build/validate_shard.sh sovereign/release/J-cloud-Sovereign/
```

The validator checks:
- Directory structure completeness
- Backend and frontend artifact presence
- Launcher and configuration presence
- Bundled runtime components (warns if missing, never claims missing as bundled)
- Secret audit (fails if any secret is found)
- Manifest and checksum verification
- Path audit (fails on hard-coded drive letters)
- Cloud adapter mandatory check

### Smoke test

```bash
python3 sovereign/tests/smoke_test.py --shard-dir sovereign/release/J-cloud-Sovereign/
```

The smoke test boots the backend in portable mode on a test port and
verifies:
- Backend boots and responds
- Sovereign status endpoint reports portable profile, SQLite, local auth
- All cloud adapters are disabled
- Local auth init, login, and token-based /auth/me work
- Project creation and list work
- File write and read work
- GitHub and voice adapters return 503

## Security rule

Never place API keys, OAuth tokens, passwords, private certificates, or production `.env` files in the repository or release image. Local secrets belong in the operator-controlled `config/` directory and should be generated on first boot.

The release builder enforces this by auditing the source tree before
assembly. If any secret file is detected, the build is aborted with exit
code 4.
