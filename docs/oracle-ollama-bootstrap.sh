#!/usr/bin/env bash
#
# oracle-ollama-bootstrap.sh
#
# One-shot setup for the Gauntlet DevSpace fine-tuned LoRA on an Oracle Cloud
# Ampere A1 (ARM64, 24 GB RAM) Ubuntu 22 VM. Idempotent — safe to re-run.
#
# What it does (~45-90 min end-to-end, mostly downloads):
#   1. System prep (build tools, python, huggingface CLI, cloudflared)
#   2. Downloads base Qwen 2.5 Coder 7B (~14 GB from Hugging Face)
#   3. Downloads your LoRA adapter (38 MB from Cloudflare R2)
#   4. Merges LoRA into base weights
#   5. Converts to q4_k_m GGUF (~4.5 GB, runs comfortably on 24 GB RAM)
#   6. Imports into Ollama as `j-v1`
#   7. Exposes Ollama on 0.0.0.0:11434
#   8. Sets up a Cloudflare Tunnel so it's reachable from the internet
#
# USAGE:
#   scp oracle-ollama-bootstrap.sh ubuntu@<VM_IP>:~/
#   ssh ubuntu@<VM_IP>
#   chmod +x oracle-ollama-bootstrap.sh
#   ./oracle-ollama-bootstrap.sh
#
# ---------------------------------------------------------------------------

set -euo pipefail

# --- Config ----------------------------------------------------------------
WORKDIR="${HOME}/j-model"
BASE_MODEL="Qwen/Qwen2.5-Coder-7B-Instruct"
MODEL_NAME="j-v1"
QUANT="q4_k_m"          # q4_k_m is best speed/quality on ARM CPU
OLLAMA_PORT=11434

# Signed R2 URLs (7-day expiry — regenerate if this script fails after that)
ADAPTER_SAFETENSORS_URL='https://fbeba52b3b274d3d9b1febebc39f2d03.r2.cloudflarestorage.com/j-training-artifacts/adapters/r_4bd8c3/adapter_model.safetensors?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=68feba78f0b2c90c316b441e5cd77c75%2F20260722%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20260722T111719Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=917c07de0762383fcc7bfeae40530e3d5e25d73ef7e9a16ef9e85a534d69cdf3'
ADAPTER_CONFIG_URL='https://fbeba52b3b274d3d9b1febebc39f2d03.r2.cloudflarestorage.com/j-training-artifacts/adapters/r_4bd8c3/adapter_config.json?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=68feba78f0b2c90c316b441e5cd77c75%2F20260722%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20260722T111719Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=9bc6b231c14d9d3f1595da5b5c770390e62bff4560cea2084a0352a4cde834bb'

# Optional: set to your Cloudflare Tunnel token to auto-connect at the end.
# Get one from https://one.dash.cloudflare.com → Zero Trust → Networks → Tunnels
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"

# --- Helpers ---------------------------------------------------------------
log() { echo -e "\n\033[1;36m▶ $*\033[0m"; }

# --- 1. System prep --------------------------------------------------------
log "1/8  Installing system deps"
sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential git curl wget ca-certificates gnupg lsb-release \
  python3 python3-pip python3-venv cmake

# Open the Ollama port on Oracle's Ubuntu firewall (iptables-based)
sudo iptables -I INPUT 6 -p tcp --dport ${OLLAMA_PORT} -j ACCEPT || true
sudo netfilter-persistent save 2>/dev/null || sudo iptables-save > /etc/iptables/rules.v4 2>/dev/null || true

# --- 2. Install Ollama -----------------------------------------------------
if ! command -v ollama >/dev/null; then
  log "2/8  Installing Ollama"
  curl -fsSL https://ollama.com/install.sh | sh
else
  log "2/8  Ollama already installed"
fi

# Ensure Ollama listens on all interfaces (not just 127.0.0.1)
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0:${OLLAMA_PORT}"
Environment="OLLAMA_KEEP_ALIVE=24h"
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sleep 3

# --- 3. Setup Python venv --------------------------------------------------
log "3/8  Creating Python venv + installing merge/convert tooling"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate

pip install --upgrade pip
pip install "torch" "transformers>=4.44" "peft>=0.12" "safetensors" \
            "sentencepiece" "protobuf" "huggingface_hub"

# --- 4. Download base model + adapter --------------------------------------
log "4/8  Downloading base model ${BASE_MODEL} (~14 GB — may take 5-10 min)"
huggingface-cli download "${BASE_MODEL}" \
  --local-dir "${WORKDIR}/base" --local-dir-use-symlinks False

log "4/8  Downloading LoRA adapter from R2"
mkdir -p "${WORKDIR}/adapter"
curl -fL --retry 3 -o "${WORKDIR}/adapter/adapter_model.safetensors" "${ADAPTER_SAFETENSORS_URL}"
curl -fL --retry 3 -o "${WORKDIR}/adapter/adapter_config.json"       "${ADAPTER_CONFIG_URL}"

