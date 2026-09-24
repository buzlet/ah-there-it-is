from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.agent import ci_waiter


HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def _check(name: str, status: str, conclusion: str | None = None) -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def _status(context: str, state: str) -> dict:
    return {"context": context, "state": state}


def _cycle(
    runs: list[dict] | None = None,
    statuses: list[dict] | None = None,
    *,
    before: str = HEAD,
    after: str = HEAD,
    combined: str = "pending",
    runs_response: object | None = None,
) -> dict:
    return {
        "before": before,
        "after": after,
        "runs": runs_response
        if runs_response is not None
        else {"total_count": len(runs or []), "check_runs": runs or []},
        "statuses": {"state": combined, "statuses": statuses or []},
    }


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.value += duration


class FakeGitHub:
    def __init__(self, cycles: list[dict]) -> None:
        self.cycles = cycles
        self.poll_index = 0
        self.pr_read_index = 0
        self.calls: list[list[str]] = []
        self.environments: list[dict[str, str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.environments.append(dict(kwargs["env"]))
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] > 0
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert args[1] == "api"
        assert "--method" not in args
        assert kwargs["env"]["GH_PROMPT_DISABLED"] == "1"
        cycle = self.cycles[min(self.poll_index, len(self.cycles) - 1)]
        route = args[-1]
        if "/pulls/" in route:
            head = cycle["before"] if self.pr_read_index == 0 else cycle["after"]
            self.pr_read_index += 1
            if self.pr_read_index == 2:
                self.pr_read_index = 0
                self.poll_index += 1
            payload = {"head": {"sha": head}}
        elif "/check-runs?" in route:
            assert "--paginate" in args and "--slurp" in args
            payload = [cycle["runs"]]
        elif route.endswith("/status?per_page=100"):
            assert "--paginate" in args and "--slurp" in args
            payload = [cycle["statuses"]]
        else:
            raise AssertionError(f"unexpected gh api route: {route}")
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(payload), stderr=""
        )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    cycles: list[dict],
) -> tuple[FakeGitHub, FakeClock]:
    fake_gh = FakeGitHub(cycles)
    clock = FakeClock()
    monkeypatch.setattr(ci_waiter.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(ci_waiter.subprocess, "run", fake_gh)
    return fake_gh, clock


def _wait(
    clock: FakeClock,
    *,
    state_dir: Path | None = None,
    timeout: float = 10.0,
    interval: float = 1.0,
    grace: float = 3.0,
) -> dict:
    return ci_waiter.wait_for_checks(
        repository="buzlet/ah-there-it-is",
        pr_number=58,
        expected_head_sha=HEAD,
        timeout_seconds=timeout,
        poll_interval_seconds=interval,
        registration_grace_seconds=grace,
        state_dir=None if state_dir is None else str(state_dir),
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )


def test_waits_for_delayed_check_registration_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch,
        [
            _cycle(),
            _cycle([_check("verify", "completed", "success")], combined="pending"),
        ],
    )

    result = _wait(clock)

    assert result["status"] == "success"
    assert result["expected_head_sha"] == HEAD
    assert result["current_head_sha"] == HEAD
    assert [check["name"] for check in result["observed_checks"]] == ["verify"]
    assert result["poll_count"] == 2
    assert clock.sleeps == [1.0]
    assert len(fake_gh.calls) == 8


def test_queued_check_transitions_to_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh, clock = _install(
        monkeypatch,
        [
            _cycle([_check("verify", "queued")]),
            _cycle([_check("verify", "completed", "success")], combined="pending"),
        ],
    )

    result = _wait(clock)

    assert result["status"] == "success"
    assert [call[-1].split("/")[-1].split("?")[0] for call in fake_gh.calls[1:3]] == [
        "check-runs",
        "status",
    ]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_terminal_non_success_conclusion_fails_immediately(
    monkeypatch: pytest.MonkeyPatch,
    conclusion: str,
) -> None:
    fake_gh, clock = _install(
        monkeypatch, [_cycle([_check("verify", "completed", conclusion)])]
    )

    result = _wait(clock)

    assert result["status"] == "failed"
    assert conclusion in result["failure_reason"]
    assert result["poll_count"] == 1
    assert clock.sleeps == []
    assert len(fake_gh.calls) == 4


def test_mixed_success_neutral_skipped_and_commit_statuses_are_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch,
        [
            _cycle(
                [
                    _check("verify", "completed", "success"),
                    _check("docs", "completed", "skipped"),
                    _check("advisory", "completed", "neutral"),
                ],
                [_status("legacy-lint", "success")],
                combined="success",
            )
        ],
    )

    result = _wait(clock)

    assert result["status"] == "success"
    assert len(result["observed_checks"]) == 4
    assert {check["source"] for check in result["observed_checks"]} == {
        "check_run",
        "commit_status",
    }


def test_failed_commit_status_fails_even_if_check_run_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        [
            _cycle(
                [_check("verify", "completed", "success")],
                [_status("legacy-lint", "failure")],
                combined="failure",
            )
        ],
    )

    result = _wait(FakeClock())

    assert result["status"] == "failed"
    assert "legacy-lint" in result["failure_reason"]


