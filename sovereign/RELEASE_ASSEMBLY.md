# J-cloud USB Release Assembly

The repository is the source. The USB image is an assembled release artifact.

## Assembly stages

1. Clean checkout of the release commit.
2. Install/build frontend dependencies using a portable Node runtime.
3. Freeze Python dependencies into the portable Python environment.
4. Add the supported portable Python runtime.
5. Add the supported local model server runtime.
6. Add selected GGUF model files under `models/`.
7. Create `data/`, `workspace/`, `logs/`, and `config/`.
8. Generate local-only configuration; never copy production secrets.
9. Run backend import/startup smoke test.
10. Run frontend production build/startup smoke test.
11. Run local auth/project/file CRUD smoke tests.
12. Run local-model chat smoke test.
13. Disable network access and repeat the offline test suite.
14. Write SHA-256 checksums for the release contents.
15. Package the resulting tree as a ZIP suitable for copying to USB.

## Release artifact

```text
J-cloud-Sovereign-Shard-<version>/
├── backend/
├── frontend/build/
├── runtime/
│   ├── python/
│   ├── node/
│   └── model-server/
├── models/
├── data/
├── workspace/
├── logs/
├── config/
├── launch/
│   ├── J-cloud.bat
│   └── STOP-J-cloud.bat
├── CHECKSUMS.sha256
└── README-USB.md
```

## Model policy

Models are release assets, not source code. The release builder must record the model filename, quantization, size, source, and checksum in the manifest.

The shard must boot without a model only far enough to report `LOCAL_LLM_UNAVAILABLE`; it must never silently fall back to a cloud provider in portable mode.

## Host isolation

The release must not require administrator privileges, modify PATH, install system packages, write registry keys, create Windows services, or place dependencies in the user's profile.
