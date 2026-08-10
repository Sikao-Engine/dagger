"""divdag_server: HTTP server + scheduler + DB for DivDag (M5).

Built on divdag_kernel (StateStore + DAG engine) and divdag_agent (SessionRunner).
Litestar + SQLAlchemy + SQLite + Alembic.

The server reuses the kernel's `run_graph` as its unit-of-work primitive (design
doc §13 risk: no duplicate readiness logic). The scheduler wraps the engine,
persisting NodeRun/Attempt state to DB as it goes; crash recovery reads back
from the StateStore (the kernel's recovery substrate).
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
