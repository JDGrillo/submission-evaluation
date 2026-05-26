# Submission Evaluation

Minimal Python 3.11+ project scaffold for a Foundry/Agent Framework-oriented multi-agent workflow.

## Quick start

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -e .[dev]
```

3. Optional: set environment variables (see `.env.example`).
4. Run connectivity checks and a no-op pipeline:

```bash
python -m submission_evaluation.main --check-connections
python -m submission_evaluation.main --discover-agents
python -m submission_evaluation.main
```

Use `--live-probe` with `--check-connections` to run real HTTP probes.

## Foundry deployment

This repository includes deployment-ready Foundry manifests for all six agents under `deploy/foundry/agents`.

Validate manifests and build a deployment bundle:

```bash
submission-eval-deploy --dry-run
```

Trigger deployment with a single command wrapper:

```bash
submission-eval-deploy --execute-command "foundry deploy apply --config {bundle}"
```

You can also set `FOUNDRY_DEPLOY_COMMAND` and run `submission-eval-deploy` with no additional flags.

## Deployment environment smoke test

Run the deployment smoke harness in local or CI to validate runtime assets:

```bash
submission-eval-smoke
```

Use live endpoint probes when deployed secrets and network access are available:

```bash
submission-eval-smoke --live-probe
```

The smoke report verifies required environment variables, directory initialization and write access,
Azure OpenAI throughput budget assumptions, web-search configuration, and secure secret handling guidance.
