from __future__ import annotations

import argparse
import json
from json import JSONDecodeError

from .clients import run_connectivity_checks
from .config import AppConfig
from .orchestrator import build_default_orchestrator
from .pipeline import InputDirectoryAccessError, run_pipeline_monitor
from .runtime import AgentFrameworkRuntime, initialize_foundry_runtime


def _print_connectivity(config: AppConfig, probe: bool) -> None:
    checks = run_connectivity_checks(config, probe=probe)
    for name, result in checks.items():
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {name}: {result.detail}")


def _register_agents(runtime: AgentFrameworkRuntime) -> None:
    orchestrator = build_default_orchestrator()
    runtime.register("orchestrator", orchestrator)
    for agent in orchestrator.pipeline:
        runtime.register(agent.name, agent)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submission evaluation bootstrap runner"
    )
    parser.add_argument(
        "--check-connections",
        action="store_true",
        help="Run configuration connectivity checks for Azure OpenAI and Web Search",
    )
    parser.add_argument(
        "--live-probe",
        action="store_true",
        help="Run live HTTP probes for Azure OpenAI and Web Search endpoints",
    )
    parser.add_argument(
        "--discover-agents",
        action="store_true",
        help="List registered agent names",
    )
    parser.add_argument(
        "--payload",
        default="{}",
        help="Optional JSON payload passed through the no-op agent pipeline",
    )
    parser.add_argument(
        "--monitor-once",
        action="store_true",
        help="Run a single input-directory polling cycle and process one discovered submission batch",
    )
    parser.add_argument(
        "--monitor-loop",
        action="store_true",
        help="Continuously poll the input directory and process discovered submission batches",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1.0,
        help="Polling interval for monitor loop mode",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Maximum concurrent submission runs for input monitoring",
    )
    args = parser.parse_args()

    config = AppConfig.from_env()
    try:
        config.ensure_directories()
    except OSError as exc:
        print(f"[FAIL] Unable to access configured directories: {exc}")
        return 3
    runtime_status = initialize_foundry_runtime()
    print(
        f"[INFO] foundry_sdk_available={runtime_status.foundry_sdk_available} "
        f"foundry_initialized={runtime_status.foundry_initialized}"
    )

    registry = AgentFrameworkRuntime()
    _register_agents(registry)

    if args.discover_agents:
        print(json.dumps({"agents": registry.discover_agents()}, indent=2))

    if args.check_connections:
        _print_connectivity(config, probe=args.live_probe)

    if args.monitor_once or args.monitor_loop:
        try:
            runs = run_pipeline_monitor(
                input_dir=config.input_dir,
                processed_dir=config.processed_dir,
                poll_interval_seconds=args.poll_interval_seconds,
                max_workers=args.max_workers,
                continuous=args.monitor_loop,
            )
        except InputDirectoryAccessError as exc:
            print(f"[FAIL] {exc}")
            return 3

        if args.monitor_once:
            print(json.dumps({"runs": runs}, indent=2))
            return 0

    try:
        payload = json.loads(args.payload)
    except JSONDecodeError as exc:
        print(f"[FAIL] Invalid JSON payload: {exc}")
        return 2

    orchestrator = build_default_orchestrator()
    response = orchestrator.invoke(payload)
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
