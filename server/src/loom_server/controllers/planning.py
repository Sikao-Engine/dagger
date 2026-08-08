"""Planning controllers: ledger + milestones + plan (§13 Ledger & Planning).

  GET  /api/v1/projects/{project_id}/ledger          # paginated items
  POST /api/v1/projects/{project_id}/ledger/refresh   # trigger ItemSource.refresh
  GET  /api/v1/projects/{project_id}/plan             # progress + milestones + suggestions

Refresh calls the domain's ItemSource SPI (same one the scheduler uses),
upserts ledger_items + milestones, and stamps first_seen_run if given.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from litestar import Controller, get, post
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.params import Parameter

from ..deps import AppDeps
from ..domain_runtime import configure_domain
from ..repositories import (
    get_latest_plan,
    get_or_create_project,
    list_ledger_items,
    list_milestones,
    upsert_ledger_items,
    upsert_milestones,
)
from ..schemas import (
    LedgerItemOut,
    LedgerRefreshResult,
    MilestoneOut,
    PlanSnapshot,
)


def _deps(state: State) -> AppDeps:
    return state.deps  # type: ignore[attr-defined]


def _refresh_sync(src: Any, items_dir: str) -> Any:
    async def _do() -> Any:
        return await src.refresh(type("Ws", (), {"root": items_dir})())

    return asyncio.run(_do())


class PlanningController(Controller):
    path = "/api/v1"
    tags = ["planning"]

    @get("/projects/{project_id:str}/ledger")
    async def list_ledger(
        self,
        state: State,
        project_id: str,
        status: Annotated[str | None, Parameter(query="status", required=False)] = None,
        limit: Annotated[int, Parameter(query="limit", required=False)] = 100,
        offset: Annotated[int, Parameter(query="offset", required=False)] = 0,
    ) -> list[LedgerItemOut]:
        deps = _deps(state)
        with deps.session_factory() as session:
            rows = list_ledger_items(
                session,
                project_id=project_id,
                status=status,
                limit=limit,
                offset=offset,
            )
            return [LedgerItemOut.model_validate(r) for r in rows]

    @post("/projects/{project_id:str}/ledger/refresh")
    async def refresh_ledger(
        self,
        state: State,
        project_id: str,
        data: dict[str, Any],
    ) -> LedgerRefreshResult:
        """Body: {domain_id, items_dir, first_seen_run?}."""
        import anyio

        deps = _deps(state)
        domain_id = str(data.get("domain_id", ""))
        items_dir = str(data.get("items_dir", ""))
        first_seen_run = data.get("first_seen_run")
        if not domain_id or not items_dir:
            raise NotFoundException(detail="domain_id and items_dir required")
        reg = deps.runtime.get(domain_id)

        def _do() -> tuple[int, int]:
            configure_domain(deps.runtime, domain_id, source_dir=items_dir)
            src = reg.plugin.item_source()
            snap = _refresh_sync(src, items_dir)
            with deps.session_factory() as session:
                get_or_create_project(session, project_id=project_id, name=project_id)
                n_items = upsert_ledger_items(
                    session,
                    project_id=project_id,
                    items=[
                        {
                            "id": i.id,
                            "seq": i.seq,
                            "title": i.title,
                            "payload": dict(getattr(i, "payload", {})),
                        }
                        for i in snap.items
                    ],
                    first_seen_run=first_seen_run,
                )
                n_ms = upsert_milestones(
                    session,
                    project_id=project_id,
                    milestones=[
                        {"name": m.name, "boundary_item_id": m.boundary_item_id}
                        for m in snap.milestones
                    ],
                )
                session.commit()
            return n_items, n_ms

        n_items, n_ms = await anyio.to_thread.run_sync(_do)
        return LedgerRefreshResult(
            project_id=project_id,
            domain_id=domain_id,
            items_upserted=n_items,
            milestones_upserted=n_ms,
        )

    @get("/projects/{project_id:str}/plan")
    async def get_plan(self, state: State, project_id: str) -> PlanSnapshot:
        deps = _deps(state)
        with deps.session_factory() as session:
            items = list_ledger_items(session, project_id=project_id, limit=10000)
            by_status: dict[str, int] = {}
            for it in items:
                by_status[it.status] = by_status.get(it.status, 0) + 1
            milestones = [
                MilestoneOut.model_validate(m)
                for m in list_milestones(session, project_id=project_id)
            ]
            latest = get_latest_plan(session, project_id=project_id)
            latest_plan = None
            if latest is not None:
                from ..schemas import PlanOut

                latest_plan = PlanOut(
                    project_id=project_id,
                    snapshot=dict(latest.snapshot),
                    suggestions=list(latest.suggestions),
                    refreshed_at=latest.refreshed_at,
                )
        return PlanSnapshot(
            project_id=project_id,
            total_items=len(items),
            by_status=by_status,
            milestones=milestones,
            suggestions=latest_plan.suggestions if latest_plan else [],
            latest_plan=latest_plan,
        )


__all__ = ["PlanningController"]
