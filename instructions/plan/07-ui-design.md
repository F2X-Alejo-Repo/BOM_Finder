# 07 — UI Design

## Application Shell Layout

```
┌──────────────────────────────────────────────────────────────┐
│  APP BAR    [BOM Workbench]           [workspace] [🌙 theme] │
├────────┬─────────────────────────────────────────────────────┤
│        │                                                      │
│  NAV   │              CENTRAL WORKSPACE                       │
│  RAIL  │                                                      │
│        │  ┌─────────────────────────────┬──────────────────┐ │
│ Import │  │                             │                  │ │
│        │  │    Page Content              │   INSPECTOR      │ │
│  BOM   │  │    (tab-specific)           │   PANEL          │ │
│ Table  │  │                             │   (contextual)   │ │
│        │  │                             │                  │ │
│  Part  │  │                             │                  │ │
│ Finder │  │                             │                  │ │
│        │  │                             │                  │ │
│  LLM   │  │                             │                  │ │
│ Config │  │                             │                  │ │
│        │  │                             │                  │ │
│  Jobs  │  └─────────────────────────────┴──────────────────┘ │
│        │                                                      │
│ Export │                                                      │
│        │                                                      │
│Settings│                                                      │
├────────┴─────────────────────────────────────────────────────┤
│  STATUS BAR   [job progress] [rows: 142] [enriched: 89]     │
└──────────────────────────────────────────────────────────────┘
```

## Widget Hierarchy

```
MainWindow (QMainWindow)
├── AppBar (QFrame) — top bar
│   ├── QLabel — app title "BOM Intelligence Workbench"
│   ├── QLabel — workspace/project name
│   └── QPushButton — theme toggle
│
├── Central QSplitter (horizontal)
│   ├── NavRail (QFrame) — left navigation
│   │   ├── NavButton × 7 — one per tab
│   │   └── QLabel — version at bottom
│   │
│   ├── PageStack (QStackedWidget) — central content
│   │   ├── ImportPage (QWidget)
│   │   ├── BomTablePage (QWidget)
│   │   ├── PartFinderPage (QWidget)
│   │   ├── ProvidersPage (QWidget)
│   │   ├── JobsPage (QWidget)
│   │   ├── ExportPage (QWidget)
│   │   └── SettingsPage (QWidget)
│   │
│   └── InspectorPanel (QFrame) — right details
│       └── RowInspector (QWidget)
│
└── StatusBar (QFrame) — bottom bar
    ├── AsyncProgressBar — current job progress
    ├── QLabel — quick stats (rows, enriched, etc.)
    └── StatusChip — connection/provider status
```

## Page Designs

### 1. ImportPage

```
┌──────────────────────────────────────────┐
│  BOM IMPORT                              │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │                                    │  │
│  │     DropZone                       │  │
│  │     "Drag CSV files here"          │  │
│  │     "or click to browse"           │  │
│  │                                    │  │
│  │     [Browse Files] [Browse Folder] │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Recent Imports:                         │
│  ┌────────────────────────────────────┐  │
│  │ sample_bom.csv  │ 142 rows │ 2m ago│  │
│  │ power_board.csv │ 89 rows  │ 1h ago│  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

**Components**: `DropZone` (custom QFrame with drag-drop), file picker buttons, recent imports list.

### 2. BomTablePage

```
┌─────────────────────────────────────────────────────────────┐
│ BOM TABLE                                   [Enrich All] ▼  │
│                                                              │
│ ┌─────┬─────┬──────┬────┬─────┬─────┬──────┬──────┬──────┐ │
│ │Total│Uniq │Enrich│Fail│ OOS │ Low │ EOL  │Alts  │Review│ │
│ │ 142 │ 98  │  89  │  3 │  5  │ 12  │  2   │  34  │  8   │ │
│ └─────┴─────┴──────┴────┴─────┴─────┴──────┴──────┴──────┘ │
│                                                              │
│ [Search...________________________] [Filter ▼] [Columns ▼]  │
│                                                              │
│ ┌──────┬────────┬──────────┬──────┬───────┬──────┬────────┐ │
│ │Desgn │Comment │Footprint │LCSC# │Stock  │Life  │State   │ │
│ ├──────┼────────┼──────────┼──────┼───────┼──────┼────────┤ │
│ │R1-R4 │100K    │0402      │C1234 │●12.5K │●Act  │✓ Done  │ │
│ │C1,C2 │100nF   │0402      │C5678 │●0     │●EOL  │⚠ Warn  │ │
│ │U1    │STM32F4 │LQFP-64   │—     │—      │—     │○ Pend  │ │
│ │...   │...     │...       │...   │...    │...   │...     │ │
│ └──────┴────────┴──────────┴──────┴───────┴──────┴────────┘ │
│                                                              │
│ Showing 142 of 142 rows                    Page 1/3 [< >]   │
└─────────────────────────────────────────────────────────────┘
```

**Color coding in table cells**:
- Stock column: green dot = HIGH/MEDIUM, amber dot = LOW, red dot = OUT
- Lifecycle column: green = ACTIVE, amber = NRND, red = EOL/LTB
- State column: green checkmark = ENRICHED, amber warning = WARNING, red X = FAILED, gray circle = PENDING
- Full row background tint: subtle red for EOL/out-of-stock, subtle amber for low-stock/NRND, no tint for healthy

**MetricCard row**: 9 summary cards at top using `MetricCard` widget.

### 3. PartFinderPage

```
┌─────────────────────────────────────────────────────────────┐
│ PART FINDER                                                  │
│                                                              │
│ Search By:                                                   │
│ ┌──────────────┬──────────────┬───────────────────────────┐ │
│ │ Part #/MPN   │ Footprint    │ Value                     │ │
│ ├──────────────┼──────────────┼───────────────────────────┤ │
│ │ [C1234___]   │ [0402____]   │ [100nF___]                │ │
│ └──────────────┴──────────────┴───────────────────────────┘ │
│                                                              │
│ Filters:                                                     │
│ [✓ Active only] [✓ In stock] [✓ LCSC available]             │
│ [  Long-life  ] [  High stock] [Manufacturer: ________]     │
│                                                              │
│ [Search from selected BOM row]  [Search]                     │
│                                                              │
│ Results (5 candidates):                                      │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ ★ 0.95  C1234  │ Samsung CL05B104KO5  │ 100nF 50V X7R│  │
│ │         In Stock: 125,000  │ Active  │ [Apply to BOM] │  │
│ ├────────────────────────────────────────────────────────┤  │
│ │ ★ 0.88  C5678  │ Yageo CC0402KRX7R9  │ 100nF 50V X7R │  │
│ │         In Stock: 45,000   │ Active  │ [Apply to BOM] │  │
│ └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4. ProvidersPage

