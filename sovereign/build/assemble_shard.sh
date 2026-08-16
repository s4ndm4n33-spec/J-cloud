#!/usr/bin/env bash
# =============================================================================
# J-cloud Sovereign Shard — Reproducible Release Assembly
#
# Assembles a relocatable, USB-ready shard from the current source tree.
# The artifact is written to sovereign/release/J-cloud-Sovereign/ and
# contains only what is required to run the shard — no secrets, no dev
# artifacts, no cloud credentials.
#
# Usage:
#   bash sovereign/build/assemble_shard.sh [output_dir]
#
# Exit codes:
#   0  artifact assembled and validated
#   1  source tree validation failed
#   2  frontend build failed
#   3  backend dependency installation failed
#   4  secret detected in source tree
#   5  artifact validation failed
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/sovereign/release}"
SHARD_NAME="J-cloud-Sovereign"
SHARD_DIR="$OUTPUT_DIR/$SHARD_NAME"
VERSION="${J_CLOUD_VERSION:-0.1.0}"

red()   { printf '\033[0;31m%s\033[0m\n' "$1"; }
green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
yellow(){ printf '\033[0;33m%s\033[0m\n' "$1"; }
info()  { printf '[assemble] %s\n' "$1"; }

# ---------------------------------------------------------------------------
# 1. Validate source tree
# ---------------------------------------------------------------------------
info "Validating source tree..."

for required in \
    backend/server.py backend/config.py backend/deps.py \
    backend/sqlite_store.py backend/llm_chain.py \
    backend/routes/auth.py backend/routes/projects.py \
    frontend/package.json launch/J-cloud.bat launch/STOP-J-cloud.bat; do
    if [[ ! -f "$REPO_ROOT/$required" ]]; then
        red "MISSING: $required"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 2. Secret audit — fail if known secret files exist in the tree
# ---------------------------------------------------------------------------
info "Auditing for secrets..."

SECRET_PATTERNS=(
    "backend/.keys_secret"
    ".env"
    "credentials.json"
    "*.pem"
    "*.key"
)

found_secret=0
for pattern in "${SECRET_PATTERNS[@]}"; do
    while IFS= read -r -d '' f; do
        # Allow .env.example (template, no real secrets)
        if [[ "$f" == *".env.example" ]]; then
            continue
        fi
        red "SECRET DETECTED: $f"
        found_secret=1
    done < <(find "$REPO_ROOT" -name "$pattern" -not -path "*/node_modules/*" -not -path "*/.git/*" -print0 2>/dev/null || true)
done

if [[ $found_secret -eq 1 ]]; then
    red "Refusing to assemble: secrets detected in source tree."
    exit 4
fi

# ---------------------------------------------------------------------------
# 3. Clean staging directory
# ---------------------------------------------------------------------------
info "Cleaning staging directory..."
rm -rf "$SHARD_DIR"
mkdir -p "$SHARD_DIR"

# ---------------------------------------------------------------------------
# 4. Assemble backend
# ---------------------------------------------------------------------------
info "Assembling backend..."

mkdir -p "$SHARD_DIR/backend"
# Copy backend Python source — exclude tests, __pycache__, .venv, .keys_secret
rsync -a --exclude='__pycache__/' --exclude='.venv/' --exclude='tests/' \
    --exclude='.keys_secret' --exclude='*.pyc' --exclude='.pytest_cache/' \
    "$REPO_ROOT/backend/" "$SHARD_DIR/backend/"

# Copy requirements.txt for reference (runtime install is a host concern)
cp "$REPO_ROOT/backend/requirements.txt" "$SHARD_DIR/backend/requirements.txt"

# ---------------------------------------------------------------------------
# 5. Build frontend production artifact
# ---------------------------------------------------------------------------
info "Building frontend production artifact..."

if [[ -d "$REPO_ROOT/frontend/node_modules" ]]; then
    (cd "$REPO_ROOT/frontend" && npm run build)
else
    yellow "frontend/node_modules not found — installing deps..."
    (cd "$REPO_ROOT/frontend" && npm install && npm run build)
fi

if [[ ! -d "$REPO_ROOT/frontend/build" ]]; then
    red "Frontend build failed — no build/ directory produced."
    exit 2
fi

mkdir -p "$SHARD_DIR/frontend"
cp -a "$REPO_ROOT/frontend/build" "$SHARD_DIR/frontend/build"
# Copy package.json for reference
cp "$REPO_ROOT/frontend/package.json" "$SHARD_DIR/frontend/package.json"

# ---------------------------------------------------------------------------
# 6. Assemble launch scripts
# ---------------------------------------------------------------------------
info "Assembling launch scripts..."
mkdir -p "$SHARD_DIR/launch"
cp "$REPO_ROOT/launch/J-cloud.bat" "$SHARD_DIR/launch/J-cloud.bat"
cp "$REPO_ROOT/launch/STOP-J-cloud.bat" "$SHARD_DIR/launch/STOP-J-cloud.bat"
if [[ -f "$REPO_ROOT/launch/serve-build.js" ]]; then
    cp "$REPO_ROOT/launch/serve-build.js" "$SHARD_DIR/launch/serve-build.js"
