from __future__ import annotations

from pathlib import Path

from submission_evaluation.deployment_config import (
    REQUIRED_AGENTS,
    load_agent_manifests,
    load_env_schema,
    validate_manifest_environment,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_load_agent_manifests_has_all_required_agents() -> None:
    manifests = load_agent_manifests(_repo_root() / "deploy" / "foundry" / "agents")

    assert sorted(manifest.name for manifest in manifests) == list(REQUIRED_AGENTS)


def test_agent_manifests_define_resource_and_health_settings() -> None:
    manifests = load_agent_manifests(_repo_root() / "deploy" / "foundry" / "agents")

    for manifest in manifests:
        assert manifest.resources.cpu_millicores > 0
        assert manifest.resources.memory_mib > 0
        assert manifest.resources.tpm > 0
        assert manifest.health_check.endpoint == f"/health/{manifest.name}"
        assert manifest.health_check.command


def test_env_schema_covers_all_manifest_variables() -> None:
    manifests = load_agent_manifests(_repo_root() / "deploy" / "foundry" / "agents")
    env_schema = load_env_schema(_repo_root() / "deploy" / "foundry" / "env.schema.json")

    validate_manifest_environment(manifests, env_schema)