```
┌─────────────────────────────────────────────────────────────┐
│ LLM PROVIDERS                                                │
│                                                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ OpenAI                                    [Enabled ◉]   │ │
│ │                                                         │ │
│ │ API Key: [••••••••••••••••____] [Test Connection]       │ │
│ │ Model:   [gpt-4o           ▼ ] [Refresh Models]        │ │
│ │                                                         │ │
│ │ Advanced:                                               │ │
│ │ Temperature: [0.3___]  Timeout: [60s__]                │ │
│ │ Max Concurrent: [5__]  Max Retries: [3__]              │ │
│ │ [✓ Structured output]                                   │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Anthropic                                 [Enabled ◉]   │ │
│ │                                                         │ │
│ │ API Key: [••••••••••••••••____] [Test Connection]       │ │
│ │ Model:   [claude-sonnet-4 ▼  ] [Refresh Models]        │ │
│ │                                                         │ │
│ │ Advanced:                                               │ │
│ │ Temperature: [0.3___]  Timeout: [60s__]                │ │
│ │ Max Concurrent: [5__]  Max Retries: [3__]              │ │
│ │ Thinking Effort: [● Low ○ Med ○ High]                  │ │
│ │ [✓ Structured output]                                   │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Dynamic controls**: Reasoning effort slider only shown when `capabilities.supports_reasoning_control == True`. Controls adapt per provider.

### 5. JobsPage

```
┌─────────────────────────────────────────────────────────────┐
│ JOBS & ACTIVITY                                              │
│                                                              │
│ [Pause All] [Resume All] [Cancel All] [Retry Failed] [Clear]│
│                                                              │
│ ┌──────┬──────────┬────────┬─────┬───────┬──────┬────────┐ │
│ │Job ID│Type      │Status  │Rows │Done   │Prov  │Duration│ │
│ ├──────┼──────────┼────────┼─────┼───────┼──────┼────────┤ │
│ │ J-042│Enrich    │●Running│ 142 │ 89/142│Claude│ 2m 14s │ │
│ │ J-041│Enrich    │✓ Done  │  50 │ 50/50 │GPT-4o│ 1m 02s │ │
│ │ J-040│Export    │✓ Done  │   1 │  1/1  │ —    │    3s  │ │
│ └──────┴──────────┴────────┴─────┴───────┴──────┴────────┘ │
│                                                              │
│ Job Details (J-042):                                         │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Started: 14:32:01 │ Provider: Anthropic │ Model: claude │ │
│ │ Progress: ████████████░░░░░░░░ 62.7%                   │ │
│ │ Completed: 89  │ Failed: 3  │ Retries: 2               │ │
│ │ Failures: Row 23 (timeout), Row 67 (rate limit), ...   │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 6. ExportPage

```
┌──────────────────────────────────────────┐
│ EXPORT                                    │
│                                          │
│ Export Target:                            │
│ ○ Current filtered view                  │
│ ○ Full canonical table                   │
│ ● Final procurement BOM                  │
│                                          │
│ Format: .xlsx (Excel)                    │
│                                          │
│ Preview columns:                         │
│ ✓ Designator                             │
│ ✓ Comment                                │
│ ✓ Footprint                              │
│ ✓ LCSC LINK                              │
│ ✓ LCSC PART #                            │
│                                          │
│ Options:                                 │
│ [✓ Include metadata sheet]               │
│ [✓ Apply color coding]                   │
│ [✓ Preserve hyperlinks]                  │
│                                          │
│ [Export to File...]                       │
└──────────────────────────────────────────┘
```

