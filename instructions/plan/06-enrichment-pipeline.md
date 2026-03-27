# 06 — Enrichment Pipeline & Matching Engine

## Enrichment Philosophy (Non-negotiable)

```
RULE: Deterministic retrieval FIRST → LLM reasoning SECOND → User verification THIRD

The LLM NEVER invents: stock quantities, lifecycle status, EOL flags,
source URLs, lead times, part numbers, or compatibility claims.

Every asserted fact carries: source URL, source name, timestamp,
confidence level, evidence type (observed/inferred/estimated), raw snippet.
```

## Enrichment Pipeline — Per-Row Flow

```
BomRow (state: PENDING)
    │
    ▼
┌──────────────────────────────────┐
│ STAGE 1: SEARCH KEY EXTRACTION   │
│                                   │
│ Priority order:                   │
│   1. lcsc_part_number (if set)   │
│   2. mpn (if derivable)          │
│   3. lcsc_link / source_url      │
│   4. value + footprint + pkg     │
│      (parametric fallback)       │
│                                   │
│ Output: SearchKeys object         │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│ STAGE 2: EVIDENCE RETRIEVAL      │
│ (Deterministic — no LLM here)    │
│                                   │
│ Strategy per search key type:     │
│                                   │
│ a) LCSC Part # → build LCSC URL  │
│    → httpx GET product page       │
│    → parse stock, lifecycle,      │
│      pricing, datasheet link      │
│                                   │
│ b) MPN → search LCSC by MPN      │
│    → parse results                │
│                                   │
│ c) URL → httpx GET the URL       │
│    → parse structured data        │
│                                   │
│ d) Parametric → search LCSC by   │
│    value + footprint keywords     │
│                                   │
│ Output: list[RawEvidence]         │
│ Each with: source, timestamp,     │
│   raw_html/json snippet           │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│ STAGE 3: EVIDENCE PARSING        │
│ (Deterministic extraction)        │
│                                   │
│ Parse raw evidence into:          │
│ - stock_qty (int)                │
│ - stock_status (enum)            │
│ - lifecycle_status (enum)        │
│ - lead_time (str)                │
│ - moq (int)                      │
│ - manufacturer (str)             │
│ - package (str)                  │
│ - pricing tiers if available     │
│                                   │
│ Mark each field:                  │
│ - evidence_type: OBSERVED        │
│ - confidence: HIGH/MEDIUM        │
│ - source_url, source_name        │
│                                   │
│ Output: list[EvidenceRecord]      │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│ STAGE 4: LLM REASONING          │
│ (Optional, only if enabled)       │
│                                   │
│ Use LLM to:                       │
│ - Synthesize multiple evidence    │
│   sources into summary           │
│ - Classify lifecycle risk from    │
│   ambiguous evidence text        │
│ - Parse messy vendor text into    │
│   structured fields              │
│ - Rank multiple candidates       │
│ - Suggest alternates if stock    │
│   is problematic                 │
│ - Explain tradeoffs              │
│                                   │
│ LLM receives:                     │
│ - parsed evidence (not raw HTML) │
│ - row context per privacy level  │
│ - structured output schema       │
│                                   │
│ LLM output marked:               │
│ - evidence_type: INFERRED        │
│ - confidence: based on evidence  │
│   quality, not LLM certainty    │
│                                   │
│ Output: EnrichmentResult          │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│ STAGE 5: PERSISTENCE & UPDATE    │
│                                   │
│ - Update BomRow fields           │
│ - Store EnrichmentResult as JSON │
│   in evidence_blob               │
│ - Store raw_provider_response    │
│ - Set row_state = ENRICHED       │
│   or WARNING if issues found     │
│ - Update last_checked_at         │
│ - Emit event for UI update       │
└──────────────────────────────────┘
```

## SearchKeys Model

```python
@dataclass
class SearchKeys:
    lcsc_part_number: str | None = None
    mpn: str | None = None
    url: str | None = None
    value: str | None = None
    footprint: str | None = None
    package: str | None = None
    category: str | None = None
    manufacturer: str | None = None
    search_strategy: str = ""  # "lcsc_direct" | "mpn_search" | "url_resolve" | "parametric"
```

