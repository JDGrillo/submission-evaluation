from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import logging
from threading import Lock
import time
from typing import Any, Callable, Dict, Iterable
from uuid import uuid4

from .orchestrator import build_default_orchestrator


LOGGER = logging.getLogger(__name__)

_SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".pdf"}


class InputDirectoryAccessError(RuntimeError):
    """Raised when the configured input directory cannot be accessed."""


@dataclass(frozen=True)
class SubmissionBatch:
    submission_id: str
    created_at: str
    files: tuple[Path, ...]


class SubmissionPipelineMonitor:
    """Poll-based submission monitor that batches files and invokes orchestrator runs."""

    def __init__(
        self,
        *,
        input_dir: Path,
        processed_dir: Path,
        orchestrator_factory: Callable[[], Any] = build_default_orchestrator,
        max_workers: int = 2,
    ) -> None:
        self._input_dir = input_dir
        self._processed_dir = processed_dir
        self._orchestrator_factory = orchestrator_factory
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
        self._claimed: set[str] = set()
        self._futures: set[Future[Dict[str, Any]]] = set()
        self._lock = Lock()

    def run_once(self, *, wait: bool = True) -> list[Dict[str, Any]]:
        self._validate_input_dir()
        batch_files = self._claim_new_batch()
        if batch_files:
            self._submit_batch(batch_files)
        return self.collect_finished(wait=wait)

    def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        while True:
            self.run_once(wait=False)
            time.sleep(max(0.05, poll_interval_seconds))

    def collect_finished(self, *, wait: bool = False) -> list[Dict[str, Any]]:
        futures = list(self._futures)
        if not futures:
            return []

        if wait:
            for future in futures:
                future.result()
            done = futures
        else:
            done = [future for future in futures if future.done()]

        results: list[Dict[str, Any]] = []
        for future in done:
            self._futures.discard(future)
            results.append(future.result())
        return results

    def active_runs(self) -> int:
        return len(self._futures)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _validate_input_dir(self) -> None:
        if not self._input_dir.exists():
            raise InputDirectoryAccessError(
                f"Input directory '{self._input_dir}' does not exist or is inaccessible"
            )
        if not self._input_dir.is_dir():
            raise InputDirectoryAccessError(f"Input path '{self._input_dir}' is not a directory")
        try:
            list(self._input_dir.iterdir())
        except (PermissionError, OSError) as exc:
            raise InputDirectoryAccessError(
                f"Input directory '{self._input_dir}' is inaccessible: {exc}"
            ) from exc

    def _claim_new_batch(self) -> list[Path]:
        candidates, unsupported = self._scan_input_files(self._input_dir)
        for skipped in unsupported:
            LOGGER.warning("Skipped unsupported file type '%s'", skipped.name)
        if not candidates:
            return []

        with self._lock:
            fresh = [path for path in candidates if self._claim_key(path) not in self._claimed]
            if not fresh:
                return []
            for path in fresh:
                self._claimed.add(self._claim_key(path))
            return fresh

    def _submit_batch(self, files: Iterable[Path]) -> None:
        normalized = tuple(sorted((path.resolve() for path in files), key=lambda path: path.name))
        batch = SubmissionBatch(
            submission_id=f"sub-{uuid4().hex}",
            created_at=datetime.now(timezone.utc).isoformat(),
            files=normalized,
        )
        future = self._executor.submit(self._process_batch, batch)
        self._futures.add(future)

    def _process_batch(self, batch: SubmissionBatch) -> Dict[str, Any]:
        orchestrator = self._orchestrator_factory()
        file_paths = [str(path) for path in batch.files]
        payload: Dict[str, Any] = {
            "submission_id": batch.submission_id,
            "submission_created_at": batch.created_at,
            "input_files": file_paths,
        }
        try:
            result = orchestrator.invoke(payload)
            return {
                "submission_id": batch.submission_id,
                "input_files": file_paths,
                "result": result,
            }
        finally:
            self._move_batch_to_processed(batch)
            with self._lock:
                for path in batch.files:
                    self._claimed.discard(self._claim_key(path))

    def _move_batch_to_processed(self, batch: SubmissionBatch) -> None:
        destination_root = self._processed_dir / batch.submission_id
        destination_root.mkdir(parents=True, exist_ok=True)

        for source_path in batch.files:
            if not source_path.exists() or not source_path.is_file():
                continue
            destination = destination_root / source_path.name
            counter = 1
            while destination.exists():
                destination = destination_root / f"{source_path.stem}_{counter}{source_path.suffix}"
                counter += 1
            source_path.replace(destination)

    @staticmethod
    def _scan_input_files(directory: Path) -> tuple[list[Path], list[Path]]:
        supported: list[Path] = []
        unsupported: list[Path] = []
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() in _SUPPORTED_SUFFIXES:
                supported.append(path)
            else:
                unsupported.append(path)
        return (
            sorted(supported, key=lambda path: path.name),
            sorted(unsupported, key=lambda path: path.name),
        )

    @staticmethod
    def _claim_key(path: Path) -> str:
        return str(path.resolve())


def run_pipeline_monitor(
    *,
    input_dir: Path,
    processed_dir: Path,
    poll_interval_seconds: float,
    max_workers: int,
    continuous: bool,
) -> list[Dict[str, Any]]:
    monitor = SubmissionPipelineMonitor(
        input_dir=input_dir,
        processed_dir=processed_dir,
        max_workers=max_workers,
    )
    try:
        if continuous:
            monitor.run_forever(poll_interval_seconds=poll_interval_seconds)
            return []
        return monitor.run_once(wait=True)
    finally:
        monitor.shutdown()
