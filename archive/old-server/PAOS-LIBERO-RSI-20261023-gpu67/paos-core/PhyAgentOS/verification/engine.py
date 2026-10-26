"""Stateless model-backed semantic verification."""

from __future__ import annotations

from typing import Any
from PhyAgentOS.providers.structured import complete_typed
from PhyAgentOS.verification.contracts import VerificationVerdict


class VerificationEngine:
    def __init__(self, *, provider: Any, model: str, timeout_s: float = 180.0) -> None:
        self.provider = provider
        self.model = model
        self.timeout_s = float(timeout_s)

    async def complete(self, *, system_prompt: str, content: list[dict[str, Any]]) -> dict:
        verdict = await complete_typed(
            provider=self.provider, model=self.model, result_type=VerificationVerdict,
            system_prompt=system_prompt, user_content=content, timeout_s=self.timeout_s,
        )
        return verdict.model_dump(mode="json")
