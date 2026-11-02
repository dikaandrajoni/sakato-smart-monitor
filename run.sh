#!/usr/bin/env bash
# Sakato Smart Monitor — jalan satu perintah:
#   ./run.sh
# Menyalakan: prototype (deteksi+face+Telegram+MQTT+VLM) + agent (--bridge).
# Mosquitto dicoba distart otomatis bila belum jalan.
#
# Kustomisasi via env:
#   SOURCE=rtsp://... ./run.sh     (default: 0 = webcam)
#   CAMERA_NAME=teras_belakang ./run.sh
#   EXTRA_ARGS="--no-show" ./run.sh
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE="${SOURCE:-0}"
CAMERA_NAME="${CAMERA_NAME:-teras_depan}"
EXTRA_ARGS="${EXTRA_ARGS:---gallery gallery/ --telegram --mqtt --describe}"

# 1. Mosquitto ---------------------------------------------------------------
if ! pgrep -x mosquitto >/dev/null 2>&1; then
  echo "[run] mosquitto belum jalan, mencoba start..."
  if ! (mosquitto -d 2>/dev/null || sudo -n systemctl start mosquitto 2>/dev/null); then
    echo "[run] WARNING: mosquitto gagal distart — lanjut tanpa MQTT"
    echo "[run]         (install: sudo apt install -y mosquitto)"
  fi
fi

# 2. Prototype ---------------------------------------------------------------
PY_PROTO="$ROOT/prototype/.venv/bin/python"
if [ ! -x "$PY_PROTO" ]; then
  echo "[run] ERROR: venv prototype belum ada."
  echo "[run] Ikuti panduan instalasi di README.md dulu."
  exit 1
fi
echo "[run] prototype: source=$SOURCE camera=$CAMERA_NAME"
(cd "$ROOT/prototype" && "$PY_PROTO" main.py \
  --source "$SOURCE" --camera-name "$CAMERA_NAME" $EXTRA_ARGS) &
PID_PROTO=$!

cleanup() { kill "$PID_PROTO" "$PID_AGENT" 2>/dev/null; }
trap cleanup INT TERM

# 3. Agent (--bridge: digest & eskalasi ke Telegram) --------------------------
PY_AGENT="$ROOT/agent/.venv/bin/python"
if [ -x "$PY_AGENT" ]; then
  echo "[run] agent --bridge"
  (cd "$ROOT" && "$PY_AGENT" -m agent.agent --bridge) &
  PID_AGENT=$!
else
  echo "[run] venv agent belum ada — agent dilewati (prototype tetap jalan)"
  echo "[run] pasang: cd agent && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  PID_AGENT=""
fi

wait
