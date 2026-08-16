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

## Security rule

Never place API keys, OAuth tokens, passwords, private certificates, or production `.env` files in the repository or release image. Local secrets belong in the operator-controlled `config/` directory and should be generated on first boot.
