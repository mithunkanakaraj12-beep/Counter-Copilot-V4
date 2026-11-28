"""CI stays reproducible: locked npm dependencies, pinned actions, read-only access."""

from __future__ import annotations

import json
import re

import yaml

from conftest import HERE

TYPESCRIPT = HERE / "typescript"
WORKFLOW_PATH = HERE.parents[1] / ".github" / "workflows" / "contract.yml"
WORKFLOW = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def load(name: str) -> dict:
    return json.loads((TYPESCRIPT / name).read_text(encoding="utf-8"))


def steps() -> list[dict]:
    return [step for job in WORKFLOW["jobs"].values() for step in job["steps"]]


def test_lockfile_matches_the_exact_pins():
    wanted = load("package.json")["devDependencies"]
    packages = load("package-lock.json")["packages"]
    assert packages[""]["devDependencies"] == wanted
    for name, version in wanted.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), name
        assert packages[f"node_modules/{name}"]["version"] == version


def test_every_locked_package_comes_from_the_registry_with_a_hash():
    packages = load("package-lock.json")["packages"]
    assert len(packages) > 1
    for path, entry in packages.items():
        if path:
            assert entry["resolved"].startswith("https://registry.npmjs.org/"), path
            assert entry["integrity"].startswith("sha512-"), path
            assert not entry.get("hasInstallScript"), path


def test_ci_installs_only_from_the_lockfile():
    commands = " ".join(step.get("run", "") for step in steps())
    assert "npm ci " in commands
    assert not re.search(r"npm (install|i|add|update)\b", commands)
    assert "package-lock.json" not in (TYPESCRIPT / ".gitignore").read_text(encoding="utf-8")


def test_actions_are_pinned_and_permissions_read_only():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    used = [step["uses"] for step in steps() if "uses" in step]
    assert used and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref) for ref in used)