def test_pr_head_change_during_check_observation_stops_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch,
        [
            _cycle(
                [_check("verify", "queued")],
                before=HEAD,
                after=OTHER_HEAD,
            )
        ],
    )

    result = _wait(clock)

    assert result["status"] == "head_changed"
    assert result["current_head_sha"] == OTHER_HEAD
    assert "changed while" in result["failure_reason"]
    assert len(fake_gh.calls) == 4
    assert clock.sleeps == []


def test_head_mismatch_before_observing_checks_stops_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch, [_cycle(before=OTHER_HEAD, after=OTHER_HEAD)]
    )

    result = _wait(clock)

    assert result["status"] == "head_changed"
    assert result["current_head_sha"] == OTHER_HEAD
    assert len(fake_gh.calls) == 1


def test_no_registered_checks_fails_after_bounded_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(monkeypatch, [_cycle()])

    result = _wait(clock, grace=2.0)

    assert result["status"] == "checks_not_registered"
    assert "2-second" in result["failure_reason"]
    assert result["poll_count"] == 3
    assert clock.sleeps == [1.0, 1.0]


def test_wait_times_out_while_checks_are_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch, [_cycle([_check("verify", "in_progress")])]
    )

    result = _wait(clock, timeout=2.5)

    assert result["status"] == "timed_out"
    assert result["failure_reason"] == "timed out waiting for checks"
    assert result["elapsed_seconds"] == 2.5
    assert result["poll_count"] == 3


def test_malformed_github_response_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch,
        [_cycle(runs_response={"total_count": 1, "check_runs": "invalid"})],
    )

    result = _wait(clock)

    assert result["status"] == "malformed_response"
    assert "check_runs array" in result["failure_reason"]
    assert result["poll_count"] == 1


def test_missing_gh_fails_without_running_a_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci_waiter.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        ci_waiter.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("gh must not run when absent"),
    )

    result = _wait(FakeClock())

    assert result["status"] == "gh_unavailable"
    assert "not found" in result["failure_reason"]


def test_unauthenticated_gh_fails_without_exposing_cli_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ci_waiter.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        ci_waiter.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="gh: not logged in to github.com",
        ),
    )

    result = _wait(FakeClock())

    assert result["status"] == "unauthenticated"
    assert "not authenticated" in result["failure_reason"]
    assert "logged in" not in result["failure_reason"]


def test_only_read_only_gh_api_requests_are_emitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh, clock = _install(
        monkeypatch, [_cycle([_check("verify", "completed", "success")])]
    )

    assert _wait(clock)["status"] == "success"

    assert len(fake_gh.calls) == 4
    assert all(call[1] == "api" for call in fake_gh.calls)
    assert all("--method" not in call for call in fake_gh.calls)
    assert all("/actions/runs/" not in " ".join(call) for call in fake_gh.calls)


def test_external_state_records_observations_and_atomic_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install(
        monkeypatch, [_cycle([_check("verify", "completed", "success")])]
    )
    state_dir = tmp_path / "wait-run"

    result = _wait(FakeClock(), state_dir=state_dir)

    assert result["status"] == "success"
    assert result["state_dir"] == str(state_dir.resolve())
    summary = json.loads((state_dir / "summary.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (state_dir / "observations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert summary["status"] == "success"
    assert events[0]["status"] == "success"
    assert events[0]["expected_head_sha"] == HEAD
    assert not list(state_dir.glob("*.tmp"))


def test_state_directory_is_external_and_never_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install(monkeypatch, [_cycle([_check("verify", "completed", "success")])])
    repo_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ci_waiter.WaiterError, match="outside"):
        ci_waiter._prepare_journal(str(repo_root / "waiter-state"))
    assert not (repo_root / "waiter-state").exists()

    state_dir = tmp_path / "already-used"
    state_dir.mkdir()
    with pytest.raises(ci_waiter.WaiterError, match="fresh unique"):
        ci_waiter._prepare_journal(str(state_dir))


@pytest.mark.parametrize(
    ("timeout", "interval", "grace"),
    [
        (0, 1, 1),
        (float("nan"), 1, 1),
        (10, 0.5, 1),
        (10, 301, 1),
        (10, 1, 601),
    ],
)
def test_invalid_wait_bounds_are_rejected(
    timeout: float,
    interval: float,
    grace: float,
) -> None:
    with pytest.raises(ci_waiter.WaiterError):
        ci_waiter._validate_inputs(
            "buzlet/ah-there-it-is",
            58,
            HEAD,
            timeout,
            interval,
            grace,
        )


def test_combined_failure_without_visible_context_does_not_report_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        [
            _cycle(
                [_check("verify", "completed", "success")],
                [],
                combined="failure",
            )
        ],
    )

    result = _wait(FakeClock())

    assert result["status"] == "failed"
    assert any(
        check["source"] == "commit_status_summary"
        for check in result["observed_checks"]
    )
