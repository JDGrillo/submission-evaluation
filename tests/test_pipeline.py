from __future__ import annotations

from pathlib import Path
from threading import Event, Lock

import pytest

from submission_evaluation.pipeline import InputDirectoryAccessError, SubmissionPipelineMonitor


class _RecordingOrchestrator:
    def __init__(self, calls: list[dict[str, object]], block: Event | None = None) -> None:
        self._calls = calls
        self._block = block

    def invoke(self, payload):
        self._calls.append(dict(payload))
        if self._block is not None:
            self._block.wait(timeout=2)
        return {"status": "ok"}


def _write_supported_files(input_dir: Path, names: list[str]) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (input_dir / name).write_bytes(b"data")


def test_monitor_when_new_files_arrive_should_trigger_single_batch_and_move_processed(tmp_path: Path):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    _write_supported_files(input_dir, ["submission.xlsx", "schedule.pdf"])

    calls: list[dict[str, object]] = []
    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=lambda: _RecordingOrchestrator(calls),
        max_workers=2,
    )

    try:
        results = monitor.run_once(wait=True)
    finally:
        monitor.shutdown()

    assert len(results) == 1
    assert len(calls) == 1
    payload = calls[0]
    file_names = {Path(item).name for item in payload["input_files"]}
    assert file_names == {"submission.xlsx", "schedule.pdf"}

    assert not any(path.is_file() for path in input_dir.iterdir())
    moved = list((processed_dir / str(payload["submission_id"])).iterdir())
    assert {path.name for path in moved} == {"submission.xlsx", "schedule.pdf"}


def test_monitor_when_directory_empty_should_not_trigger(tmp_path: Path):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir(parents=True, exist_ok=True)

    calls: list[dict[str, object]] = []
    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=lambda: _RecordingOrchestrator(calls),
    )

    try:
        results = monitor.run_once(wait=True)
    finally:
        monitor.shutdown()

    assert results == []
    assert calls == []


def test_monitor_when_concurrent_batches_arrive_should_isolate_input_files(tmp_path: Path):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    _write_supported_files(input_dir, ["batch_a.xlsx"])

    calls: list[dict[str, object]] = []
    call_started = Event()
    release_first = Event()
    lock = Lock()
    invocation_count = {"value": 0}

    class _ConcurrentOrchestrator:
        def invoke(self, payload):
            with lock:
                invocation_count["value"] += 1
                index = invocation_count["value"]
            calls.append(dict(payload))
            if index == 1:
                call_started.set()
                release_first.wait(timeout=2)
            return {"status": "ok"}

    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=_ConcurrentOrchestrator,
        max_workers=2,
    )

    try:
        monitor.run_once(wait=False)
        assert call_started.wait(timeout=1)

        _write_supported_files(input_dir, ["batch_b.pdf"])
        monitor.run_once(wait=False)

        release_first.set()
        monitor.collect_finished(wait=True)
    finally:
        monitor.shutdown()

    assert len(calls) == 2
    first_files = {Path(item).name for item in calls[0]["input_files"]}
    second_files = {Path(item).name for item in calls[1]["input_files"]}
    assert first_files == {"batch_a.xlsx"}
    assert second_files == {"batch_b.pdf"}


def test_monitor_when_input_directory_inaccessible_should_raise_clear_error(tmp_path: Path):
    input_dir = tmp_path / "missing"
    processed_dir = tmp_path / "processed"

    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
    )

    with pytest.raises(InputDirectoryAccessError) as exc_info:
        monitor.run_once(wait=True)

    monitor.shutdown()
    assert "inaccessible" in str(exc_info.value).lower()


def test_monitor_when_filename_reused_should_trigger_new_submission(tmp_path: Path):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir(parents=True, exist_ok=True)

    calls: list[dict[str, object]] = []
    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=lambda: _RecordingOrchestrator(calls),
        max_workers=2,
    )

    try:
        (input_dir / "submission.xlsx").write_bytes(b"first")
        first_results = monitor.run_once(wait=True)
        assert len(first_results) == 1

        (input_dir / "submission.xlsx").write_bytes(b"second")
        second_results = monitor.run_once(wait=True)
        assert len(second_results) == 1
    finally:
        monitor.shutdown()

    assert len(calls) == 2
    assert Path(str(calls[0]["input_files"][0])).name == "submission.xlsx"
    assert Path(str(calls[1]["input_files"][0])).name == "submission.xlsx"


def test_monitor_when_unsupported_file_present_should_log_skip_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "notes.txt").write_text("skip", encoding="utf-8")

    calls: list[dict[str, object]] = []
    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        orchestrator_factory=lambda: _RecordingOrchestrator(calls),
    )

    try:
        with caplog.at_level("WARNING"):
            results = monitor.run_once(wait=True)
    finally:
        monitor.shutdown()

    assert results == []
    assert calls == []
    assert "Skipped unsupported file type 'notes.txt'" in caplog.text
