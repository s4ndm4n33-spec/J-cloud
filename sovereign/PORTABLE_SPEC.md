# Portable Shard Specification

## 1. Runtime ownership

Every runtime dependency required for normal local execution is resolved relative to the shard root.

No executable may assume:

- a fixed drive letter;
- a user home directory;
- a system Python installation;
- a system Node installation;
- a globally installed package;
- a cloud-hosted API URL.

Use the shard root as the only deployment anchor and derive all runtime paths from it.

## 2. Process topology

```text
launch/J-cloud.bat
  ├── backend process : 127.0.0.1:8001
  ├── frontend process : 127.0.0.1:3000
  └── optional model process : 127.0.0.1:8080
```

The launcher owns child-process lifecycle and records PIDs under `data/run/` or equivalent runtime state.

## 3. Storage

The local profile uses one shard-local SQLite database and filesystem storage:

```text
data/jcloud.db
workspace/<project-id>/
logs/
```

Nothing required for operation may be written outside the shard root.

## 4. Configuration

Configuration precedence:

1. explicit process environment;
2. `config/.env.local`;
3. safe defaults.

Production/cloud configuration must never be copied into the portable profile.

Required local defaults:

```text
J_CLOUD_PROFILE=portable
J_CLOUD_ROOT=<resolved shard root>
J_CLOUD_DB=<root>/data/jcloud.db
WORKSPACE_ROOT=<root>/workspace
LOCAL_AUTH=1
LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1
CORS_ORIGINS=http://127.0.0.1:3000
```

## 5. Authentication

Portable mode must bypass the Emergent OAuth exchange entirely.

The local auth adapter creates an operator account on first run and stores only a salted password verifier in SQLite. Session tokens are generated locally and scoped to the shard database.

OAuth remains an optional cloud profile feature; it is not part of the portable boot path.

## 6. Inference

The portable inference contract is OpenAI-compatible HTTP:

```text
POST /v1/chat/completions
```

The adapter can point at llama.cpp, Ollama, vLLM, or another compatible local server. The application must not hard-code a model name; the selected model is local configuration.

## 7. Offline guarantee

After assembly, normal operation must succeed with network access disabled.

Offline verification must cover:

- login;
- IDE load;
- project creation;
- file CRUD;
- terminal access;
- Chronicle;
- Five Masters evaluation;
- J chat/refine through the local model;
- restart persistence.

Features that inherently require a network connection must report that fact explicitly rather than silently failing or attempting an external request.

## 8. Release assembly

A release builder creates a directory tree, verifies dependencies, copies portable runtimes and selected model artifacts, writes a generated configuration, runs smoke tests, and emits a checksum manifest.

The Git repository is the source tree. The USB release is a reproducible assembled artifact.

## 9. Acceptance criterion

A portable release is complete only when the release artifact can be copied to another supported Windows machine and boot without modifying the host's global development environment.
