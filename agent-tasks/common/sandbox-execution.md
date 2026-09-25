# Sandbox execution rules — legacy v8

This file is retained only because batches already issued under v8 may reference
it.

New v9 batches do not use this file. Their sandbox environment is defined by:

`agent-tasks/executors/chatgpt-sandbox.md`

Do not migrate an in-flight v8 batch from this document to the v9 executor profile
mid-execution.

---

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
- the artifact's GitHub run/ref metadata is present.

Then run `make sandbox-bootstrap` before edits. Bootstrap creates the synthetic
local Git repository, clean baseline commit and `sandbox-base` tag locally. The
synthetic commit SHA is not the GitHub upstream SHA; `.sandbox/MANIFEST.txt` is
the binding between them.

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

- creates a local `.venv`;
- bridges the preinstalled `/opt/pyvenv` site-packages into that venv through a local `.pth` file;
- installs only this project from local source with `--no-index --no-build-isolation --no-deps`;
- runs a project-scoped requirement check against `pyproject.toml`.

No dependency wheelhouse is shipped in the artifact. The sandbox's existing
`setuptools` backend is sufficient to build the project wheel; the Python
`build` package is not required.

Do not use online pip/uv, curl/wget, shell GitHub access or ad-hoc dependency
downloads.

The requirement check intentionally ignores unrelated conflicts elsewhere in the
large preinstalled sandbox environment and validates only this project's runtime,
test and build-system requirements.

If bootstrap reports a missing or incompatible declared dependency, stop and
report the sandbox-image mismatch. Do not conceal it by changing project
dependencies or downloading a replacement package unless the task explicitly
authorizes that change.


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

Use the synthetic local Git repository created by `make sandbox-bootstrap` for diff review and local task checkpoints.

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

