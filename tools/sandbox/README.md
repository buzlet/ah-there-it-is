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
- GitHub workflow sources except what the package tests need (currently none);
- AGENTS/HANDOFF;
- existing build/pytest caches;
- a prebuilt virtualenv;
- Python `build` package.

The bootstrap creates a tiny local Git repository around the extracted source
because process-tool tests intentionally verify Git-worktree boundaries.

Python 3.12 remains the project's authoritative CI target. This bundle is only an
additional Python 3.13 sandbox verification surface.

Artifact retention is one day and only the final bundle is uploaded; wheelhouse
intermediates are not uploaded separately.