## Evidence Retrieval Strategy

The `IEvidenceRetriever` port defines the interface:

```python
class IEvidenceRetriever(ABC):
    @abstractmethod
    async def retrieve(self, search_keys: SearchKeys) -> list[RawEvidence]: ...

class RawEvidence(BaseModel):
    source_url: str
    source_name: str
    retrieved_at: datetime
    content_type: str  # "html" | "json" | "text"
    raw_content: str   # The raw response snippet (truncated to reasonable size)
    search_strategy: str
```

### LCSC Evidence Retriever

Primary implementation. Retrieves data from LCSC (jlcpcb.com/parts):

```python
class LcscEvidenceRetriever(IEvidenceRetriever):
    """Retrieves component data from LCSC/JLCPCB parts catalog."""

    BASE_URL = "https://jlcpcb.com/parts"

    async def retrieve(self, search_keys: SearchKeys) -> list[RawEvidence]:
        if search_keys.lcsc_part_number:
            return await self._retrieve_by_part_number(search_keys.lcsc_part_number)
        if search_keys.mpn:
            return await self._retrieve_by_mpn(search_keys.mpn)
        if search_keys.url:
            return await self._retrieve_by_url(search_keys.url)
        return await self._retrieve_by_parametric(search_keys)
```

**Note**: LCSC/JLCPCB may require API keys or have rate limits. The retriever must:
- Respect rate limits with configurable delays
- Handle HTTP errors gracefully
- Cache responses to avoid redundant fetches
- Timeout per request (configurable)

## LLM Prompt Templates

### Enrichment Summary Prompt

```python
ENRICHMENT_PROMPT = """You are an electronics component analyst. Given the following evidence about a component, extract and summarize the sourcing information.

## Component
- Designator: {designator}
- Comment/Value: {comment}
- Footprint: {footprint}
- LCSC Part #: {lcsc_part_number}

## Retrieved Evidence
{evidence_text}

## Instructions
Based ONLY on the evidence above, extract:
1. stock_qty: integer or null if not found
2. lifecycle_status: one of [active, nrnd, last_time_buy, eol, unknown]
3. eol_risk: one of [low, medium, high, unknown]
4. manufacturer: string or empty
5. mpn: string or empty
6. lead_time: string or empty
7. moq: integer or null
8. summary: one-line summary of sourcing status
9. warnings: list of any concerns

CRITICAL RULES:
- If information is NOT in the evidence, set it to null/unknown/empty
- NEVER invent or guess values
- For each field, state whether it is OBSERVED (directly in evidence) or INFERRED (derived from evidence)
- Include confidence: high (directly stated), medium (clearly implied), low (loosely implied)

Respond in the specified JSON format only."""
```

### Replacement Search Prompt

```python
REPLACEMENT_PROMPT = """You are an electronics component matching expert. Given a component and candidate replacements, rank the candidates by compatibility.

## Original Component
- Value: {comment}
- Footprint: {footprint}
- Package: {package}
- LCSC Part #: {lcsc_part_number}
- Category: {category}

## Candidates
{candidates_json}

## Instructions
For each candidate, assess:
1. match_score: 0.0-1.0 overall compatibility
2. match_explanation: why it matches
3. differences: what may differ from the original
4. warnings: any risks of this substitution
5. recommended: boolean

Score breakdown factors:
- value_match: exact value/rating match
- footprint_match: exact footprint/package match
- voltage_compatibility: voltage rating >= original
- tolerance_compatibility: tolerance <= original
- temperature_compatibility: temp range >= original
- dielectric_match: same dielectric/technology
- lifecycle_safety: active lifecycle preferred
- stock_health: good stock preferred

CRITICAL: Base your assessment ONLY on the provided data. Do not invent specifications."""
```

## Matching Engine (`domain/matching.py`)

### Tiered Matching Strategy

