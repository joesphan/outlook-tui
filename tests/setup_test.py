"""Regression test for the setup wizard.

Covers the two bugs found while testing it:
  - an explicit --config path that does not exist yet must be created there,
    not fall back to the default config
  - tenant must not be written for non-Microsoft accounts

Run: python tests/setup_test.py
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKS: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    CHECKS.append((label, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + label)


def run_setup(tmp: pathlib.Path, config: pathlib.Path, answers: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(tmp)  # isolate the default config path
    env.pop("OUTLOOK_TUI_CLIENT_ID", None)
    env.pop("OUTLOOK_TUI_CONFIG", None)
    return subprocess.run(
        [sys.executable, "-m", "outlook_tui", "--setup", "--config", str(config)],
        input=answers,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env=env,
        timeout=120,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        config = tmp / "nested" / "cfg.json"

        # Google path: email, provider, host, app password, name
        result = run_setup(tmp, config, "bar@gmail.com\n\n\nsecret-value\nbar acct\n")
        check("wizard exits 0", result.returncode == 0)
        check("config created at the explicit path", config.is_file())

        blob = json.loads(config.read_text(encoding="utf-8"))
        account = blob["accounts"][0]
        check("address stored", account["user"] == "bar@gmail.com")
        check("provider detected from domain", account["provider"] == "google")
        check("app password stored", account["app_password"] == "secret-value")
        check("no tenant for a Google account", "tenant" not in account)
        check("name stored", account["name"] == "bar acct")

        default_config = tmp / "outlook-tui" / "config.json"
        check("default config not touched", not default_config.exists())

        # Missing answer must fail cleanly, not write a broken account
        bad = tmp / "bad.json"
        result = run_setup(tmp, bad, "\n")
        check("empty address rejected", result.returncode == 2)
        check("no file written on failure", not bad.exists())

        # Microsoft path: email, provider, host, tenant, client id, name
        ms = tmp / "ms.json"
        answers = "me@outlook.com\n\n\n\n11111111-2222-3333-4444-555555555555\n\n"
        result = run_setup(tmp, ms, answers)
        check("microsoft setup exits 0", result.returncode == 0)
        if ms.is_file():
            acct = json.loads(ms.read_text(encoding="utf-8"))["accounts"][0]
            check("client id stored", acct.get("client_id", "").startswith("11111111"))
            check("tenant kept for microsoft", acct.get("tenant") == "consumers")
            check("no app password for microsoft", "app_password" not in acct)
        else:
            check("microsoft config created", False)

    failed = [label for label, ok in CHECKS if not ok]
    print()
    if failed:
        print(f"FAILED {len(failed)}/{len(CHECKS)}")
        return 1
    print(f"PASS {len(CHECKS)}/{len(CHECKS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
