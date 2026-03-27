# 10 — Security & Observability

## Secret Management

### Storage
- **Primary**: OS keyring via `keyring` library
  - Windows: Windows Credential Locker
  - macOS: Keychain
  - Linux: Secret Service (GNOME Keyring / KWallet)
- **Namespace**: `bom-workbench/{provider_name}` per key
- **Fallback**: If keyring unavailable, prompt user with warning; never fall back to plaintext config file silently

### Rules
1. API keys NEVER appear in log output
2. API keys NEVER stored in config files
3. API keys masked in UI (`••••••••••••abcd` — show last 4 chars)
4. API keys excluded from exception tracebacks via custom exception hook
5. API keys never included in crash reports or diagnostics export

## Logging Architecture

Using `structlog` for structured, JSON-capable logging:

```python
# infrastructure/logging/setup.py

import structlog
import logging

def configure_logging(debug: bool = False) -> None:
    """Configure structured logging with redaction."""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_secrets,          # Custom: redact API keys
            _add_correlation_id,      # Custom: add job/request correlation
            structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
    )
```

### Redaction Processor

```python
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),          # OpenAI keys
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),       # Anthropic keys
    re.compile(r"[a-zA-Z0-9]{32,}"),               # Generic long tokens (conservative)
]

REDACT_FIELDS = {"api_key", "api-key", "authorization", "x-api-key", "token", "secret", "password"}

def _redact_secrets(logger, method_name, event_dict):
    """Redact secrets from all log fields."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            # Redact known field names
            if key.lower().replace("_", "").replace("-", "") in {f.replace("_","").replace("-","") for f in REDACT_FIELDS}:
                event_dict[key] = "***REDACTED***"
            else:
                # Redact values matching secret patterns
                for pattern in SECRET_PATTERNS:
                    value = pattern.sub("***REDACTED***", value)
                event_dict[key] = value
    return event_dict
```

### Log Categories

| Logger Name | File | Purpose |
|------------|------|---------|
| `bom.app` | app.log | Application lifecycle, startup, shutdown |
| `bom.provider` | provider.log | Provider API calls (redacted), model discovery |
| `bom.job` | job.log | Job lifecycle, progress, failures |
| `bom.import` | import.log | CSV import operations, warnings |
| `bom.export` | export.log | Excel export operations |
| `bom.error` | error.log | All ERROR+ level from any logger |

All logs written to: `~/.bom_workbench/logs/` with daily rotation.

### Correlation IDs

Every job gets a UUID correlation ID (`enrichment_job_id`). All log entries within that job include the correlation ID, enabling end-to-end tracing:

```
{"event": "row_enriched", "job_id": "a1b2c3", "row_id": 42, "provider": "anthropic", "latency_ms": 1234}
```

## Privacy Controls

### Privacy Levels (ProviderConfig.privacy_level)

| Level | What is sent to LLM | Use when |
|-------|---------------------|----------|
| `full` | All row fields including designators, URLs | Default, trusted provider |
| `minimized` | Only comment, footprint, LCSC part # | Reduce data exposure |
| `no_urls` | All fields except URLs | Prevent URL tracking |

### Manual Approval Mode

When `ProviderConfig.manual_approval = True`:
- Before each LLM call, a dialog shows the user exactly what will be sent
- User must click "Approve" or "Deny" for each call (or "Approve All" for batch)
- Denied calls are skipped, row marked as "skipped_by_user"

### Privacy Notice

On first use, show a non-blocking notice:
> "BOM data will be sent to external LLM providers for enrichment. You can control what data is shared in Settings > Privacy."

## Error Handling Strategy

### Error Boundaries

```
Application Layer
├── ImportBomUseCase
│   └── catches: FileNotFoundError, UnicodeDecodeError, csv.Error, ValidationError
│       → user message: "Could not read file: {friendly_reason}"
│
├── EnrichBomUseCase
│   └── catches: httpx.TimeoutException, httpx.HTTPStatusError, ProviderError
│       → per-row: mark failed, log, continue to next row
│       → user message: "Row {designator} enrichment failed: {reason}"
│
├── FindPartsUseCase
│   └── catches: same as enrichment
│       → user message: "Part search failed: {reason}"
│
├── ExportBomUseCase
│   └── catches: PermissionError, OSError
│       → user message: "Could not write file: {reason}"
│
└── ConfigureProviderUseCase
    └── catches: httpx.ConnectError, httpx.TimeoutException
        → user message: "Connection to {provider} failed: {reason}"
```

### User-Facing vs Developer Errors

```python
class UserFacingError(Exception):
    """Errors that should be displayed to the user."""
    def __init__(self, message: str, detail: str = "", suggestion: str = ""):
        self.message = message      # Short, actionable
        self.detail = detail        # Technical detail (collapsible in UI)
        self.suggestion = suggestion # "Try: check your API key"
```

### Global Error Handler

```python
def global_exception_handler(exc_type, exc_value, exc_tb):
    """Last-resort handler. Logs full traceback, shows user-friendly dialog."""
    # Redact secrets from traceback
    safe_tb = redact_traceback(exc_tb)
    logger.error("unhandled_exception", exc_type=exc_type.__name__, traceback=safe_tb)
    # Show error dialog to user (via Qt signal to UI thread)
    ...
```

### Startup Checks

On application launch:
1. Check Python version >= 3.12
2. Check SQLite database is accessible / not corrupted
3. Check keyring is available (warn if not)
4. Load provider configs, mark unavailable providers
5. Check for pending/interrupted jobs from last session
6. If any check fails: show diagnostic screen, not a crash