# --- 5. Merge LoRA into base ----------------------------------------------
log "5/8  Merging LoRA into base model (loads ~14 GB into RAM — needs full 24 GB VM)"
python3 - <<PYEOF
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

print("loading base model in bfloat16...")
base = AutoModelForCausalLM.from_pretrained(
    "${WORKDIR}/base",
    torch_dtype=torch.bfloat16,
    device_map="cpu",
    low_cpu_mem_usage=True,
)
tok = AutoTokenizer.from_pretrained("${WORKDIR}/base")

print("attaching LoRA adapter...")
model = PeftModel.from_pretrained(base, "${WORKDIR}/adapter")

print("merging + unloading...")
merged = model.merge_and_unload()

print("saving to ${WORKDIR}/merged...")
merged.save_pretrained("${WORKDIR}/merged", safe_serialization=True, max_shard_size="4GB")
tok.save_pretrained("${WORKDIR}/merged")
print("done.")
PYEOF

# --- 6. Convert to GGUF ----------------------------------------------------
log "6/8  Cloning llama.cpp + converting to GGUF ${QUANT}"
if [ ! -d "${WORKDIR}/llama.cpp" ]; then
  git clone --depth 1 https://github.com/ggerganov/llama.cpp "${WORKDIR}/llama.cpp"
fi
cd "${WORKDIR}/llama.cpp"
pip install -r requirements.txt

# f16 intermediate, then quantize to q4_k_m
python3 convert_hf_to_gguf.py "${WORKDIR}/merged" \
        --outfile "${WORKDIR}/${MODEL_NAME}-f16.gguf" --outtype f16

# Build the quantize tool if not present
if [ ! -f "${WORKDIR}/llama.cpp/build/bin/llama-quantize" ]; then
  cmake -B build -DGGML_NATIVE=ON
  cmake --build build --config Release -j"$(nproc)" --target llama-quantize
fi
./build/bin/llama-quantize \
        "${WORKDIR}/${MODEL_NAME}-f16.gguf" \
        "${WORKDIR}/${MODEL_NAME}.gguf" "${QUANT}"

# Free ~14 GB by dropping the merged HF snapshot + f16 GGUF
rm -rf "${WORKDIR}/merged" "${WORKDIR}/${MODEL_NAME}-f16.gguf"

# --- 7. Register with Ollama -----------------------------------------------
log "7/8  Registering ${MODEL_NAME} with Ollama"
cat > "${WORKDIR}/Modelfile" <<'MODELFILE'
FROM ./j-v1.gguf
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 8192
PARAMETER stop "<|im_end|>"
TEMPLATE """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
"""
SYSTEM """You are J, an AI coworker embedded in the Gauntlet DevSpace IDE. You have been fine-tuned on your operator's chronicle of past answers. Prefer concrete code, cite files and line numbers when relevant, and never invent APIs."""
MODELFILE

cd "${WORKDIR}"
ollama create "${MODEL_NAME}" -f Modelfile

# Warm the model into memory so first request isn't a 30-sec load stall.
ollama run "${MODEL_NAME}" "ready?" </dev/null || true

# --- 8. Cloudflare Tunnel (optional) ---------------------------------------
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN}" ]; then
  log "8/8  Installing Cloudflare Tunnel"
  if ! command -v cloudflared >/dev/null; then
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb" \
      -o /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb
  fi
  sudo cloudflared service install "${CLOUDFLARE_TUNNEL_TOKEN}"
  echo "→ Cloudflare Tunnel installed. Configure the public hostname to route to http://localhost:${OLLAMA_PORT} in your Cloudflare dashboard."
else
  log "8/8  Skipping Cloudflare Tunnel (no CLOUDFLARE_TUNNEL_TOKEN in env)"
  echo "→ Set CLOUDFLARE_TUNNEL_TOKEN before running to auto-connect."
  echo "→ Or run manually later:"
  echo "     curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cf.deb"
  echo "     sudo dpkg -i /tmp/cf.deb"
  echo "     sudo cloudflared service install <token-from-dashboard>"
fi

# --- Sanity check ---------------------------------------------------------
log "DONE. Sanity check:"
VM_IP=$(hostname -I | awk '{print $1}')
echo
echo "  curl http://${VM_IP}:${OLLAMA_PORT}/api/tags"
echo
curl -s "http://127.0.0.1:${OLLAMA_PORT}/api/tags" | python3 -m json.tool || true

cat <<POINT

═══════════════════════════════════════════════════════════════════
✅  j-v1 is ready at http://${VM_IP}:${OLLAMA_PORT}

Point J's BYOK card at:
    provider  =  ollama
    model     =  j-v1
    base_url  =  http://${VM_IP}:${OLLAMA_PORT}    (or your CF tunnel URL)

Test:
    curl http://${VM_IP}:${OLLAMA_PORT}/api/generate \\
      -d '{"model":"j-v1","prompt":"what is 2+2","stream":false}'
═══════════════════════════════════════════════════════════════════
POINT
