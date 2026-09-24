"""POSIX process identity helpers shared by local agent tooling."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _read_proc_stat(pid: int) -> dict[str, Any] | None:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="ascii") as stream:
            line = stream.read()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    closing_paren = line.rfind(")")
    if closing_paren < 0:
        return None
    fields = line[closing_paren + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return {
            "pid": pid,
            "state": fields[0],
            "pgrp": int(fields[2]),
            "session": int(fields[3]),
            "start_ticks": int(fields[19]),
        }
    except ValueError:
        return None


def _group_state(metadata: dict[str, Any]) -> tuple[str, bool]:
    """Return (state, supervisor_alive), checking Linux process identity."""
    try:
        pid = int(metadata["pid"])
        pgid = int(metadata["pgid"])
        expected_start = int(metadata["process_start_ticks"])
    except (KeyError, TypeError, ValueError):
        return "invalid", False
    if pid <= 0 or pgid != pid or expected_start <= 0:
        return "invalid", False

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return "unverifiable", False

    supervisor_alive = False
    live_group_members = 0
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return "unverifiable", False
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        info = _read_proc_stat(int(entry.name))
        if info is None or info["pgrp"] != pgid:
            continue
        if info["pid"] == pid:
            if info["start_ticks"] != expected_start:
                return "identity_mismatch", False
            if info["state"] not in {"Z", "X"}:
                supervisor_alive = True
        if info["state"] not in {"Z", "X"}:
            live_group_members += 1
    return ("live" if live_group_members else "dead", supervisor_alive)
