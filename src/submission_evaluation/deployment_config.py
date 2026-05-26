from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

REQUIRED_AGENTS = (
    "analysis",
    "ingestion",
    "orchestrator",
    "report",
    "research",
    "validation",
)


@dataclass(frozen=True)
class ResourceRequirements:
    cpu_millicores: int
    memory_mib: int
    tpm: int


@dataclass(frozen=True)
class HealthCheckConfig:
    endpoint: str
    check_type: str
    command: tuple[str, ...]
    interval_seconds: int
    timeout_seconds: int
    failure_threshold: int


@dataclass(frozen=True)
class AgentManifestConfig:
    name: str
    module: str
    class_name: str
    resources: ResourceRequirements
    health_check: HealthCheckConfig
    required_env: tuple[str, ...]
    secret_env: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "runtime": {
                "module": self.module,
                "class": self.class_name,
            },
            "resources": {
                "cpuMillicores": self.resources.cpu_millicores,
                "memoryMiB": self.resources.memory_mib,
                "tpm": self.resources.tpm,
            },
            "healthCheck": {
                "endpoint": self.health_check.endpoint,
                "type": self.health_check.check_type,
                "command": list(self.health_check.command),
                "intervalSeconds": self.health_check.interval_seconds,
                "timeoutSeconds": self.health_check.timeout_seconds,
                "failureThreshold": self.health_check.failure_threshold,
            },
            "environment": {
                "required": list(self.required_env),
                "secrets": list(self.secret_env),
            },
        }


def _ensure_int(value: Any, field: str, path: Path) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path}: {field} must be a positive integer")
    return value


def _ensure_str(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {field} must be a non-empty string")
    return value


def _ensure_str_list(value: Any, field: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{path}: {field} must be a list of non-empty strings")
    return tuple(value)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected top-level object")
    return data


def parse_agent_manifest(path: Path) -> AgentManifestConfig:
    data = _load_yaml(path)
    spec = data.get("spec")
    if not isinstance(spec, dict):
        raise ValueError(f"{path}: missing spec")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: missing metadata")
    name = _ensure_str(metadata.get("name"), "metadata.name", path)

    runtime = spec.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError(f"{path}: missing spec.runtime")
    module = _ensure_str(runtime.get("module"), "spec.runtime.module", path)
    class_name = _ensure_str(runtime.get("class"), "spec.runtime.class", path)

    resources_data = spec.get("resources")
    if not isinstance(resources_data, dict):
        raise ValueError(f"{path}: missing spec.resources")
    resources = ResourceRequirements(
        cpu_millicores=_ensure_int(resources_data.get("cpuMillicores"), "spec.resources.cpuMillicores", path),
        memory_mib=_ensure_int(resources_data.get("memoryMiB"), "spec.resources.memoryMiB", path),
        tpm=_ensure_int(resources_data.get("tpm"), "spec.resources.tpm", path),
    )

    health_data = spec.get("healthCheck")
    if not isinstance(health_data, dict):
        raise ValueError(f"{path}: missing spec.healthCheck")
    endpoint = _ensure_str(health_data.get("endpoint"), "spec.healthCheck.endpoint", path)
    if not endpoint.startswith("/health/"):
        raise ValueError(f"{path}: health check endpoint must start with /health/")

    health_check = HealthCheckConfig(
        endpoint=endpoint,
        check_type=_ensure_str(health_data.get("type"), "spec.healthCheck.type", path),
        command=_ensure_str_list(health_data.get("command"), "spec.healthCheck.command", path),
        interval_seconds=_ensure_int(
            health_data.get("intervalSeconds"), "spec.healthCheck.intervalSeconds", path
        ),
        timeout_seconds=_ensure_int(
            health_data.get("timeoutSeconds"), "spec.healthCheck.timeoutSeconds", path
        ),
        failure_threshold=_ensure_int(
            health_data.get("failureThreshold"), "spec.healthCheck.failureThreshold", path
        ),
    )

    environment_data = spec.get("environment")
    if not isinstance(environment_data, dict):
        raise ValueError(f"{path}: missing spec.environment")

    required_env = _ensure_str_list(environment_data.get("required", []), "spec.environment.required", path)
    secret_env = _ensure_str_list(environment_data.get("secrets", []), "spec.environment.secrets", path)

    return AgentManifestConfig(
        name=name,
        module=module,
        class_name=class_name,
        resources=resources,
        health_check=health_check,
        required_env=required_env,
        secret_env=secret_env,
    )


def load_agent_manifests(manifest_dir: Path) -> list[AgentManifestConfig]:
    manifest_paths = sorted(manifest_dir.glob("*.yaml"))
    manifests = [parse_agent_manifest(path) for path in manifest_paths]
    names = sorted(manifest.name for manifest in manifests)

    if names != list(REQUIRED_AGENTS):
        raise ValueError(
            "Manifest set mismatch. "
            f"Expected {list(REQUIRED_AGENTS)}, found {names}"
        )

    return manifests


def load_env_schema(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected top-level object")

    properties = data.get("properties")
    required = data.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError(f"{path}: schema must contain properties object and required list")

    return data


def validate_manifest_environment(manifests: list[AgentManifestConfig], env_schema: dict[str, Any]) -> None:
    properties = env_schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("Environment schema properties must be an object")

    declared = set(properties.keys())
    secret_declared = {
        key
        for key, spec in properties.items()
        if isinstance(spec, dict) and spec.get("x-secret") is True
    }

    referenced = set()
    referenced_secrets = set()
    for manifest in manifests:
        referenced.update(manifest.required_env)
        referenced.update(manifest.secret_env)
        referenced_secrets.update(manifest.secret_env)

    undeclared = sorted(referenced - declared)
    if undeclared:
        raise ValueError(f"Manifest references undeclared environment variables: {undeclared}")

    not_marked_secret = sorted(referenced_secrets - secret_declared)
    if not_marked_secret:
        raise ValueError(
            "Manifest secret env vars must be marked with x-secret in schema: "
            f"{not_marked_secret}"
        )
