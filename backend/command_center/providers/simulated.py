"""Deterministic local stand-in for a model. Costs nothing and is ALWAYS labeled simulated.

Used only when PROVIDER_MODE=simulated or an agent's provider is 'simulated'. It is never a
silent fallback for a missing key.
"""

from __future__ import annotations

import hashlib

from command_center.providers.base import Capabilities, ChatRequest, ChatResponse


class SimulatedAdapter:
    id = "simulated"
    simulated = True

    def __init__(self, persona: str = "agent") -> None:
        self.persona = persona

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities()

    async def generate(self, req: ChatRequest) -> ChatResponse:
        task = req.messages[-1].content if req.messages else ""
        instruction = task.rsplit("YOUR TASK:", 1)[-1].strip().splitlines()[0][:160] if task else ""
        digest = hashlib.sha256(task.encode()).hexdigest()[:8]
        text = (
            f"[Simulated response, no AI model was called] {self.persona} acknowledges the task: "
            f'"{instruction}". Reference {digest}.'
        )
        return ChatResponse(
            text=text,
            input_tokens=max(1, req.prompt_chars() // 4),
            output_tokens=max(1, len(text) // 4),
            model=f"simulated:{req.model}",
            request_id=f"sim-{digest}",
            stop_reason="end_turn",
        )
