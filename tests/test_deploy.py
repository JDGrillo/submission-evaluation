from __future__ import annotations

from pathlib import Path

from submission_evaluation.deploy import main


def test_deploy_main_dry_run_writes_bundle(monkeypatch, tmp_path: Path) -> None:
    output_bundle = tmp_path / "bundle.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--dry-run",
            "--output-bundle",
            str(output_bundle),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert output_bundle.exists()


def test_deploy_main_requires_command_without_dry_run(monkeypatch, tmp_path: Path) -> None:
    output_bundle = tmp_path / "bundle.json"
    monkeypatch.delenv("FOUNDRY_DEPLOY_COMMAND", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--output-bundle",
            str(output_bundle),
        ],
    )

    exit_code = main()

    assert exit_code == 2
    assert output_bundle.exists()
