#!/usr/bin/env bash
# agent-notify
set -u

if [[ "${1:-}" != "--worker" ]]; then
    if (( $# < 1 || $# > 3 )); then
        echo "Usage: agent-notify MESSAGE [TITLE] [PRIORITY]" >&2
        exit 2
    fi
    if [[ "${AGENT_NOTIFY_DRY_RUN:-0}" == "1" ]]; then
        exec "$0" --worker "$@"
    fi
    uid="$(id -u)"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
    unit="agent-notify-${uid}-${$}-$(date +%s%N)"
    systemd-run --user --quiet --collect --no-block \
        --unit="$unit" \
        --property=RuntimeMaxSec=6s \
        "$0" --worker "$@" >/dev/null 2>&1 || true
    exit 0
fi

shift
message=${1//
title=${2:-u24}
priority=${3:-default}
notify=/home/gpt/.local/bin/notify

stamp="$(TZ=Europe/Kyiv date '+%H:%M')"
limits="$(python3 - <<'PY' 2>/dev/null || true
import json
import time
import urllib.request
from pathlib import Path

def pct(value):
    if value is None:
        return "?"
    return str(max(0, min(100, round(100 - float(value)))))

def left(reset_at, weekly=False):
    if not reset_at:
        return "?"
    sec = max(0, int(float(reset_at) - time.time()))
    if weekly:
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}:{h}:{m:02d}"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}:{m:02d}"

try:
    auth = json.loads((Path.home() / ".codex" / "auth.json").read_text())
    tokens = auth["tokens"]
    req = urllib.request.Request(
        "https://chatgpt.com/backend-api/wham/usage",
        headers={
            "Authorization": "Bearer " + tokens["access_token"],
            "ChatGPT-Account-Id": tokens["account_id"],
            "User-Agent": "codex-cli",
        },
    )
    with urllib.request.urlopen(req, timeout=2.0) as response:
        data = json.load(response)
    rate = data.get("rate_limit") or {}
    p = rate.get("primary_window") or {}
    w = rate.get("secondary_window") or {}
    print(f"{pct(p.get('used_percent'))}-{left(p.get('reset_at'))}   "
          f"{pct(w.get('used_percent'))}-{left(w.get('reset_at'), True)}")
except Exception:
    print("?-?   ?-?")
PY
)"
body="$stamp"$'\n'"$message"$'\n'"${limits:-?-?   ?-?}"

if [[ "${AGENT_NOTIFY_DRY_RUN:-0}" == "1" ]]; then
    printf '%s\n' "$body"
    exit 0
fi

timeout 3s "$notify" "$body" "$title" "$priority" >/dev/null 2>&1
\\n'/ }
title=${2:-u24}
priority=${3:-default}
notify=/home/gpt/.local/bin/notify

stamp="$(TZ=Europe/Kyiv date '+%H:%M')"
limits="$(python3 - <<'PY' 2>/dev/null || true
import json
import time
import urllib.request
from pathlib import Path

def pct(value):
    if value is None:
        return "?"
    return str(max(0, min(100, round(100 - float(value)))))

def left(reset_at, weekly=False):
    if not reset_at:
        return "?"
    sec = max(0, int(float(reset_at) - time.time()))
    if weekly:
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}:{h}:{m:02d}"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    return f"{h}:{m:02d}"

try:
    auth = json.loads((Path.home() / ".codex" / "auth.json").read_text())
    tokens = auth["tokens"]
    req = urllib.request.Request(
        "https://chatgpt.com/backend-api/wham/usage",
        headers={
            "Authorization": "Bearer " + tokens["access_token"],
            "ChatGPT-Account-Id": tokens["account_id"],
            "User-Agent": "codex-cli",
        },
    )
    with urllib.request.urlopen(req, timeout=2.0) as response:
        data = json.load(response)
    rate = data.get("rate_limit") or {}
    p = rate.get("primary_window") or {}
    w = rate.get("secondary_window") or {}
    print(f"{pct(p.get('used_percent'))}-{left(p.get('reset_at'))}   "
          f"{pct(w.get('used_percent'))}-{left(w.get('reset_at'), True)}")
except Exception:
    print("?-?   ?-?")
PY
)"
body="$stamp"$'\n'"$message"$'\n'"${limits:-?-?   ?-?}"

if [[ "${AGENT_NOTIFY_DRY_RUN:-0}" == "1" ]]; then
    printf '%s\n' "$body"
    exit 0
fi

"$notify" "$body" "$title" "$priority" >/dev/null 2>&1 || true
