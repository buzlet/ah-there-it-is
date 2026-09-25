# Sandbox offline bundle

Purpose: make this repository testable inside the current ChatGPT sandbox, which
has Python 3.13 but no reliable outbound GitHub/PyPI access.

The artifact is intentionally sandbox-specific and minimal.

Included:

- only source/test/runtime files needed by the test suite;
- one Python 3.13 offline wheelhouse;
- setuptools + wheel because tests build the project wheel with no build isolation;
- Linux x86_64 `just`;
- an offline bootstrap script;
- checksums/build metadata.

Not included:

- Python 3.12 wheelhouse;
- project documentation/process archives;
- GitHub workflow sources;
- AGENTS/HANDOFF;
- existing build/pytest caches;
- a prebuilt virtualenv;
- Python `build` package.

The bootstrap creates a tiny local Git repository around the extracted source
because process-tool tests intentionally verify Git-worktree boundaries.

Python 3.12 remains the project's authoritative CI target. This bundle is only an
additional Python 3.13 sandbox verification surface.

Only the final bundle is uploaded. Its retention is one day. After a successful
upload, the workflow deletes older artifacts created by this sandbox-bundle
workflow naming scheme, including obsolete py312/py313 intermediate wheelhouses.
It does not touch unrelated project artifacts.
