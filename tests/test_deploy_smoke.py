from __future__ import annotations

from submission_evaluation.deploy_smoke import main, run_environment_smoke


def _set_required_env(monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_DIR", str(tmp_path / "input"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
    monkeypatch.setenv("AZURE_OPENAI_TPM_TARGET", "5000")
    monkeypatch.setenv("WEB_SEARCH_ENDPOINT", "https://example.search")
    monkeypatch.setenv("WEB_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("EXPECTED_SUBMISSIONS_PER_DAY", "10")
    monkeypatch.setenv("TOKENS_PER_SUBMISSION", "50000")
    monkeypatch.setenv("PROCESSING_WINDOW_MINUTES", "480")


def test_environment_smoke_passes_with_required_assets(monkeypatch, tmp_path):
    _set_required_env(monkeypatch, tmp_path)

    report = run_environment_smoke(live_probe=False)

    assert report.ok is True
    assert report.required_user_fields == []
    assert all(check.ok for check in report.checks)


def test_environment_smoke_reports_missing_subscription_specific_fields(monkeypatch, tmp_path):
    _set_required_env(monkeypatch, tmp_path)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT")

    report = run_environment_smoke(live_probe=False)

    assert report.ok is False
    assert "AZURE_OPENAI_ENDPOINT" in report.required_user_fields


def test_environment_smoke_fails_when_throughput_inputs_are_not_integers(monkeypatch, tmp_path):
    _set_required_env(monkeypatch, tmp_path)
    monkeypatch.setenv("EXPECTED_SUBMISSIONS_PER_DAY", "ten")

    report = run_environment_smoke(live_probe=False)

    assert report.ok is False
    throughput_checks = [check for check in report.checks if check.name == "throughput:azure-openai-tpm"]
    assert len(throughput_checks) == 1
    assert throughput_checks[0].ok is False
    assert "must be integers" in throughput_checks[0].detail


def test_environment_smoke_fails_when_tpm_is_insufficient(monkeypatch, tmp_path):
    _set_required_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AZURE_OPENAI_TPM_TARGET", "500")

    report = run_environment_smoke(live_probe=False)

    assert report.ok is False
    throughput_checks = [check for check in report.checks if check.name == "throughput:azure-openai-tpm"]
    assert len(throughput_checks) == 1
    assert throughput_checks[0].ok is False
    assert "< required" in throughput_checks[0].detail


def test_smoke_main_returns_failure_when_requirements_missing(monkeypatch):
    for key in [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_TPM_TARGET",
        "WEB_SEARCH_ENDPOINT",
        "WEB_SEARCH_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("sys.argv", ["prog"])

    result = main()

    assert result == 1
