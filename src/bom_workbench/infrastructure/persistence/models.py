"""Persistence model exports for BOM Workbench.

The database layer intentionally re-exports the domain SQLModel entities so
there is a single source of truth for table definitions and metadata.
"""

from __future__ import annotations

from bom_workbench.domain.entities import (
    BomProject as _BomProject,
    BomRow as _BomRow,
    Job as _Job,
    ProviderConfig as _ProviderConfig,
)

BomProject = _BomProject
BomRow = _BomRow
ProviderConfig = _ProviderConfig
Job = _Job

__all__ = [
    "BomProject",
    "BomRow",
    "ProviderConfig",
    "Job",
]
