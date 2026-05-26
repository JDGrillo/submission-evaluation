from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

from .deployment_config import (
    load_agent_manifests,
    load_env_schema,
    validate_manifest_environment,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_manifest_dir() -> Path:
    return _repo_root() / "deploy" / "foundry" / "agents"


def _default_env_schema_path() -> Path:
    return _repo_root() / "deploy" / "foundry" / "env.schema.json"


def _default_output_bundle_path() -> Path:
    return _repo_root() / "output" / "foundry" / "deployment-bundle.json"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Foundry deployment wrapper")
    parser.add_argument(
        "--manifest-dir",
        default=str(_default_manifest_dir()),
        help="Directory containing Foundry agent manifests",
    )
    parser.add_argument(
        "--env-schema",
        default=str(_default_env_schema_path()),
        help="Path to Foundry environment/secrets schema",
    )
    parser.add_argument(
        "--output-bundle",
        default=str(_default_output_bundle_path()),
        help="Where to write the deployment bundle JSON",
    )
    parser.add_argument(
        "--execute-command",
        default="",
        help=(
            "Command to execute for deployment. "
            "Use {bundle} placeholder for the bundle path, or provide a command "
            "that accepts the bundle path as the final argument."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and generate deployment bundle without invoking external deployment command",
    )
    return parser


def _resolve_command(execute_command: str) -> str:
    return execute_command or os.getenv("FOUNDRY_DEPLOY_COMMAND", "")


def _run_deploy_command(command_template: str, bundle_path: Path) -> int:
    if "{bundle}" in command_template:
        command = command_template.replace("{bundle}", str(bundle_path))
        completed = subprocess.run(command, shell=True, check=False)
        return completed.returncode

    argv = shlex.split(command_template, posix=False)
    argv.append(str(bundle_path))
    completed = subprocess.run(argv, check=False)
    return completed.returncode


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        manifest_dir = Path(args.manifest_dir)
        env_schema_path = Path(args.env_schema)
        output_bundle_path = Path(args.output_bundle)

        manifests = load_agent_manifests(manifest_dir)
        env_schema = load_env_schema(env_schema_path)
        validate_manifest_environment(manifests, env_schema)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Deployment configuration validation failed: {exc}")
        return 1

    bundle = {
        "deployment": "submission-evaluation",
        "manifestDirectory": str(manifest_dir),
        "envSchemaPath": str(env_schema_path),
        "agents": [manifest.to_dict() for manifest in manifests],
    }

    try:
        output_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        output_bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[FAIL] Could not write deployment bundle: {exc}")
        return 1

    print(
        f"[INFO] Validated {len(manifests)} Foundry agent manifests and wrote bundle to "
        f"{output_bundle_path}"
    )

    if args.dry_run:
        print("[INFO] Dry run complete. No deployment command was invoked.")
        return 0

    command_template = _resolve_command(args.execute_command)
    if not command_template:
        print(
            "[FAIL] No deployment command configured. Set FOUNDRY_DEPLOY_COMMAND or pass "
            "--execute-command."
        )
        return 2

    try:
        return _run_deploy_command(command_template, output_bundle_path)
    except OSError as exc:
        print(f"[FAIL] Deployment command execution failed: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
