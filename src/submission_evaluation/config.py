from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    input_dir: Path
    processed_dir: Path
    output_dir: Path
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str
    web_search_endpoint: str
    web_search_api_key: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        input_dir = Path(os.getenv("INPUT_DIR", "input"))
        processed_dir_env = os.getenv("PROCESSED_DIR", "")
        processed_dir = (
            Path(processed_dir_env) if processed_dir_env else input_dir / "processed"
        )
        return cls(
            input_dir=input_dir,
            processed_dir=processed_dir,
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
            azure_openai_api_version=os.getenv(
                "AZURE_OPENAI_API_VERSION", "2024-06-01"
            ),
            web_search_endpoint=os.getenv("WEB_SEARCH_ENDPOINT", ""),
            web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", ""),
        )

    def ensure_directories(self) -> None:
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
