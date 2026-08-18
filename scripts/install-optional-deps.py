#!/usr/bin/env python3
"""Install every optional dependency declared in hermes-agent's pyproject.toml.

WHY THIS EXISTS
---------------
`pip install -e ".[all]"` only resolves the `all` extra, which on
hermes-agent expands to just 9 of the 44 declared extras. Everything
else — anthropic, elevenlabs, exa-py, firecrawl-py, fal-client, mem0ai,
supermemory, python-telegram-bot, slack-bolt, lark-oapi, dingtalk-stream,
mautrix, modal, vercel, boto3, azure-identity, ... — is simply absent
from a freshly provisioned seat venv.

That absence is invisible until the day someone switches the matching
feature on. Then the gateway raises ImportError deep inside agent init,
every message in that seat fails with "unexpected error", and the
launchd job still reports perfectly healthy.

Verified on maclab 2026-08-16: flipping providers.<name>.api_mode to
anthropic_messages caused 7 minutes of total DM outage, purely because
the `anthropic` package had never been installed into that seat's venv.

DESIGN NOTES
------------
* Installs one spec at a time. A single platform-unavailable wheel
  (onnxruntime pin with no macOS x86_64 build, ai-edge-litert 2.x which
  is arm64-only) must not abort the other 60 packages.
* Skips anything already importable, so re-runs are cheap and the
  playbook can report accurate changed/unchanged state.
* Emits machine-readable JSON on the last line for Ansible to parse.
* Exit code is 0 even when some packages are unavailable — an
  unbuildable wheel on this platform is information, not a provisioning
  failure. Genuine errors (bad pyproject, missing interpreter) exit 1.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import subprocess
import sys
import tomllib

# Distribution names that differ from the importable module name, or that
# carry extras in the spec. We only ever need the distribution name to
# test presence, so strip everything after the first delimiter.
_SPEC_SPLIT = re.compile(r"[=<>!~;\[\s]")


def spec_to_dist(spec: str) -> str:
    """'mautrix[encryption]==0.21.0' -> 'mautrix'"""
    return _SPEC_SPLIT.split(spec.strip(), 1)[0].strip()


def collect_specs(pyproject: str) -> list[str]:
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    extras = data["project"].get("optional-dependencies", {})
    specs: set[str] = set()
    for group in extras.values():
        for spec in group:
            # 'hermes-agent[cron]' style self-references are meta-extras,
            # not real distributions — they expand to other groups we
            # already walk.
            if spec.startswith("hermes-agent["):
                continue
            specs.add(spec)
    return sorted(specs)


def is_installed(dist: str) -> bool:
    try:
        md.version(dist)
        return True
    except md.PackageNotFoundError:
        return False
    except Exception:
        return False


def install(python: str, spec: str, timeout: int) -> tuple[bool, str]:
    proc = subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade-strategy",
            "only-if-needed",
            spec,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode == 0:
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    reason = next((ln for ln in reversed(tail) if "ERROR" in ln or "error:" in ln), "")
    return False, reason[:300]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pyproject", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument(
        "--check",
        action="store_true",
        help="report coverage without installing anything",
    )
    args = ap.parse_args()

    try:
        specs = collect_specs(args.pyproject)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        print(f"FATAL: cannot read {args.pyproject}: {exc}", file=sys.stderr)
        return 1

    already: list[str] = []
    installed: list[str] = []
    unavailable: list[dict[str, str]] = []

    for spec in specs:
        dist = spec_to_dist(spec)
        if is_installed(dist):
            already.append(dist)
            continue
        if args.check:
            unavailable.append({"spec": spec, "reason": "not installed (check mode)"})
            continue
        ok, reason = install(args.python, spec, args.timeout)
        if ok:
            installed.append(dist)
        else:
            unavailable.append({"spec": spec, "reason": reason})

    summary = {
        "total": len(specs),
        "already_present": len(already),
        "newly_installed": len(installed),
        "unavailable": len(unavailable),
        "installed_names": installed,
        "unavailable_detail": unavailable,
        "changed": bool(installed),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
