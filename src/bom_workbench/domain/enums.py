"""Domain enums for BOM workbench workflows."""

from __future__ import annotations

from enum import StrEnum


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    NRND = "nrnd"
    LAST_TIME_BUY = "last_time_buy"
    EOL = "eol"
    UNKNOWN = "unknown"


class StockBucket(StrEnum):
    OUT = "out"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class EolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class RowState(StrEnum):
    IMPORTED = "imported"
    PENDING = "pending"
    QUEUED = "queued"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED_BY_USER = "skipped_by_user"
    USER_REVIEWED = "user_reviewed"


class ReplacementStatus(StrEnum):
    NONE = "none"
    CANDIDATES_FOUND = "candidates_found"
    USER_ACCEPTED = "user_accepted"
    USER_REJECTED = "user_rejected"


class JobState(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class EvidenceType(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"
