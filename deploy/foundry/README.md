# Foundry Deployment Configuration

This directory contains deployment-ready configuration for all agents used by the submission evaluation pipeline.

## Files
- `deployment.yaml`: Top-level deployment descriptor.
- `agents/*.yaml`: Agent manifests (analysis, ingestion, orchestrator, report, research, validation).
- `env.schema.json`: Environment variable and secret schema.

## Secrets policy
No secrets are stored in code or in manifest files. Secrets are referenced by name in each agent manifest and are marked with `x-secret: true` in `env.schema.json`.

## Validation
Run the deployment wrapper in dry-run mode to validate schema consistency and generate a deployment bundle:

```bash
submission-eval-deploy --dry-run
```
