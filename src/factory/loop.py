#!/usr/bin/env python3
"""Closed validation loop for the DataOps Solutions software factory.

Runs, in order:
  1. Syntax check:    python -m compileall src
  2. Tests:           pytest (skipped if no test_*.py files exist)
  3. Evals/smoke:     python evals/runner.py --offline --compare (skipped if absent)
  4. Secret scan:     hardcoded credentials in the repository

Writes the state to data/factory_audit.json and exits 0 if passed, 1 otherwise.

Iteration model: if a check fails and --repair-cmd is given, that command runs
(e.g. an agent invocation that applies fixes using the error report), then the
checks run again, up to --max-iterations. Without --repair-cmd there is nothing
that can change between runs, so the loop stops after the first failing
iteration and reports next_action for the builder agent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "data" / "factory_audit.json"
DEFAULT_MAX_ITERATIONS = 3
COMMAND_TIMEOUT_S = 300
MAX_OUTPUT_CHARS = 4000
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "data",
}

# Patterns match real-looking values only, so placeholders such as "sk-xxxx"
# or "api_key=<TU_CLAVE>" do not trigger findings.
SECRET_RULES: dict[str, re.Pattern[str]] = {
    "aws_secret": re.compile(r"AWS_SECRET\w*\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{30,}"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "hardcoded_api_key": re.compile(
        r"api_key\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.IGNORECASE
    ),
}


@dataclass
class CheckResult:
    name: str
    status: str  # "passed" | "failed" | "skipped"
    command: str | None = None
    returncode: int | None = None
    output: str = ""


def _command_str(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_command(name: str, cmd: list[str]) -> CheckResult:
    """Run a command from ROOT and classify the result."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name, "failed", _command_str(cmd), None,
            f"timeout after {COMMAND_TIMEOUT_S}s",
        )
    except OSError as exc:
        return CheckResult(name, "failed", _command_str(cmd), None, str(exc))

    output = (proc.stdout + proc.stderr).strip()[-MAX_OUTPUT_CHARS:]
    status = "passed" if proc.returncode == 0 else "failed"
    return CheckResult(name, status, _command_str(cmd), proc.returncode, output)


def iter_text_files(base: Path = ROOT):
    """Yield repository text files, pruning SKIP_DIRS."""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                with path.open("rb") as fh:
                    if b"\x00" in fh.read(2048):
                        continue  # binary file
            except OSError:
                continue
            yield path


def check_compile() -> CheckResult:
    if not (ROOT / "src").is_dir():
        return CheckResult("compileall", "skipped", output="src/ not found")
    return run_command(
        "compileall", [sys.executable, "-m", "compileall", "-q", "src"]
    )


def check_tests() -> CheckResult:
    has_tests = any(
        p.name.startswith("test_") and p.suffix == ".py"
        for p in iter_text_files()
    )
    if not has_tests:
        return CheckResult("pytest", "skipped", output="no test_*.py files found")
    return run_command("pytest", [sys.executable, "-m", "pytest", "-q"])


def check_evals() -> CheckResult:
    runner = ROOT / "evals" / "runner.py"
    if not runner.is_file():
        return CheckResult("evals", "skipped", output="evals/runner.py not found")
    return run_command(
        "evals",
        [sys.executable, str(runner), "--offline", "--compare"],
    )


def check_secrets() -> CheckResult:
    """Scan for hardcoded credentials. Never prints the matched value."""
    findings: list[str] = []
    for path in iter_text_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(lines, start=1):
            for rule, pattern in SECRET_RULES.items():
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno} [{rule}]")

    if findings:
        return CheckResult(
            "secret_scan", "failed",
            output="\n".join(findings[:50]),
        )
    return CheckResult("secret_scan", "passed", output="no hardcoded secrets found")


def run_all_checks() -> list[CheckResult]:
    return [check_compile(), check_tests(), check_evals(), check_secrets()]


def write_report(
    iteration: int,
    max_iterations: int,
    checks: list[CheckResult],
    next_action: str,
) -> dict:
    report = {
        "passed": not any(c.status == "failed" for c in checks),
        "iteration": iteration,
        "max_iterations": max_iterations,
        "checks": [asdict(c) for c in checks],
        "next_action": next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def print_failures(checks: list[CheckResult]) -> None:
    for check in checks:
        if check.status == "failed":
            print(f"[FAIL] {check.name} (exit={check.returncode})", file=sys.stderr)
            if check.command:
                print(f"  command: {check.command}", file=sys.stderr)
            if check.output:
                for line in check.output.splitlines():
                    print(f"  {line}", file=sys.stderr)


def print_summary(checks: list[CheckResult]) -> None:
    for check in checks:
        print(f"[{check.status.upper():7}] {check.name}")


def run_repair(repair_cmd: str, iteration: int) -> int:
    """Run the external repair command with the audit path exposed in the env."""
    env = {**os.environ, "FACTORY_AUDIT_PATH": str(AUDIT_PATH), "FACTORY_ITERATION": str(iteration)}
    print(f"[REPAIR] running: {repair_cmd}")
    try:
        proc = subprocess.run(
            shlex.split(repair_cmd),
            cwd=ROOT,
            env=env,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[REPAIR] could not run repair command: {exc}", file=sys.stderr)
        return 1
    return proc.returncode


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument(
        "--repair-cmd",
        default=None,
        help="Command run between iterations to apply fixes. Reads FACTORY_AUDIT_PATH.",
    )
    args = parser.parse_args(argv)
    if args.max_iterations < 1:
        parser.error("--max-iterations must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    max_iterations = args.max_iterations

    for iteration in range(1, max_iterations + 1):
        print(f"=== iteration {iteration}/{max_iterations} ===")
        checks = run_all_checks()
        print_summary(checks)
        failed = [c for c in checks if c.status == "failed"]

        if not failed:
            write_report(
                iteration, max_iterations, checks,
                next_action="publish: all checks passed; run security-release agent before release",
            )
            print("PASSED")
            return 0

        print_failures(checks)
        last_iteration = iteration == max_iterations
        if last_iteration:
            write_report(
                iteration, max_iterations, checks,
                next_action="stop: max_iterations reached; escalate to human review",
            )
            print(f"FAILED after {max_iterations} iterations", file=sys.stderr)
            return 1

        if not args.repair_cmd:
            write_report(
                iteration, max_iterations, checks,
                next_action="fix: pass these errors to the builder agent (agents/builder.md), then rerun",
            )
            print("FAILED: no --repair-cmd given; stopping. Fix the errors above and rerun.", file=sys.stderr)
            return 1

        write_report(
            iteration, max_iterations, checks,
            next_action="repair: running --repair-cmd, then re-validating",
        )
        run_repair(args.repair_cmd, iteration)

    return 1  # unreachable: loop always returns above


if __name__ == "__main__":
    sys.exit(main())
