"""App-level dependencies: the singletons wired into the Litestar app state.

Built once at startup (`build_deps`) and attached to `app.state`. Controllers
read them via `request.state.deps`. This avoids per-request provider boilerplate
while keeping the wiring in one auditable place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dagger_agent import AgentServerProcessManager
from dagger_kernel.state import StateStore
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .database import make_engine, make_session_factory
from .domain_runtime import DomainRuntime, assemble_runtime
from .events import EventBus
from .scheduler import Scheduler
from .sse import SSEBroker


@dataclass
class AppDeps:
    """All process-wide singletons the server needs."""

    engine: Engine
    session_factory: sessionmaker
    runtime: DomainRuntime
    scheduler: Scheduler
    bus: EventBus
    broker: SSEBroker
    process_manager: AgentServerProcessManager
    data_dir: Path

    def store_for(self, run_id: str, state_root_rel: str) -> StateStore:
        """Reconstruct a StateStore for a run from its relative state root."""
        return StateStore(self.data_dir / Path(state_root_rel).parent, run_id=run_id)


def build_deps(*, db_url: str, data_dir: Path) -> AppDeps:
    """Assemble all singletons. Called once at app startup."""
    engine = make_engine(db_url)
    session_factory = make_session_factory(engine)
    runtime = assemble_runtime()
    bus = EventBus()
    broker = SSEBroker(bus)
    process_manager = AgentServerProcessManager(data_dir=data_dir)
    scheduler = Scheduler(
        runtime=runtime, data_dir=data_dir, bus=bus, process_manager=process_manager
    )
    return AppDeps(
        engine=engine,
        session_factory=session_factory,
        runtime=runtime,
        scheduler=scheduler,
        bus=bus,
        broker=broker,
        process_manager=process_manager,
        data_dir=data_dir,
    )


__all__ = ["AppDeps", "build_deps"]