fi

# ---------------------------------------------------------------------------
# 7. Create data/workspace/log/config directories
# ---------------------------------------------------------------------------
info "Creating runtime directories..."
for d in data workspace logs config models manifests; do
    mkdir -p "$SHARD_DIR/$d"
done

# ---------------------------------------------------------------------------
# 8. Generate portable configuration
# ---------------------------------------------------------------------------
info "Generating portable configuration..."

cat > "$SHARD_DIR/config/sovereign.env" << 'SOVEREIGN_ENV'
# J-cloud Sovereign Shard — portable configuration
# This file is loaded by launch/J-cloud.bat on startup.
# Do NOT place API keys or secrets here. Use config/.env.local for
# operator-supplied secrets (generated on first boot).

J_CLOUD_PROFILE=portable
LOCAL_AUTH=1
LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1
LOCAL_LLM_MODEL=local-model
CORS_ORIGINS=http://127.0.0.1:3000
REACT_APP_BACKEND_URL=http://127.0.0.1:8001
REACT_APP_J_CLOUD_PROFILE=portable
BACKEND_VERSION=__SHARD_VERSION__
SOVEREIGN_ENV

# Substitute version
sed -i "s/__SHARD_VERSION__/$VERSION/" "$SHARD_DIR/config/sovereign.env"

# ---------------------------------------------------------------------------
# 9. Assemble sovereign documentation
# ---------------------------------------------------------------------------
info "Assembling documentation..."
cp "$REPO_ROOT/sovereign/README.md" "$SHARD_DIR/SOVEREIGN-README.md"
if [[ -f "$REPO_ROOT/sovereign/PORTABLE_SPEC.md" ]]; then
    cp "$REPO_ROOT/sovereign/PORTABLE_SPEC.md" "$SHARD_DIR/docs/PORTABLE_SPEC.md"
fi

# Write USB README
cat > "$SHARD_DIR/README-USB.md" << 'USB_README'
# J-cloud Sovereign Shard — USB Deployment

## Quick Start

1. Plug the USB / copy the folder to any location (C:\, D:\, E:\, USB:\).
2. Double-click `launch\J-cloud.bat`.
3. On first boot, use the "FIRST BOOT" tab to create your local operator.
4. On subsequent boots, use "LOGIN" with the same credentials.

## Requirements

- Windows 10 or later (64-bit)
- A portable Python runtime under `runtime\python\` (or system Python 3.11+)
- A portable Node runtime under `runtime\node\` (or system Node 18+)
- Git on PATH (for workspace Git features)
- Optional: a local OpenAI-compatible model server (Ollama, llama.cpp)

## Without bundled runtimes

If `runtime\python\` or `runtime\node\` are absent, the launcher will attempt
to use system-installed Python and Node. If those are also unavailable,
the shard will report the missing component and exit.

## Local LLM

The shard expects an OpenAI-compatible endpoint at `http://127.0.0.1:8080/v1`.
Configure the URL and model in `config\sovereign.env`.

If no model server is running, the shard will boot and report
`local_llm: unavailable` in the status endpoint. Core IDE, project, and
file features remain usable. J chat will not work until a model server is
available.

## Stopping

Double-click `launch\STOP-J-cloud.bat` to cleanly stop all shard processes.

## Offline Operation

Once assembled, the shard operates fully offline for:
- Authentication (local)
- Project CRUD
- File editing
- Local snapshots
- Local Git operations
- Chronicle and Five Masters evaluation

Cloud features (GitHub, Tavily, voice, R2, Resend, Modal) are disabled
by default and will report "Unavailable in Sovereign/Offline mode."
USB_README

# ---------------------------------------------------------------------------
# 10. Generate release manifest and checksums
# ---------------------------------------------------------------------------
info "Generating release manifest..."

python3 "$SCRIPT_DIR/generate_manifest.py" \
    --shard-dir "$SHARD_DIR" \
    --version "$VERSION" \
    --repo-root "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 11. Validate the artifact
# ---------------------------------------------------------------------------
info "Validating artifact..."

bash "$SCRIPT_DIR/validate_shard.sh" "$SHARD_DIR"
validate_result=$?

if [[ $validate_result -ne 0 ]]; then
    red "Artifact validation FAILED (exit $validate_result)."
    exit 5
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
green "============================================"
green " Sovereign Shard assembled successfully"
green "============================================"
info "Artifact: $SHARD_DIR"
info "Version:  $VERSION"
info "Manifest: $SHARD_DIR/manifests/manifest.json"
info "Checksums: $SHARD_DIR/manifests/SHA256SUMS.txt"
echo
echo "Next steps:"
echo "  1. Copy $SHARD_DIR to target media (USB, drive)"
echo "  2. Optionally place portable runtimes under runtime/"
echo "  3. Run launch\\J-cloud.bat on the target machine"