### 7. SettingsPage

Privacy controls, data directory, general preferences.

## Inspector Panel (Right Side)

When a BomRow is selected in the table:

```
┌──────────────────────┐
│ ROW INSPECTOR        │
│                      │
│ Designator: R1-R4    │
│ Comment: 100K        │
│ Footprint: 0402      │
│ LCSC: C1234          │
│ State: ✓ Enriched    │
│                      │
│ ── Sourcing ──       │
│ Stock: 125,000       │
│ Lifecycle: Active    │
│ EOL Risk: Low        │
│ Lead Time: 2-3 wks   │
│ MOQ: 100             │
│ Confidence: High     │
│ Source: LCSC          │
│ Last Check: 2m ago   │
│                      │
│ ── Evidence ──       │
│ 3 records            │
│ [View Evidence]      │
│                      │
│ ── Replacement ──    │
│ Status: None         │
│ [Find Replacement]   │
│                      │
│ ── Actions ──        │
│ [Enrich Row]         │
│ [Mark Reviewed]      │
│ [Export Row]         │
└──────────────────────┘
```

## QSS Theme System (`resources/themes/dark.qss` + `ui/theme.py`)

### Color Palette

```python
COLORS = {
    # Base
    "bg_primary": "#1a1a2e",       # Main background
    "bg_secondary": "#16213e",     # Cards, panels
    "bg_tertiary": "#0f3460",      # Elevated elements
    "bg_surface": "#1e2746",       # Table rows, inputs

    # Text
    "text_primary": "#e8e8e8",     # Primary text
    "text_secondary": "#a0a0b0",   # Secondary/muted text
    "text_disabled": "#606070",    # Disabled text

    # Accent
    "accent_primary": "#4a9eff",   # Primary accent (blue)
    "accent_hover": "#6bb3ff",     # Hover state
    "accent_pressed": "#3580d4",   # Pressed state

    # Status
    "status_success": "#4ade80",   # Green — healthy, active, done
    "status_warning": "#fbbf24",   # Amber — low stock, NRND, warning
    "status_error": "#f87171",     # Red — EOL, out of stock, failed
    "status_info": "#60a5fa",      # Blue — pending, info

    # Borders
    "border_subtle": "#2a2a4a",    # Subtle dividers
    "border_default": "#3a3a5a",   # Default borders
    "border_focus": "#4a9eff",     # Focus rings
}
```

### Typography

```python
TYPOGRAPHY = {
    "font_family": "Segoe UI, Inter, -apple-system, sans-serif",
    "font_size_xs": 11,
    "font_size_sm": 12,
    "font_size_md": 13,
    "font_size_lg": 15,
    "font_size_xl": 18,
    "font_size_xxl": 22,
    "font_weight_normal": 400,
    "font_weight_medium": 500,
    "font_weight_bold": 600,
}
```

### Spacing Scale

```python
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}
```

## Signal/Slot Architecture

Key signals connecting UI to application layer:

| Signal | Source | Handler | Purpose |
|--------|--------|---------|---------|
| `files_dropped(list[Path])` | DropZone | ImportPage | Trigger CSV import flow |
| `import_completed(ImportReport)` | ImportBomUseCase | BomTablePage | Refresh table after import |
| `row_selected(int)` | BomTablePage | RowInspector | Show selected row details |
| `enrich_requested(list[int])` | BomTablePage | EnrichBomUseCase | Start enrichment job |
| `row_enriched(int, EnrichmentResult)` | EnrichBomUseCase | BomTableModel | Update single row in table |
| `job_state_changed(Job)` | JobManager | JobsPage, StatusBar | Update job display |
| `replacement_found(int, list[RC])` | FindPartsUseCase | PartFinderPage | Show candidates |
| `replacement_accepted(int, RC)` | PartFinderPage | BomTableModel | Update BomRow with replacement |
| `provider_configured(ProviderConfig)` | ProvidersPage | ConfigureProviderUseCase | Save provider config |
| `export_completed(Path)` | ExportBomUseCase | ExportPage | Show success message |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+I` | Import file |
| `Ctrl+E` | Export |
| `Ctrl+F` | Focus search bar |
| `Ctrl+R` | Enrich selected rows |
| `Ctrl+Shift+R` | Enrich all |
| `F5` | Refresh current view |
| `Escape` | Close inspector / clear selection |
| `1-7` | Switch tabs (when nav focused) |
| `Ctrl+,` | Open settings |

## Table Virtualization Strategy

For large BOMs (500+ rows), the BomTableModel uses Qt's model/view architecture natively:
- `QAbstractTableModel` serves data on demand (Qt only requests visible rows)
- No need for explicit virtualization — Qt's `QTableView` already virtualizes rendering
- Sorting: `QSortFilterProxyModel` wrapping `BomTableModel`
- Filtering: same proxy model with custom `filterAcceptsRow`
- Updates: `dataChanged` signal emitted per-row as enrichment completes (no full refresh)
