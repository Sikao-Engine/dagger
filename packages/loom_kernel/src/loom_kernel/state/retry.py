"""RetryPolicy: how scratch is treated across attempts of the same node.

- FRESH   (default): each attempt starts with an empty scratch dir.
- INHERIT: copy the previous attempt's scratch dir into the new one (resume).
- LINK    : read-only overlay of the previous attempt's scratch; new writes go
            to the new dir. Useful for skill-state-continuation patterns.

This module is intentionally tiny: the StateStore reads `SkillSpec.retry_policy`
and dispatches to its internal helpers when `begin_attempt()` is called.
"""

from __future__ import annotations

from enum import Enum


class RetryPolicy(str, Enum):
    FRESH = "fresh"
    INHERIT = "inherit"
    LINK = "link"


__all__ = ["RetryPolicy"]
