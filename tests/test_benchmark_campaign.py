from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ah_there_it_is.benchmark_campaign import (
    BenchmarkCampaignManifest,
    load_campaign_manifest,
    run_campaign,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_inputs(tmp_path: Path) -> tuple[Path, str, str]:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("prompt body\n", encoding="utf-8")
    prompt_hash = hashlib.sha256(prompt.read_bytes()).hexdigest()
    corpus = {
        "version": "corpus-test-v1",
        "fixture": "inventory-fixture-v1",
        "cases": [
            {"id": "live-b", "group": "g", "turns": ["b"], "focus": "b"},
            {"id": "live-a", "group": "g", "turns": ["a"], "focus": "a"},
        ],
    }
    probes = {
        "version": "probe-test-v1",
        "cases": [
            {
                "id": "probe-z",
                "messages": [{"role": "user", "content": "z"}],
                "steps": [{"no_tool_calls": True, "require_text": True}],
            }
        ],
    }
    (tmp_path / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    (tmp_path / "probes.json").write_text(json.dumps(probes), encoding="utf-8")
    return prompt, prompt_hash, "probe-test-v1"


def _manifest(tmp_path: Path) -> BenchmarkCampaignManifest:
    _prompt, prompt_hash, probe_version = _write_inputs(tmp_path)
    return BenchmarkCampaignManifest.model_validate(
        {
            "schema_version": "benchmark-campaign-v1",
            "campaign_id": "campaign-1",
            "campaign_version": "7",
            "candidate": {
                "provider": "fake",
                "model": "fake-1",
                "config_label": "temp0",
            },
            "prompt": {
                "version": "prompt-v7",
                "file": "prompt.txt",
                "sha256": prompt_hash,
            },
            "live_eval": {
                "file": "corpus.json",
                "version": "corpus-test-v1",
                "case_ids": ["live-b", "live-a"],
            },
            "model_probe": {
                "file": "probes.json",
                "version": probe_version,
                "case_ids": ["probe-z"],
            },
            "repetitions": 2,
            "delay_seconds": 0.25,
            "output": {"directory": "results", "file_prefix": "candidate"},
        }
    )


def _provider(**config: object) -> dict:
    return {"provider": "fake", "model": "fake-1", "config": config}


def test_campaign_manifest_is_strict_versioned_and_rejects_secret_fields(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    path = tmp_path / "campaign.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    loaded = load_campaign_manifest(path)
    assert loaded.schema_version == "benchmark-campaign-v1"
    with pytest.raises(ValidationError):
        BenchmarkCampaignManifest.model_validate(
            {**manifest.model_dump(), "unexpected": True}
        )
    with pytest.raises(ValidationError):
        BenchmarkCampaignManifest.model_validate(
            {
                **manifest.model_dump(),
                "candidate": {
                    "provider": "fake",
                    "model": "fake-1",
                    "config_label": "Bearer abc.def.secret",
                },
            }
        )


def test_campaign_repeated_order_is_declared_and_incrementally_persisted(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    calls: list[str] = []
    sleeps: list[float] = []
    output = tmp_path / "campaign-result.json"

    def live(case, prompt, prompt_version):
        assert prompt == "prompt body\n"
        assert prompt_version == "prompt-v7"
        calls.append(f"live:{case.id}")
        persisted = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
        if persisted is not None:
            assert len(persisted["attempts"]) == len(calls) - 1
        return {"case_id": case.id, "status": "completed", "checks_passed": True}

    def probe(case):
        calls.append(f"probe:{case.id}")
        return {"case_id": case.id, "passed": True}

    result = run_campaign(
        manifest,
        provider_info=_provider(temperature=0),
        live_executor=live,
        probe_executor=probe,
        base_dir=tmp_path,
        result_path=output,
        sleep=sleeps.append,
    )

    assert calls == [
        "live:live-b", "live:live-b", "live:live-a", "live:live-a", "probe:probe-z"
    ]
    assert [attempt["slot_id"] for attempt in result["attempts"]] == [
        "live_eval:live-b:1", "live_eval:live-b:2", "live_eval:live-a:1",
        "live_eval:live-a:2", "model_probe:probe-z:1",
    ]
    assert sleeps == [0.25, 0.25, 0.25, 0.25]
    assert json.loads(output.read_text(encoding="utf-8"))["completed"] is True


def test_campaign_resume_skips_completed_slots_and_ignores_stale_temp(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    output = tmp_path / "resume.json"
    calls: list[str] = []

    def live(case, prompt, prompt_version):
        calls.append(case.id)
        if len(calls) == 2:
            raise KeyboardInterrupt("simulated interruption")
        return {"case_id": case.id, "status": "completed", "checks_passed": True}

    with pytest.raises(KeyboardInterrupt):
        run_campaign(
            manifest,
            provider_info=_provider(temperature=0),
            live_executor=live,
            probe_executor=lambda case: {"case_id": case.id, "passed": True},
            base_dir=tmp_path,
            result_path=output,
        )
    first = json.loads(output.read_text(encoding="utf-8"))
    assert [a["slot_id"] for a in first["attempts"]] == ["live_eval:live-b:1"]
    output.with_name(output.name + ".tmp").write_text("truncated", encoding="utf-8")

    resumed_calls: list[str] = []
    result = run_campaign(
        manifest,
        provider_info=_provider(temperature=0),
        live_executor=lambda case, prompt, version: (
            resumed_calls.append(case.id)
            or {"case_id": case.id, "status": "completed", "checks_passed": True}
        ),
        probe_executor=lambda case: (
            resumed_calls.append(case.id) or {"case_id": case.id, "passed": True}
        ),
        base_dir=tmp_path,
        result_path=output,
    )
    assert resumed_calls == ["live-b", "live-a", "live-a", "probe-z"]
    assert len(result["attempts"]) == 5
    assert result["completed"] is True


def test_campaign_resume_refuses_provider_config_and_prompt_identity_changes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    output = tmp_path / "identity.json"
    run_campaign(
        manifest,
        provider_info=_provider(temperature=0),
        live_executor=lambda case, prompt, version: {"case_id": case.id, "status": "completed"},
        probe_executor=lambda case: {"case_id": case.id, "passed": True},
        base_dir=tmp_path,
        result_path=output,
    )
    with pytest.raises(ValueError, match="identity"):
        run_campaign(
            manifest,
            provider_info=_provider(temperature=1),
            live_executor=lambda *args: {},
            probe_executor=lambda *args: {},
            base_dir=tmp_path,
            result_path=output,
        )

    (tmp_path / "prompt.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="prompt hash mismatch"):
        run_campaign(
            manifest,
            provider_info=_provider(temperature=0),
            live_executor=lambda *args: {},
            probe_executor=lambda *args: {},
            base_dir=tmp_path,
            result_path=output,
        )


def test_campaign_result_does_not_persist_provider_or_evidence_secrets(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    output = tmp_path / "safe.json"
    run_campaign(
        manifest,
        provider_info={
            "provider": "fake",
            "model": "fake-1",
            "config": {"temperature": 0, "api_key": "top-secret"},
            "authorization": "Bearer provider-secret",
        },
        live_executor=lambda case, prompt, version: {
            "case_id": case.id,
            "headers": {"Authorization": "Bearer attempt-secret"},
            "error": "Bearer tokenvalue",
        },
        probe_executor=lambda case: {"case_id": case.id, "passed": True},
        base_dir=tmp_path,
        result_path=output,
    )
    text = output.read_text(encoding="utf-8")
    assert "top-secret" not in text
    assert "provider-secret" not in text
    assert "attempt-secret" not in text
    assert "tokenvalue" not in text
    assert "temperature" in text
