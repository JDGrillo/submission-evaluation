from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "status": self.status,
            "payload": self.payload,
        }


class NoOpAgent:
    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status="ok",
            payload={
                "received": payload,
                "message": f"{self.name} no-op completed",
            },
        )
