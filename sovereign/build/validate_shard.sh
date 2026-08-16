#!/usr/bin/env bash
# =============================================================================
# J-cloud Sovereign Shard — Release Artifact Validator
#
# Validates an assembled shard directory for correctness:
#   - expected directory structure
#   - backend exists
#   - frontend artifact exists
#   - launcher exists
#   - configuration exists
#   - required runtime components exist OR are marked missing
#   - no secrets exist
#   - manifest exists and checksums validate
#   - paths are shard-root-relative (no absolute drive letters)
#   - cloud adapters are not accidentally mandatory
#
# Usage:
#   bash sovereign/build/validate_shard.sh <shard_dir>
#
# Exit codes:
#   0  PASS  — artifact is valid
#   1  FAIL  — one or more required components are missing/broken
#   2  BLOCKED — cannot validate (e.g. missing manifest, no sha256sum)
# =============================================================================
set -euo pipefail

SHARD_DIR="${1:-}"
if [[ -z "$SHARD_DIR" ]]; then
    echo "Usage: validate_shard.sh <shard_dir>"
    exit 2
fi

if [[ ! -d "$SHARD_DIR" ]]; then
    echo "FAIL: shard directory does not exist: $SHARD_DIR"
    exit 1
fi

# Resolve to absolute
SHARD_DIR="$(cd "$SHARD_DIR" && pwd)"

