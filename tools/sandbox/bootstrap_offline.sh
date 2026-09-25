#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./bootstrap-sandbox.sh [--python PYTHON]

Run from the extracted sandbox artifact root.

Creates source/.venv and installs the project plus its test/build-backend
requirements strictly from the bundled Python 3.13 wheelhouse.
No network and no Python 'build' package are required.
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
wheelhouse="$root/wheelhouse"

if [[ ! -f "$source_dir/pyproject.toml" ]]; then
    echo "invalid sandbox bundle: source/pyproject.toml is missing" >&2
    exit 2
fi

read -r py_major py_minor < <(
    "$python_cmd" - <<'PY'
import sys
print(sys.version_info.major, sys.version_info.minor)
PY
)

if [[ "$py_major.$py_minor" != "3.13" ]]; then
    echo "this sandbox bundle targets Python 3.13, got $py_major.$py_minor" >&2
    exit 2
fi

version="$("$python_cmd" - <<PY
import tomllib
with open("$source_dir/pyproject.toml", "rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
PY
)"

if [[ ! -d "$source_dir/.git" ]]; then
    git -C "$source_dir" init --initial-branch=main >/dev/null
    git -C "$source_dir" config user.name "Sandbox Bundle"
    git -C "$source_dir" config user.email "sandbox@example.invalid"
    git -C "$source_dir" add .
    git -C "$source_dir" commit -m "sandbox source snapshot" >/dev/null
fi

rm -rf "$source_dir/.venv"
"$python_cmd" -m venv "$source_dir/.venv"

"$source_dir/.venv/bin/python" -m pip install     --no-index     --find-links="$wheelhouse"     "ah-there-it-is[test]==$version"     'setuptools>=68'     wheel

"$source_dir/.venv/bin/python" - <<'PY'
import fastapi
import pydantic
import sqlalchemy
import alembic
import httpx
import pytest
import setuptools
import wheel
print("offline environment ready")
print("fastapi", fastapi.__version__)
print("pydantic", pydantic.__version__)
print("sqlalchemy", sqlalchemy.__version__)
print("alembic", alembic.__version__)
print("httpx", httpx.__version__)
print("pytest", pytest.__version__)
print("setuptools", setuptools.__version__)
print("wheel", wheel.__version__)
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
