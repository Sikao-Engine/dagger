"""SessionRunner: the trust loop.

send prompt → stream events → wait for the contract result file (NEVER trust
SSE idle) → validate → on failure: inject previous-failure context → retry.

Background-task handling: if the result file says `background_tasks.active`,
we keep waiting (with periodic keepalive) until the Agent flips it to terminal.

This is the kernel that turns unreliable LLM loops into nodes a program can call
and trust. CubeClaw's most valuable pattern, generalized.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from divdag_kernel.state import K, StateStore

from .backend import AgentBackend
from .contract import ResultContract, check_kernel_invariants
from .taskcard import TaskCard, render_task_card_prompt


@dataclass
class SessionOutcome:
    """Outcome of one session run attempt."""

    success: bool
    attempts: int
    final_status: str  # success | failed | blocked | timeout | aborted
    result: ResultContract | None = None
    error: str = ""


@dataclass
class SessionRunner:
    """Drives the trust loop for one Agent node run."""

    backend: AgentBackend
    store: StateStore
    max_retries: int = 3
    idle_timeout_seconds: int = 3600
    keepalive_interval_seconds: int = 30

    async def run(
        self,
        *,
        node_run_id: str,
        node_type: str,
        skill: str,
        declared_writes: tuple[str, ...] | None,
        task_card: TaskCard,
        workdir: str,
        validators: list[Any] | None = None,
    ) -> SessionOutcome:
        """Run the trust loop. Returns the final outcome."""
        attempt = 1
        last_error = ""
        while attempt <= self.max_retries:
            # Allocate the attempt slot in the state store.
            self.store.begin_attempt(node_run_id)
            # Write the task card for this attempt.
            card_key = K.task_card(node_run_id, attempt)
            self.store.write_json(
                card_key,
                task_card.to_body(),
                kind="task_card",
                written_by={"role": "orchestrator"},
            )
            # Render prompt + previous-failure prefix if any.
            prompt = render_task_card_prompt(self.store.path(card_key))
            if last_error:
                prompt = f"上次尝试失败，原因：{last_error}。请先做环境体检再继续。\n" + prompt
            try:
                result = await self._drive_one_attempt(
                    node_run_id=node_run_id,
                    node_type=node_type,
                    skill=skill,
                    attempt=attempt,
                    prompt=prompt,
                    workdir=workdir,
                    declared_writes=declared_writes,
                    validators=validators,
                )
            except TimeoutError:
                last_error = f"timeout after {self.idle_timeout_seconds}s"
                attempt += 1
                continue
            if result is not None and result.success:
                return SessionOutcome(
                    success=True,
                    attempts=attempt,
                    final_status=result.status,
                    result=result,
                )
            last_error = (result.error if result else "") or last_error or "unknown"
            attempt += 1
        return SessionOutcome(
            success=False,
            attempts=self.max_retries,
            final_status="failed",
            error=last_error,
        )

    async def _drive_one_attempt(
        self,
        *,
        node_run_id: str,
        node_type: str,
        skill: str,
        attempt: int,
        prompt: str,
        workdir: str,
        declared_writes: tuple[str, ...] | None,
        validators: list[Any] | None,
    ) -> ResultContract | None:
        """Drive one attempt to terminal state. Raises asyncio.TimeoutError on timeout."""
        endpoint = await self.backend.ensure_ready(workdir)
        session_id = await self.backend.create_session(endpoint)
        # Backends that need node_type to dispatch scripts (e.g. mock) bind it here.
        if hasattr(self.backend, "bind_session_node_type"):
            self.backend.bind_session_node_type(session_id, node_type)  # type: ignore[attr-defined]
        await self.backend.send_prompt(endpoint, session_id, prompt)
        # Stream events to transcript.jsonl. We do NOT trust `idle` — we wait
        # for the result file to flip terminal.
        transcript_key = K.transcript(node_run_id, attempt)
        stream = self.backend.stream_events(endpoint, session_id)

        async def _consume() -> None:
            async for ev in stream:
                self.store.append_jsonl(transcript_key, ev.to_dict())

        consume_task = asyncio.create_task(_consume())
        # Poll the result file.
        result_key = K.result(node_run_id, attempt)
        deadline = asyncio.get_event_loop().time() + self.idle_timeout_seconds
        while True:
            body = self.store.read_json(result_key)
            if body is not None:
                contract = ResultContract.from_body(body)
                # Validate kernel invariants + domain validators.
                errs = check_kernel_invariants(
                    body,
                    node_run_id=node_run_id,
                    node_type=node_type,
                    skill=skill,
                    declared_writes=declared_writes,
                )
                for v in validators or []:
                    errs.extend(v(body, node_run_id=node_run_id))
                if errs:
                    # Body present but invalid — treat as failure, re-prompt.
                    await self.backend.abort(endpoint, session_id)
                    return ResultContract(
                        node_run_id=node_run_id,
                        node_type=node_type,
                        skill=skill,
                        status="failed",
                        success=False,
                        error="; ".join(errs),
                    )
                if contract.is_terminal:
                    consume_task.cancel()
                    return contract
            # Keepalive: tell the backend we're still watching (no-op for mock).
            if asyncio.get_event_loop().time() > deadline:
                await self.backend.abort(endpoint, session_id)
                raise TimeoutError()
            await asyncio.sleep(self.keepalive_interval_seconds)


__all__ = ["SessionOutcome", "SessionRunner"]