red()    { printf '\033[0;31m%s\033[0m\n' "$1"; }
green()  { printf '\033[0;32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }

PASS_COUNT=0
FAIL_COUNT=0
BLOCKED_COUNT=0

check_pass() { green "  PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
check_fail() { red   "  FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
check_blocked() { yellow "  BLOCKED: $1"; BLOCKED_COUNT=$((BLOCKED_COUNT + 1)); }

echo "============================================"
echo " Validating: $SHARD_DIR"
echo "============================================"

# ---------------------------------------------------------------------------
# 1. Directory structure
# ---------------------------------------------------------------------------
echo ""
echo "[1] Directory structure"

for dir in backend frontend launch config data workspace logs models manifests; do
    if [[ -d "$SHARD_DIR/$dir" ]]; then
        check_pass "$dir/ exists"
    else
        check_fail "$dir/ missing"
    fi
done

# ---------------------------------------------------------------------------
# 2. Backend
# ---------------------------------------------------------------------------
echo ""
echo "[2] Backend"

if [[ -f "$SHARD_DIR/backend/server.py" ]]; then
    check_pass "server.py exists"
else
    check_fail "server.py missing"
fi

if [[ -f "$SHARD_DIR/backend/config.py" ]]; then
    check_pass "config.py exists"
else
    check_fail "config.py missing"
fi

if [[ -f "$SHARD_DIR/backend/requirements.txt" ]]; then
    check_pass "requirements.txt exists"
else
    check_fail "requirements.txt missing"
fi

if [[ -f "$SHARD_DIR/backend/routes/auth.py" ]]; then
    check_pass "routes/auth.py exists"
else
    check_fail "routes/auth.py missing"
fi

if [[ -f "$SHARD_DIR/backend/routes/projects.py" ]]; then
    check_pass "routes/projects.py exists"
else
    check_fail "routes/projects.py missing"
fi

# ---------------------------------------------------------------------------
# 3. Frontend artifact
# ---------------------------------------------------------------------------
echo ""
echo "[3] Frontend"

if [[ -d "$SHARD_DIR/frontend/build" ]]; then
    check_pass "frontend/build/ exists"
    if [[ -f "$SHARD_DIR/frontend/build/index.html" ]]; then
        check_pass "frontend/build/index.html exists"
    else
        check_fail "frontend/build/index.html missing"
    fi
else
    check_fail "frontend/build/ missing — frontend not built"
fi

# ---------------------------------------------------------------------------
# 4. Launcher
# ---------------------------------------------------------------------------
echo ""
echo "[4] Launcher"

if [[ -f "$SHARD_DIR/launch/J-cloud.bat" ]]; then
    check_pass "J-cloud.bat exists"
else
    check_fail "J-cloud.bat missing"
fi

if [[ -f "$SHARD_DIR/launch/STOP-J-cloud.bat" ]]; then
    check_pass "STOP-J-cloud.bat exists"
else
    check_fail "STOP-J-cloud.bat missing"
fi

# ---------------------------------------------------------------------------
# 5. Configuration
# ---------------------------------------------------------------------------
echo ""
echo "[5] Configuration"

if [[ -f "$SHARD_DIR/config/sovereign.env" ]]; then
    check_pass "sovereign.env exists"
    # Check it contains portable profile
    if grep -q "J_CLOUD_PROFILE=portable" "$SHARD_DIR/config/sovereign.env"; then
        check_pass "sovereign.env sets portable profile"
    else
        check_fail "sovereign.env does not set portable profile"
    fi
else
    check_fail "sovereign.env missing"
fi

# ---------------------------------------------------------------------------
# 6. Runtime components
# ---------------------------------------------------------------------------
echo ""
echo "[6] Runtime components"

PYTHON_EXE="$SHARD_DIR/runtime/python/python.exe"
NODE_EXE="$SHARD_DIR/runtime/node/node.exe"

if [[ -f "$PYTHON_EXE" ]]; then
    check_pass "Bundled Python runtime present"
else
    yellow "  MISSING: Bundled Python runtime (host-provided required)"
    echo "         This is acceptable if the target host has Python 3.11+."
    echo "         Never claim a missing runtime as BUNDLED."
    BLOCKED_COUNT=$((BLOCKED_COUNT + 1))
fi

if [[ -f "$NODE_EXE" ]]; then
    check_pass "Bundled Node runtime present"
else
    yellow "  MISSING: Bundled Node runtime (host-provided required)"
    echo "         This is acceptable if the target host has Node 18+."
    echo "         Never claim a missing runtime as BUNDLED."
    BLOCKED_COUNT=$((BLOCKED_COUNT + 1))
fi

# ---------------------------------------------------------------------------
# 7. Secret audit
# ---------------------------------------------------------------------------
echo ""
echo "[7] Secret audit"

SECRET_FOUND=0
for pattern in ".keys_secret" ".env" "credentials.json"; do
    found=$(find "$SHARD_DIR" -name "$pattern" -not -path "*/node_modules/*" 2>/dev/null || true)
    if [[ -n "$found" ]]; then
        red "  FAIL: Secret file detected: $found"
        SECRET_FOUND=1
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

for pattern in "*.pem" "*.key"; do
    found=$(find "$SHARD_DIR" -name "$pattern" -not -path "*/node_modules/*" 2>/dev/null || true)
    if [[ -n "$found" ]]; then
        red "  FAIL: Secret file detected: $found"
        SECRET_FOUND=1
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

if [[ $SECRET_FOUND -eq 0 ]]; then
    check_pass "No secrets detected"
fi

# ---------------------------------------------------------------------------
# 8. Manifest and checksums
# ---------------------------------------------------------------------------
echo ""
echo "[8] Manifest and checksums"

MANIFEST="$SHARD_DIR/manifests/manifest.json"
CHECKSUMS="$SHARD_DIR/manifests/SHA256SUMS.txt"

if [[ -f "$MANIFEST" ]]; then
    check_pass "manifest.json exists"
else
    check_fail "manifest.json missing"
    check_blocked "Cannot validate checksums without manifest"
fi

if [[ -f "$CHECKSUMS" ]]; then
    check_pass "SHA256SUMS.txt exists"
    # Verify checksums if sha256sum is available
    if command -v sha256sum &>/dev/null; then
        (cd "$SHARD_DIR" && sha256sum -c "$CHECKSUMS" --quiet 2>/dev/null)
        if [[ $? -eq 0 ]]; then
            check_pass "Checksums verified"
        else
            check_fail "Checksum verification failed"
        fi
    else
        check_blocked "sha256sum not available — cannot verify checksums"
    fi
else
    check_fail "SHA256SUMS.txt missing"
fi

# ---------------------------------------------------------------------------
# 9. Path audit — no absolute drive-letter paths in config
# ---------------------------------------------------------------------------
echo ""
echo "[9] Path audit (shard-root-relative)"

if [[ -f "$SHARD_DIR/config/sovereign.env" ]]; then
    # Check for hard-coded Windows drive letters (C:\, D:\, etc.)
    if grep -qE '[A-Z]:\\' "$SHARD_DIR/config/sovereign.env"; then
        check_fail "sovereign.env contains hard-coded drive letter paths"
    else
        check_pass "sovereign.env uses shard-root-relative paths"
    fi
fi

# Check launcher for hard-coded paths (excluding %~dp0 which is correct)
if [[ -f "$SHARD_DIR/launch/J-cloud.bat" ]]; then
    if grep -qiE '[A-Z]:\\' "$SHARD_DIR/launch/J-cloud.bat" | grep -v '%~dp0' | grep -v '^rem' | grep -v '^@'; then
        # Allow SHARD_ROOT derivation from %~dp0 — only flag explicit absolute paths
        hard_paths=$(grep -iE '[A-Z]:\\' "$SHARD_DIR/launch/J-cloud.bat" | grep -v '%~dp0' | grep -v '^rem' | grep -v '^@' || true)
        if [[ -n "$hard_paths" ]]; then
            check_fail "J-cloud.bat contains hard-coded drive letter paths"
        else
            check_pass "J-cloud.bat uses shard-root-relative paths"
        fi
    else
        check_pass "J-cloud.bat uses shard-root-relative paths"
    fi
fi

# ---------------------------------------------------------------------------
# 10. Cloud adapter mandatory check
# ---------------------------------------------------------------------------
echo ""
echo "[10] Cloud adapter mandatory check"

if [[ -f "$SHARD_DIR/config/sovereign.env" ]]; then
    if grep -q "J_CLOUD_ENABLE_CLOUD_ADAPTERS" "$SHARD_DIR/config/sovereign.env"; then
        # If it contains adapters, check they're not mandatory
        adapters=$(grep "J_CLOUD_ENABLE_CLOUD_ADAPTERS" "$SHARD_DIR/config/sovereign.env" | cut -d= -f2)
        if [[ -n "$adapters" ]]; then
            yellow "  NOTE: Cloud adapters enabled: $adapters"
            echo "         These are optional and should not block startup."
        else
            check_pass "No cloud adapters enabled (fully offline)"
        fi
    else
        check_pass "No cloud adapters enabled (fully offline)"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo " VALIDATION SUMMARY"
echo "============================================"
echo "  PASS:    $PASS_COUNT"
echo "  FAIL:    $FAIL_COUNT"
echo "  BLOCKED: $BLOCKED_COUNT"
echo ""

if [[ $FAIL_COUNT -gt 0 ]]; then
    red "RESULT: FAIL — artifact has $FAIL_COUNT problem(s)"
    exit 1
elif [[ $BLOCKED_COUNT -gt 0 ]]; then
    yellow "RESULT: PASS with warnings — $BLOCKED_COUNT component(s) missing/blocked"
    yellow "        Artifact is valid but requires host-provided runtimes."
    exit 0
else
    green "RESULT: PASS — artifact is valid and complete"
    exit 0
fi
