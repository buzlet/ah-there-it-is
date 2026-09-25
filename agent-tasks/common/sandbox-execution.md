# Sandbox execution rules

This document defines the third supported implementation execution channel.

## Descriptor

```text
host_profile: chatgpt-sandbox
execution_channel: sandbox
execution_user: sandbox
workdir: /mnt/data/<issued-patch-name>
source_artifact: sandbox-bundle-<expected-start-main-sha>
```

The launcher still supplies the immutable control SHA, expected start-main SHA,
implementation branch and batch manifest.

## Source acquisition

Use the `application-ci` artifact whose name is exactly:

`sandbox-bundle-<expected-start-main-sha>`

The artifact is retained for five days.

After extraction, verify:

- `.sandbox/MANIFEST.txt` says `repository=buzlet/ah-there-it-is`;
- `source_commit` equals the launcher expected start-main SHA;
- the artifact's GitHub run/ref metadata is present;
- local Git status is clean;
- local tag `sandbox-base` exists.

The artifact contains a synthetic local Git baseline. Its local commit SHA is not
the GitHub upstream SHA; `.sandbox/MANIFEST.txt` is the binding between them.

If the exact artifact expired, rerun application CI for that exact GitHub commit
or issue a new batch from a current main. Do not silently use a different SHA.

## Workdir and isolation

Extract into exactly the issued directory under `/mnt/data/`.

Do not edit another sandbox checkout.

Do not depend on `/tmp` for durable task state or handoff output.

All edits, tests, generated review material and local Git checkpoints remain
inside the issued workdir until publication/handoff.

## Dependencies

The sandbox image currently provides Python 3.13 and the project's runtime/test
dependencies globally.

Run exactly:

`make sandbox-bootstrap`

before Python work.

That target:

- creates `.venv` with `--system-site-packages`;
- installs only the bundled `wheel` package with `--no-index`;
- installs this project locally with `--no-build-isolation --no-deps`;
- runs `pip check`.

Do not use online pip/uv, curl/wget, shell GitHub access or ad-hoc dependency
downloads.

If bootstrap reports a missing or incompatible preinstalled dependency, stop and
report the sandbox-image mismatch. Do not conceal it by changing project
dependencies or downloading a replacement package unless the task explicitly
authorizes that change.

The project does not require the Python `build` package.

## Command surface

GNU Make is canonical.

Use:

- `.venv/bin/python ...` for direct Python;
- `make <target>` for repeated project checks.

Do not install or invoke `just`.

The same manifest-focused/full-local rules from v8 apply. For a manifest with
`full_local_required: true`, the canonical local sequence is:

```text
make check
make migration-check
make corpus-check
make scenario-check
make scenario-eval
make retrieval-eval
```

## Git and publication

Use the synthetic local Git repository for diff review and local task checkpoints.

The upstream implementation branch is still a real GitHub branch based on the
launcher-declared upstream start-main SHA. GitHub reads/writes use the GitHub
connector, not shell network access.

When the connector is available, publish the implementation changes/checkpoints
to the issued GitHub branch and use GitHub PR/CI normally.

If connector publication is unavailable, export a complete patch/handoff relative
to `sandbox-base` into `/mnt/data` and explicitly report that the remote branch,
PR and CI are still pending. Never report local synthetic commits as upstream
GitHub commits.

## Verification authority

Sandbox verification currently runs on Python 3.13 because that is the sandbox
runtime.

Python 3.12 remains the authoritative application CI compatibility target.

A sandbox implementation is not merge-ready until the exact remote PR head passes
the normal authoritative CI checks.

## Artifact contents

The sandbox bundle intentionally contains active project/runtime material and
excludes `agent-tasks/archive/`.

Do not reconstruct old batches by guessing missing archive content.
