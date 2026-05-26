from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

from .clients import run_connectivity_checks
from .config import AppConfig


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class EnvironmentSmokeReport:
    ok: bool
    checks: List[SmokeCheck]
    required_user_fields: List[str]
    secret_handling_reference: str


def _check_required_env() -> tuple[List[SmokeCheck], List[str]]:
    checks: List[SmokeCheck] = []
    required_fields = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "WEB_SEARCH_ENDPOINT",
        "WEB_SEARCH_API_KEY",
        "AZURE_OPENAI_TPM_TARGET",
    ]
    missing: List[str] = []

    for field in required_fields:
        value = os.getenv(field, "").strip()
        if value:
            checks.append(SmokeCheck(name=f"env:{field}", ok=True, detail="Configured"))
            continue
        checks.append(
            SmokeCheck(
                name=f"env:{field}",
                ok=False,
                detail=(
                    "Missing value. Provide via CI secret store or Azure Key Vault injection."
                ),
            )
        )
        missing.append(field)

    return checks, missing


def _check_directory_access(config: AppConfig) -> List[SmokeCheck]:
    checks: List[SmokeCheck] = []
    config.ensure_directories()

    for directory in (config.input_dir, config.processed_dir, config.output_dir):
        checks.append(_check_writable_directory(directory))

    return checks


def _check_writable_directory(directory: Path) -> SmokeCheck:
    marker = directory / ".smoke-write-check"
    try:
        marker.write_text("ok", encoding="utf-8")
        marker.unlink(missing_ok=True)
        return SmokeCheck(name=f"directory:{directory}", ok=True, detail="Writable")
    except OSError as exc:
        return SmokeCheck(name=f"directory:{directory}", ok=False, detail=str(exc))


def _check_throughput_budget() -> SmokeCheck:
    submissions_value = os.getenv("EXPECTED_SUBMISSIONS_PER_DAY", "10")
    tokens_value = os.getenv("TOKENS_PER_SUBMISSION", "50000")
    window_value = os.getenv("PROCESSING_WINDOW_MINUTES", "480")

    try:
        submissions_per_day = int(submissions_value)
        tokens_per_submission = int(tokens_value)
        processing_window_minutes = int(window_value)
    except ValueError:
        return SmokeCheck(
            name="throughput:azure-openai-tpm",
            ok=False,
            detail=(
                "EXPECTED_SUBMISSIONS_PER_DAY, TOKENS_PER_SUBMISSION, and "
                "PROCESSING_WINDOW_MINUTES must be integers."
            ),
        )

    tpm_value = os.getenv("AZURE_OPENAI_TPM_TARGET", "").strip()
    if not tpm_value:
        return SmokeCheck(
            name="throughput:azure-openai-tpm",
            ok=False,
            detail="Missing AZURE_OPENAI_TPM_TARGET required for throughput verification.",
        )

    try:
        tpm_target = int(tpm_value)
    except ValueError:
        return SmokeCheck(
            name="throughput:azure-openai-tpm",
            ok=False,
            detail="AZURE_OPENAI_TPM_TARGET must be an integer.",
        )

    if submissions_per_day <= 0 or tokens_per_submission <= 0 or processing_window_minutes <= 0:
        return SmokeCheck(
            name="throughput:azure-openai-tpm",
            ok=False,
            detail="Throughput inputs must be positive integers.",
        )

    required_tpm = math.ceil((submissions_per_day * tokens_per_submission) / processing_window_minutes)
    if tpm_target >= required_tpm:
        return SmokeCheck(
            name="throughput:azure-openai-tpm",
            ok=True,
            detail=(
                f"TPM target {tpm_target} >= required {required_tpm} "
                f"for {submissions_per_day} submissions/day."
            ),
        )

    return SmokeCheck(
        name="throughput:azure-openai-tpm",
        ok=False,
        detail=(
            f"TPM target {tpm_target} < required {required_tpm}. "
            "Increase deployment TPM or reduce expected workload."
        ),
    )


def run_environment_smoke(*, live_probe: bool = False) -> EnvironmentSmokeReport:
    config = AppConfig.from_env()
    checks: List[SmokeCheck] = []

    env_checks, missing_fields = _check_required_env()
    checks.extend(env_checks)

    try:
        checks.extend(_check_directory_access(config))
    except OSError as exc:
        checks.append(SmokeCheck(name="directories", ok=False, detail=str(exc)))

    checks.append(_check_throughput_budget())

    connectivity = run_connectivity_checks(config, probe=live_probe)
    for name, result in connectivity.items():
        checks.append(SmokeCheck(name=f"connectivity:{name}", ok=result.ok, detail=result.detail))

    report = EnvironmentSmokeReport(
        ok=all(check.ok for check in checks),
        checks=checks,
        required_user_fields=sorted(set(missing_fields)),
        secret_handling_reference=(
            "Store API keys in environment variables injected by CI secret stores or "
            "Azure Key Vault references. Do not hardcode or commit secrets."
        ),
    )
    return report


def _to_json(report: EnvironmentSmokeReport) -> str:
    payload: Dict[str, object] = {
        "ok": report.ok,
        "required_user_fields": report.required_user_fields,
        "secret_handling_reference": report.secret_handling_reference,
        "checks": [asdict(check) for check in report.checks],
    }
    return json.dumps(payload, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deployment environment smoke test")
    parser.add_argument(
        "--live-probe",
        action="store_true",
        help="Run HTTP connectivity probes against configured Azure OpenAI and Web Search endpoints",
    )
    args = parser.parse_args()

    report = run_environment_smoke(live_probe=args.live_probe)
    print(_to_json(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
