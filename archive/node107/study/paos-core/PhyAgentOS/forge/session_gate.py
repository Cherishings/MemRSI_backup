"""Opt-in local handshake: hold a Session's first policy call for real camera capture.

The policy signals readiness before inference and returns no action until PAOS has
persisted the Gateway observation. Each run uses a fresh private directory. The
handshake contains no images or scores; all evidence still comes from Gateway.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from PhyAgentOS.utils.atomic_file import atomic_write_text
from PhyAgentOS.verification.contracts import utc_now


class SessionPreactionGate:
    def __init__(self, directory: str, timeout_s: float) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.timeout_s = timeout_s

    def arm(self, task_id: str, record_id: str, tool_id: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Reusing a handshake could accept stale observations from another episode.
        if any(self.directory.iterdir()):
            raise RuntimeError("Pre-action gate directory must be fresh for each episode")
        token = uuid4().hex
        atomic_write_text(self.directory / "request.json", json.dumps({
            "token": token, "task_id": task_id, "record_id": record_id,
            "tool_id": tool_id, "armed_at": utc_now().isoformat(),
        }))
        return token

    async def wait_ready(self, token: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.timeout_s
        ready = self.directory / "ready.json"
        while asyncio.get_running_loop().time() < deadline:
            if ready.exists():
                value = json.loads(ready.read_text())
                if value.get("token") != token or value.get("policy_calls_completed") != 0:
                    raise RuntimeError("Pre-action gate readiness does not match this task")
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("Policy did not reach its first pre-action observation in time")

    def release(self, token: str, snapshot_ref: str) -> None:
        if not snapshot_ref:
            raise ValueError("Cannot release the policy without persisted before evidence")
        atomic_write_text(self.directory / "release.json", json.dumps({
            "token": token, "snapshot_ref": snapshot_ref,
            "released_at": utc_now().isoformat(),
        }))