```python
class MatchingEngine:
    """Tiered part matching with transparent scoring."""

    TIERS = [
        ("exact_lcsc", 1.0),      # Exact LCSC part number match
        ("exact_mpn", 0.95),       # Exact manufacturer part number match
        ("url_resolved", 0.9),     # URL-resolved part match
        ("strong_parametric", 0.8),# Strong parametric match (value+footprint+voltage)
        ("heuristic", 0.6),        # Heuristic match (partial parametric)
        ("llm_ranked", 0.4),       # LLM-ranked candidate set
    ]

    def compute_match_score(
        self,
        original: BomRow,
        candidate: ReplacementCandidate,
    ) -> MatchScore:
        """Compute transparent match score with breakdown."""
        breakdown = {}

        # Value match (weight: 0.20)
        breakdown["value_match"] = self._score_value_match(original, candidate) * 0.20

        # Footprint/package match (weight: 0.20)
        breakdown["footprint_match"] = self._score_footprint_match(original, candidate) * 0.20

        # Voltage compatibility (weight: 0.15)
        breakdown["voltage_compat"] = self._score_voltage_compat(original, candidate) * 0.15

        # Tolerance compatibility (weight: 0.10)
        breakdown["tolerance_compat"] = self._score_tolerance_compat(original, candidate) * 0.10

        # Temperature compatibility (weight: 0.05)
        breakdown["temp_compat"] = self._score_temp_compat(original, candidate) * 0.05

        # Dielectric/technology match (weight: 0.05)
        breakdown["dielectric_match"] = self._score_dielectric_match(original, candidate) * 0.05

        # Lifecycle safety (weight: 0.10)
        breakdown["lifecycle_safety"] = self._score_lifecycle(candidate) * 0.10

        # Stock health (weight: 0.10)
        breakdown["stock_health"] = self._score_stock(candidate) * 0.10

        # Evidence confidence (weight: 0.05)
        breakdown["evidence_confidence"] = self._score_confidence(candidate) * 0.05

        total = sum(breakdown.values())
        explanation = self._generate_explanation(breakdown, original, candidate)

        return MatchScore(total=total, breakdown=breakdown, explanation=explanation)
```

### Score Component Functions

Each `_score_*` function returns 0.0 to 1.0:

| Function | Logic |
|----------|-------|
| `_score_value_match` | Exact string match = 1.0, parsed numeric match = 0.9, close = 0.5, no match = 0.0 |
| `_score_footprint_match` | Exact = 1.0, same family (e.g., 0402 variants) = 0.8, different = 0.0 |
| `_score_voltage_compat` | candidate >= original = 1.0, candidate < original = 0.0, unknown = 0.3 |
| `_score_tolerance_compat` | candidate <= original = 1.0, candidate > original = 0.5, unknown = 0.3 |
| `_score_lifecycle` | ACTIVE = 1.0, NRND = 0.4, LTB = 0.2, EOL = 0.0, UNKNOWN = 0.3 |
| `_score_stock` | HIGH = 1.0, MEDIUM = 0.8, LOW = 0.4, OUT = 0.0, UNKNOWN = 0.2 |

## Privacy-Aware Context Building

Before sending data to LLM, apply privacy level from `ProviderConfig.privacy_level`:

```python
def build_llm_context(row: BomRow, privacy_level: str) -> dict:
    if privacy_level == "full":
        return {
            "designator": row.designator,
            "comment": row.comment,
            "footprint": row.footprint,
            "lcsc_part_number": row.lcsc_part_number,
            "lcsc_link": row.lcsc_link,
            "value_raw": row.value_raw,
        }
    elif privacy_level == "minimized":
        return {
            "comment": row.comment,
            "footprint": row.footprint,
            "lcsc_part_number": row.lcsc_part_number,
        }
    elif privacy_level == "no_urls":
        return {
            "designator": row.designator,
            "comment": row.comment,
            "footprint": row.footprint,
            "lcsc_part_number": row.lcsc_part_number,
        }
```

## Confidence Scoring Logic

```
HIGH confidence when:
  - Data directly from authoritative source (LCSC product page)
  - Field value explicitly stated in retrieved text
  - Multiple sources agree

MEDIUM confidence when:
  - Data from single source
  - Value implied but not explicitly stated
  - Parsed from semi-structured text

LOW confidence when:
  - Derived by LLM from indirect evidence
  - Single weak evidence source
  - Partially conflicting information

NONE confidence when:
  - No evidence found
  - Value is a pure guess
  → Mark as UNKNOWN, never present as fact
```
