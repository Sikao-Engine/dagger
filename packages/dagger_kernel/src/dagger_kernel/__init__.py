"""Dagger kernel — domain-agnostic core.

This package never imports domain code, HTTP frameworks, or DB drivers.
The import-linter contract in `.importlinter.toml` enforces this at CI time.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
