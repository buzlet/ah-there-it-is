#!/usr/bin/env python3
"""Verify declared project requirements in the sandbox environment."""

from __future__ import annotations

import importlib.metadata
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    with (project / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)

    project_data = data["project"]
    python_spec = SpecifierSet(project_data.get("requires-python", ""))
    python_version = ".".join(map(str, sys.version_info[:3]))
    failures: list[str] = []

    if python_version not in python_spec:
        failures.append(
            f"python {python_version} does not satisfy requires-python {python_spec}"
        )

    raw_requirements = list(project_data.get("dependencies", []))
    raw_requirements.extend(
        project_data.get("optional-dependencies", {}).get("test", [])
    )
    raw_requirements.extend(data.get("build-system", {}).get("requires", []))

    seen: set[str] = set()
    for raw in raw_requirements:
        requirement = Requirement(raw)
        key = requirement.name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"missing {requirement}")
            continue
        if requirement.specifier and version not in requirement.specifier:
            failures.append(
                f"{requirement.name} {version} does not satisfy {requirement.specifier}"
            )
            continue
        print(f"ok {requirement.name} {version}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
