"""Agent process controllers: agentcli serve process management (for M6 UI).

GET  /api/v1/agents/processes          # list managed agentcli processes
POST /api/v1/agents/processes/{key}/stop  # stop one process
POST /api/v1/agents/processes/stop-all   # stop all
GET  /api/v1/agents/processes/status     # human-readable status text
"""

from __future__ import annotations

from litestar import Controller, get, post
from litestar.datastructures import State
from litestar.exceptions import NotFoundException

from ..deps import AppDeps
from ..schemas import ManagedProcessOut


def _deps(state: State) -> AppDeps:
    return state.deps  # type: ignore[attr-defined]


class AgentsController(Controller):
    path = "/api/v1"
    tags = ["agents"]

    @get("/agents/processes")
    async def list_processes(self, state: State) -> list[ManagedProcessOut]:
        deps = _deps(state)
        return [
            ManagedProcessOut(**p.to_dict())
            for p in deps.process_manager.list_processes()
        ]

    @get("/agents/processes/status")
    async def status_text(self, state: State) -> dict[str, str]:
        deps = _deps(state)
        return {"status": deps.process_manager.get_status_text()}

    @post("/agents/processes/{key:str}/stop")
    async def stop_process(self, state: State, key: str) -> dict[str, str]:
        deps = _deps(state)
        ok, msg = await deps.process_manager.stop_async(key)
        if not ok:
            raise NotFoundException(detail=msg)
        return {"key": key, "message": msg}

    @post("/agents/processes/stop-all")
    async def stop_all(self, state: State) -> dict[str, int]:
        deps = _deps(state)
        count = await _stop_all_async(deps)
        return {"stopped": count}


async def _stop_all_async(deps: AppDeps) -> int:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, deps.process_manager.stop_all)


__all__ = ["AgentsController"]
