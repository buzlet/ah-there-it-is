#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./bootstrap-sandbox.sh [--python PYTHON]

Run this script from the extracted sandbox bundle root.

It creates source/.venv and installs the project, test dependencies and coverage
strictly from the bundled wheelhouse. No network access and no Python 'build'
package are required.
EOF
}

python_cmd="python3"
while (($#)); do
    case "$1" in
        --python)
            shift
            python_cmd="${1:?--python requires a value}"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$root/source"

if [[ ! -f "$source_dir/pyproject.toml" ]]; then
    echo "run from an extracted ah-there-it-is sandbox bundle" >&2
    exit 2
fi

read -r py_major py_minor < <(
    "$python_cmd" - <<'PY'
import sys
print(sys.version_info.major, sys.version_info.minor)
PY
)

case "$py_major.$py_minor" in
    3.12) wheelhouse="$root/wheelhouse/py312" ;;
    3.13) wheelhouse="$root/wheelhouse/py313" ;;
    *)
        echo "unsupported sandbox Python $py_major.$py_minor; bundle contains 3.12/3.13 wheels" >&2
        exit 2
        ;;
esac

version="$("$python_cmd" - <<PY
import tomllib
with open("$source_dir/pyproject.toml", "rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
)"

rm -rf "$source_dir/.venv"
"$python_cmd" -m venv "$source_dir/.venv"

"$source_dir/.venv/bin/python" -m pip install     --no-index     --find-links="$wheelhouse"     "ah-there-it-is[test]==$version"     'coverage>=7,<8'

"$source_dir/.venv/bin/python" - <<'PY'
import fastapi
import pydantic
import sqlalchemy
import alembic
import httpx
import pytest
print("offline environment ready")
print("fastapi", fastapi.__version__)
print("pydantic", pydantic.__version__)
print("sqlalchemy", sqlalchemy.__version__)
print("alembic", alembic.__version__)
print("httpx", httpx.__version__)
print("pytest", pytest.__version__)
PY

echo
echo "Ready:"
echo "  cd $source_dir"
echo "  ../bin/just check"
echo "  ../bin/just migration-check"
echo "  ../bin/just corpus-check"
echo "  ../bin/just scenario-check"
echo "  ../bin/just scenario-eval"
echo "  ../bin/just retrieval-eval"
