from __future__ import annotations

from pathlib import Path

from submission_evaluation.main import main


def test_main_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "--payload", "{not-json"])
    result = main()
    assert result == 2


def test_main_can_discover_agents(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "--discover-agents", "--payload", "{}"])
    result = main()
    assert result == 0


def test_main_when_input_path_is_a_file_should_return_clear_error(monkeypatch, tmp_path: Path):
    input_file = tmp_path / "not-a-directory"
    input_file.write_text("x", encoding="utf-8")
    monkeypatch.setenv("INPUT_DIR", str(input_file))
    monkeypatch.setattr("sys.argv", ["prog", "--payload", "{}"])

    result = main()

    assert result == 3
