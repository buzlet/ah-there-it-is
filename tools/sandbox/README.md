# Sandbox offline bundle

This helper exists only to make the repository executable in the ChatGPT sandbox,
which has no outbound package/GitHub access.

Workflow:

`.github/workflows/sandbox-bundle.yml`

The generated artifact contains:

- a complete tracked source snapshot of the producing commit;
- an offline wheelhouse for Python 3.12;
- an offline wheelhouse for Python 3.13;
- the project wheel plus all runtime/test dependencies and coverage;
- a Linux x86_64 `just` binary installed by `extractions/setup-just@v4`;
- `bootstrap-sandbox.sh`;
- SHA-256 checksums and build metadata.

The bootstrap script does not use the network and does not require the Python
`build` package.

The workflow itself proves that each wheelhouse installs with `--no-index` and
runs the full pytest suite. The final bundle is smoke-tested again with Python
3.13 because that matches the current ChatGPT sandbox runtime.

This is additional verification only. Python 3.12 remains the project's required
CI/test compatibility target.
