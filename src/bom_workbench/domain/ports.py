"""Protocol-based domain ports for BOM Workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel

from .entities import BomProject, BomRow, Job
from .enums import JobState

__all__ = [
    "ChatConfig",
    "ConnectionTestResult",
    "ExportOptions",
    "ExportResult",
    "IBomRepository",
    "IEvidenceRetriever",
    "IExporter",
    "IJobRepository",
    "IProviderAdapter",
    "ISecretStore",
    "ModelInfo",
    "ProviderCapabilities",
    "ProviderResponse",
    "RawEvidence",
]


@dataclass(slots=True)
class ProviderCapabilities:
    """Describe provider features without binding to a concrete client."""

    supports_model_discovery: bool = False
    supports_reasoning_control: bool = False
    supports_structured_output: bool = False
    supports_tool_use: bool = False
    supports_batch: bool = False
    supports_streaming: bool = False
    supports_temperature: bool = True
    max_context_window: int | None = None
    reasoning_control_name: str = ""
    reasoning_levels: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConnectionTestResult:
    """Result returned by provider connection checks."""

    success: bool
    message: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelInfo:
    """Metadata for a selectable provider model."""

    id: str
    name: str
    provider: str
    context_window: int | None = None
    supports_vision: bool = False
    supports_tools: bool = False
    created_at: datetime | None = None


@dataclass(slots=True)
class ProviderResponse:
    """Uniform provider response shape."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    success: bool = True
    error_message: str = ""


@dataclass(slots=True)
class ChatConfig:
    """Configuration for a single provider request."""

    api_key: str
    model: str
    temperature: float | None = None
    max_tokens: int = 4096
    timeout_seconds: int = 60
    reasoning_effort: str | None = None
    response_format: str | None = None
    system_prompt: str = ""


@dataclass(slots=True)
class RawEvidence:
    """Raw evidence returned by deterministic retrieval."""

    source_url: str
    source_name: str
    retrieved_at: datetime | None
    content_type: str
    raw_content: str
    search_strategy: str


@dataclass(slots=True)
class ExportOptions:
    """Options that shape export behavior."""

    include_metadata_sheet: bool = True
    apply_color_coding: bool = True
    preserve_hyperlinks: bool = True
    sanitize_formulas: bool = True


@dataclass(slots=True)
class ExportResult:
    """Uniform export outcome."""

    output_path: str
    rows_exported: int
    sheets_created: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    file_size_bytes: int = 0


@runtime_checkable
class IProviderAdapter(Protocol):
    """Port for provider integrations."""

    def get_name(self) -> str: ...

    def get_capabilities(self) -> ProviderCapabilities: ...

    async def test_connection(self, api_key: str) -> ConnectionTestResult: ...

    async def discover_models(self, api_key: str) -> list[ModelInfo]: ...

    async def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        config: ChatConfig,
    ) -> ProviderResponse: ...

    async def chat_structured(
        self,
        messages: Sequence[Mapping[str, str]],
        response_schema: type[BaseModel],
        config: ChatConfig,
    ) -> ProviderResponse: ...


@runtime_checkable
class IBomRepository(Protocol):
    """Persistence port for BOM projects and rows."""

    async def save_project(self, project: BomProject) -> BomProject: ...

    async def get_project(self, project_id: int) -> BomProject | None: ...

    async def list_projects(self, limit: int = 100, offset: int = 0) -> list[BomProject]:
        ...

    async def delete_project(self, project_id: int) -> None: ...

    async def save_row(self, row: BomRow) -> BomRow: ...

    async def get_row(self, row_id: int) -> BomRow | None: ...

    async def list_rows_by_project(self, project_id: int) -> list[BomRow]: ...

    async def list_rows_by_state(self, project_id: int, state: str) -> list[BomRow]: ...

    async def delete_row(self, row_id: int) -> None: ...


@runtime_checkable
class IJobRepository(Protocol):
    """Persistence port for tracked async jobs."""

    async def save(self, job: Job) -> Job: ...

    async def get(self, job_id: int) -> Job | None: ...

    async def list_by_state(self, state: JobState) -> list[Job]: ...

    async def list_by_project(self, project_id: int) -> list[Job]: ...

    async def list_recent(self, limit: int = 50) -> list[Job]: ...


@runtime_checkable
class IEvidenceRetriever(Protocol):
    """Deterministic retrieval port for sourcing evidence."""

    async def retrieve(self, search_keys: Any) -> list[RawEvidence]: ...


@runtime_checkable
class IExporter(Protocol):
    """Export port for workbook generation."""

    async def export_procurement_bom(
        self,
        rows: Sequence[BomRow],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...

    async def export_full_table(
        self,
        rows: Sequence[BomRow],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...

    async def export_filtered_view(
        self,
        rows: Sequence[BomRow],
        columns: Sequence[str],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...


@runtime_checkable
class ISecretStore(Protocol):
    """Secret storage port for provider credentials."""

    async def store_key(self, provider: str, api_key: str) -> None: ...

    async def get_key(self, provider: str) -> str | None: ...

    async def delete_key(self, provider: str) -> None: ...
