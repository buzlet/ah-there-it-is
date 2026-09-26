#!/usr/bin/env bash
# u24_agent_notify.sh
set -uo pipefail

notify=/home/gpt/.local/bin/notify
usage_cmd=/home/rdu01/.local/bin/codex-usage

if (( $# < 1 || $# > 3 )); then
    echo "Usage: agent-notify MESSAGE [TITLE] [PRIORITY]" >&2
    exit 2
fi

message=$1
title=${2:-u24 agent}
priority=${3:-default}

format_remaining() {
    local seconds=$1
    (( seconds < 0 )) && seconds=0
    local days=$((seconds / 86400))
    local hours=$(((seconds % 86400) / 3600))
    local mins=$(((seconds % 3600) / 60))
    if (( days > 0 )); then
        printf '%dd %dh' "$days" "$hours"
    elif (( hours > 0 )); then
        printf '%dh %dm' "$hours" "$mins"
    else
        printf '%dm' "$mins"
    fi
}

usage_suffix=""
if [[ -x "$usage_cmd" ]]; then
    usage="$("$usage_cmd" 2>/dev/null || true)"
    line5="$(printf '%s\n' "$usage" | grep '^5h:' | head -1 || true)"
    linew="$(printf '%s\n' "$usage" | grep '^weekly:' | head -1 || true)"

    rem5="$(printf '%s\n' "$line5" | sed -n 's/.*remaining \([0-9][0-9]*%\).*/\1/p')"
    reset5="$(printf '%s\n' "$line5" | sed -n 's/.*reset \(.*\)$/\1/p')"
    remw="$(printf '%s\n' "$linew" | sed -n 's/.*remaining \([0-9][0-9]*%\).*/\1/p')"
    resetw="$(printf '%s\n' "$linew" | sed -n 's/.*reset \(.*\)$/\1/p')"

    now="$(date +%s)"
    left5="?"
    leftw="?"
    if [[ -n "$rem5" && -n "$reset5" ]]; then
        epoch5="$(date -d "$reset5" +%s 2>/dev/null || true)"
        [[ "$epoch5" =~ ^[0-9]+$ ]] && left5="$(format_remaining $((epoch5 - now)))"
    fi
    if [[ -n "$remw" && -n "$resetw" ]]; then
        epochw="$(date -d "$resetw" +%s 2>/dev/null || true)"
        [[ "$epochw" =~ ^[0-9]+$ ]] && leftw="$(format_remaining $((epochw - now)))"
    fi

    if [[ -n "$rem5" || -n "$remw" ]]; then
        usage_suffix=$'\n'"Limits: 5h ${rem5:-?} · ${left5}; week ${remw:-?} · ${leftw}"
    fi
fi

"$notify" "$message$usage_suffix" "$title" "$priority" || true
