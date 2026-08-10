"""dagger_agent: backend-agnostic Agent protocol layer.

The kernel doesn't know about Agent backends. This package defines the
`AgentBackend` Protocol + unified `AgentEvent`, plus a mock and an opencode-http
implementation. The `session_runner` drives the trust loop: send prompt → stream
events → wait for the contract file (never trust SSE idle) → validate → retry.
"""

from __future__ import annotations

from .backend import AgentBackend, AgentEvent, AgentSession
from .backends.mock import MockBackend, MockScript
from .backends.opencode_http import OpencodeHttpBackend
from .contract import ResultContract, ResultValidator
from .opencode import AgentServerProcessManager
from .session_runner import SessionOutcome, SessionRunner
from .taskcard import TaskCard, render_task_card_prompt

__all__ = [
    "AgentBackend",
    "AgentEvent",
    "AgentServerProcessManager",
    "AgentSession",
    "MockBackend",
    "MockScript",
    "OpencodeHttpBackend",
    "ResultContract",
    "ResultValidator",
    "SessionOutcome",
    "SessionRunner",
    "TaskCard",
    "render_task_card_prompt",
]
