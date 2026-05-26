from __future__ import annotations

from submission_evaluation.config import AppConfig


def test_config_reads_paths_from_env(monkeypatch, tmp_path):
    in_dir = tmp_path / "in"
    processed_dir = tmp_path / "processed"
    out_dir = tmp_path / "out"
    monkeypatch.setenv("INPUT_DIR", str(in_dir))
    monkeypatch.setenv("PROCESSED_DIR", str(processed_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(out_dir))

    config = AppConfig.from_env()
    config.ensure_directories()

    assert config.input_dir == in_dir
    assert config.processed_dir == processed_dir
    assert config.output_dir == out_dir
    assert in_dir.exists()
    assert processed_dir.exists()
    assert out_dir.exists()
