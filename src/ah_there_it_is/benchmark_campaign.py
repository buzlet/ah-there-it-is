"""Versioned, resumable provider/model benchmark campaign orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClient,
    LLMClientInfo,
    LLMResponse,
    ToolDefinition,
)
from ah_there_it_is.eval_corpus import EvaluationCase, load_corpus
from ah_there_it_is.eval_fixture import FIXTURE_VERSION
from ah_there_it_is.model_probe import ModelProbeCase, load_probe_suite


CAMPAIGN_SCHEMA_VERSION = "benchmark-campaign-v1"
RESULT_SCHEMA_VERSION = "benchmark-result-v1"
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|access[_-]?token|refresh[_-]?token|(?:^|[._-])token$)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_BASIC_AUTH_RE = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{4,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|credential|authorization)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class PromptIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    file: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorpusSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str = Field(min_length=1)
    version: str = Field(min_length=1)
    case_ids: list[str] = Field(min_length=1)

    @field_validator("case_ids")
    @classmethod
    def _unique_case_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("case_ids must be unique")
        return value


class ProbeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str = Field(min_length=1)
    version: str = Field(min_length=1)
    case_ids: list[str] = Field(default_factory=list)

    @field_validator("case_ids")
    @classmethod
    def _unique_case_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("case_ids must be unique")
        return value


class CandidateIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    config_label: str = Field(min_length=1)


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: str = Field(min_length=1)
    file_prefix: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")


class BenchmarkCampaignManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["benchmark-campaign-v1"] = CAMPAIGN_SCHEMA_VERSION
    campaign_id: str = Field(min_length=1)
    campaign_version: str = Field(min_length=1)
    candidate: CandidateIdentity
    prompt: PromptIdentity
    live_eval: CorpusSelection
    model_probe: ProbeSelection
    repetitions: int = Field(default=1, ge=1, le=100)
    delay_seconds: float = Field(default=0.0, ge=0.0, le=3600.0)
    output: OutputConfig

    @model_validator(mode="after")
    def _reject_secret_like_text(self) -> "BenchmarkCampaignManifest":
        payload = self.model_dump(mode="json")
        for path, value in _walk_scalars(payload):
            if _SECRET_KEY_RE.search(path):
                raise ValueError(f"secret-bearing campaign field is forbidden: {path}")
            if isinstance(value, str) and _sanitize_text(value) != value:
                raise ValueError(f"secret-looking text is forbidden at {path}")
        return self


LiveExecutor = Callable[[EvaluationCase, str, str], dict[str, Any]]
ProbeExecutor = Callable[[ModelProbeCase], dict[str, Any]]
NowFn = Callable[[], str]
SleepFn = Callable[[float], None]


class _RequestThrottle:
    def __init__(self, delay_seconds: float, *, sleep: SleepFn = time.sleep) -> None:
        self.delay_seconds = delay_seconds
        self.sleep = sleep
        self.request_count = 0

    def before_request(self) -> None:
        if self.request_count and self.delay_seconds:
            self.sleep(self.delay_seconds)
        self.request_count += 1


class _ThrottledLLMClient:
    def __init__(self, client: LLMClient, throttle: _RequestThrottle) -> None:
        self._client = client
        self._throttle = throttle

    @property
    def info(self) -> LLMClientInfo:
        return self._client.info

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self._throttle.before_request()
        return self._client.complete(messages, tools)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def _walk_scalars(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_walk_scalars(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_scalars(item, f"{prefix}[{index}]"))
    else:
        found.append((prefix, value))
    return found


def _sanitize_text(value: str) -> str:
    sanitized = _BEARER_RE.sub("Bearer [redacted]", value)
    sanitized = _BASIC_AUTH_RE.sub("Basic [redacted]", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]", sanitized
    )
    sanitized = _SK_TOKEN_RE.sub("[redacted-token]", sanitized)
    return sanitized


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not _SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def load_campaign_manifest(path: str | Path) -> BenchmarkCampaignManifest:
    return BenchmarkCampaignManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def validate_campaign_inputs(
    manifest: BenchmarkCampaignManifest,
    *,
    base_dir: str | Path = ".",
) -> dict[str, Any]:
    base = Path(base_dir)
    prompt_path = _resolve(base, manifest.prompt.file)
    prompt = prompt_path.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if prompt_hash != manifest.prompt.sha256:
        raise ValueError(
            "prompt hash mismatch: "
            f"expected {manifest.prompt.sha256}, got {prompt_hash}"
        )

    corpus_path = _resolve(base, manifest.live_eval.file)
    corpus_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    corpus = load_corpus(corpus_path)
    if corpus.version != manifest.live_eval.version:
        raise ValueError(
            f"live corpus version mismatch: expected {manifest.live_eval.version!r}, "
            f"got {corpus.version!r}"
        )
    if corpus.fixture != FIXTURE_VERSION:
        raise ValueError(
            f"live corpus fixture mismatch: expected {FIXTURE_VERSION!r}, "
            f"got {corpus.fixture!r}"
        )
    corpus_by_id = {case.id: case for case in corpus.cases}
    missing_live = [
        case_id for case_id in manifest.live_eval.case_ids if case_id not in corpus_by_id
    ]
    if missing_live:
        raise ValueError("unknown live-eval case ids: " + ", ".join(missing_live))

    probe_path = _resolve(base, manifest.model_probe.file)
    probe_hash = hashlib.sha256(probe_path.read_bytes()).hexdigest()
    suite = load_probe_suite(probe_path)
    if suite.version != manifest.model_probe.version:
        raise ValueError(
            f"model-probe version mismatch: expected {manifest.model_probe.version!r}, "
            f"got {suite.version!r}"
        )
    probe_by_id = {case.id: case for case in suite.cases}
    missing_probe = [
        case_id for case_id in manifest.model_probe.case_ids if case_id not in probe_by_id
    ]
    if missing_probe:
        raise ValueError("unknown model-probe case ids: " + ", ".join(missing_probe))

    return {
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "corpus": corpus,
        "corpus_hash": corpus_hash,
        "corpus_by_id": corpus_by_id,
        "probe_suite": suite,
        "probe_hash": probe_hash,
        "probe_by_id": probe_by_id,
    }


def campaign_result_path(
    manifest: BenchmarkCampaignManifest,
    *,
    base_dir: str | Path = ".",
) -> Path:
    output_dir = _resolve(Path(base_dir), manifest.output.directory)
    return output_dir / f"{manifest.output.file_prefix}.json"


def _manifest_identity(manifest: BenchmarkCampaignManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")


def _provider_identity(
    provider_info: Mapping[str, Any],
    manifest: BenchmarkCampaignManifest,
) -> dict[str, Any]:
    safe = _safe_value(dict(provider_info))
    provider = safe.get("provider")
    model = safe.get("model")
    if provider != manifest.candidate.provider or model != manifest.candidate.model:
        raise ValueError(
            "configured provider/model does not match campaign candidate: "
            f"expected {manifest.candidate.provider}/{manifest.candidate.model}, "
            f"got {provider}/{model}"
        )
    config = safe.get("config") if isinstance(safe.get("config"), dict) else {}
    return {
        "provider": provider,
        "model": model,
        "config_label": manifest.candidate.config_label,
        "config": config,
        "config_hash": _canonical_hash(config),
    }


def _execution_identity(
    manifest: BenchmarkCampaignManifest,
    provider_identity: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> str:
    return _canonical_hash(
        {
            "campaign": _manifest_identity(manifest),
            "provider": provider_identity,
            "prompt_hash": inputs["prompt_hash"],
            "corpus_hash": inputs["corpus_hash"],
            "probe_hash": inputs["probe_hash"],
        }
    )


def _attempt_plan(
    manifest: BenchmarkCampaignManifest,
    inputs: Mapping[str, Any],
) -> list[tuple[str, str, int, EvaluationCase | ModelProbeCase]]:
    plan: list[tuple[str, str, int, EvaluationCase | ModelProbeCase]] = []
    for case_id in manifest.live_eval.case_ids:
        case = inputs["corpus_by_id"][case_id]
        for repetition in range(1, manifest.repetitions + 1):
            plan.append(("live_eval", case_id, repetition, case))
    for case_id in manifest.model_probe.case_ids:
        plan.append(("model_probe", case_id, 1, inputs["probe_by_id"][case_id]))
    return plan


def _slot_id(pipeline: str, case_id: str, repetition: int) -> str:
    return f"{pipeline}:{case_id}:{repetition}"


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _new_result(
    manifest: BenchmarkCampaignManifest,
    provider_identity: Mapping[str, Any],
    execution_identity: str,
    inputs: Mapping[str, Any],
    now: NowFn,
) -> dict[str, Any]:
    created = now()
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "campaign": _manifest_identity(manifest),
        "campaign_identity_hash": _canonical_hash(_manifest_identity(manifest)),
        "execution_identity_hash": execution_identity,
        "provider": dict(provider_identity),
        "prompt_version": manifest.prompt.version,
        "prompt_hash": manifest.prompt.sha256,
        "corpus_version": manifest.live_eval.version,
        "corpus_hash": inputs["corpus_hash"],
        "probe_suite_version": manifest.model_probe.version,
        "probe_suite_hash": inputs["probe_hash"],
        "created_at": created,
        "updated_at": created,
        "completed": False,
        "attempts": [],
    }


def _load_or_create_result(
    path: Path,
    manifest: BenchmarkCampaignManifest,
    provider_identity: Mapping[str, Any],
    execution_identity: str,
    inputs: Mapping[str, Any],
    now: NowFn,
) -> dict[str, Any]:
    if not path.exists():
        return _new_result(
            manifest, provider_identity, execution_identity, inputs, now
        )
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ValueError("existing campaign result uses an unsupported schema")
    if result.get("execution_identity_hash") != execution_identity:
        raise ValueError(
            "existing campaign result identity does not match provider/config/prompt/corpus/probe/campaign"
        )
    attempts = result.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("existing campaign result attempts must be a list")
    return result


def run_campaign(
    manifest: BenchmarkCampaignManifest,
    *,
    provider_info: Mapping[str, Any],
    live_executor: LiveExecutor,
    probe_executor: ProbeExecutor,
    base_dir: str | Path = ".",
    result_path: str | Path | None = None,
    now: NowFn = _utc_now,
    sleep: SleepFn = time.sleep,
    _delay_between_attempts: bool = True,
) -> dict[str, Any]:
    """Execute or resume one campaign using injected provider execution hooks."""

    base = Path(base_dir)
    inputs = validate_campaign_inputs(manifest, base_dir=base)
    provider_identity = _provider_identity(provider_info, manifest)
    identity = _execution_identity(manifest, provider_identity, inputs)
    output = Path(result_path) if result_path else campaign_result_path(manifest, base_dir=base)
    result = _load_or_create_result(
        output, manifest, provider_identity, identity, inputs, now
    )
    completed_slots = {
        attempt.get("slot_id")
        for attempt in result["attempts"]
        if isinstance(attempt, dict) and attempt.get("completed") is True
    }
    plan = _attempt_plan(manifest, inputs)
    pending_started = False

    for pipeline, case_id, repetition, case in plan:
        slot = _slot_id(pipeline, case_id, repetition)
        if slot in completed_slots:
            continue
        if pending_started and manifest.delay_seconds and _delay_between_attempts:
            sleep(manifest.delay_seconds)
        pending_started = True
        started_at = now()
        try:
            if pipeline == "live_eval":
                evidence = live_executor(
                    case, inputs["prompt"], manifest.prompt.version  # type: ignore[arg-type]
                )
            else:
                evidence = probe_executor(case)  # type: ignore[arg-type]
        except Exception as exc:
            evidence = {
                "campaign_execution_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            }
        finished_at = now()
        result["attempts"].append(
            {
                "slot_id": slot,
                "pipeline": pipeline,
                "case_id": case_id,
                "repetition": repetition,
                "completed": True,
                "started_at": started_at,
                "finished_at": finished_at,
                "evidence": _safe_value(evidence),
            }
        )
        result["updated_at"] = finished_at
        _atomic_write_json(output, result)

    result["completed"] = all(
        _slot_id(pipeline, case_id, repetition) in {
            attempt.get("slot_id")
            for attempt in result["attempts"]
            if isinstance(attempt, dict) and attempt.get("completed") is True
        }
        for pipeline, case_id, repetition, _case in plan
    )
    result["updated_at"] = now()
    _atomic_write_json(output, result)
    return result


def run_configured_campaign(
    manifest: BenchmarkCampaignManifest,
    *,
    base_dir: str | Path = ".",
    result_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run a manual campaign using the application's configured provider."""

    from ah_there_it_is.agent.factory import build_llm_factory
    from ah_there_it_is.config import get_settings
    from ah_there_it_is.live_eval import run_case
    from ah_there_it_is.model_probe import run_probe_case

    settings = get_settings()
    provider_factory = build_llm_factory(settings)
    info_client = provider_factory()
    throttle = _RequestThrottle(manifest.delay_seconds)
    probe_client = _ThrottledLLMClient(info_client, throttle)
    try:
        provider_info = info_client.info.model_dump(mode="json")

        def live_executor(
            case: EvaluationCase, prompt: str, prompt_version: str
        ) -> dict[str, Any]:
            return run_case(
                case,
                prompt=prompt,
                prompt_version=prompt_version,
                allow_heuristic=False,
                llm_factory=lambda: _ThrottledLLMClient(provider_factory(), throttle),
            )

        def probe_executor(case: ModelProbeCase) -> dict[str, Any]:
            return run_probe_case(probe_client, case)

        return run_campaign(
            manifest,
            provider_info=provider_info,
            live_executor=live_executor,
            probe_executor=probe_executor,
            base_dir=base_dir,
            result_path=result_path,
            _delay_between_attempts=False,
        )
    finally:
        probe_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = load_campaign_manifest(manifest_path)
    result = run_configured_campaign(
        manifest,
        base_dir=manifest_path.parent,
        result_path=args.output,
    )
    print(json.dumps({"completed": result["completed"], "attempts": len(result["attempts"])}))


if __name__ == "__main__":
    main()
