# Kynd Opportunity Intelligence System (KOIS) PID

## Purpose

KOIS is a provenance-first opportunity intelligence system for Kynd. It ingests assignment and procurement signals from email, broker portals, public tender platforms, scrapers, and APIs; preserves the raw evidence; groups related source items into opportunity clusters; and produces low-noise review queues, digests, and market intelligence.

The first goal is not a smarter Slack bot. The first goal is a reliable assignment inbox, duplicate clustering, and data foundation.

## Product Boundaries

KOIS owns:
- inbound opportunity and procurement signals
- raw source evidence and extracted records
- opportunity clustering and source comparison
- DPS and frame-agreement market signals
- review states, lightweight planning, and low-noise reporting
- integration points for Slack, LLM APIs, Notion imports, and later KBS matching

KOIS does not own:
- CV storage
- bid writing
- project reference variants
- candidate evaluation records
- HR or recruitment systems
- final CRM ownership unless explicitly added later

## Guiding Principles

- Preserve evidence; filter only in analysis and presentation.
- Cluster duplicates; do not delete source records.
- Prefer a primary source for display, not a single unquestioned canonical truth.
- Keep field-level provenance where source values differ.
- Use LLMs conservatively for extraction, classification, comparison, and drafting, not as the sole decision-maker.
- Keep phase 1 lightweight: speed matters more than generic configurability.
- Slack, Gemini, Notion, and broker portals are replaceable integrations, not architectural lock-ins.
- Database is source of truth. Notion is a notebook or imported reference source.

## Initial Priorities

1. Assignment inbox, dedupe/clustering, and data foundation.
2. Market analytics.
3. Sales opportunity filtering.
4. CV market-fit evaluation through KBS integration.

## Conceptual Data Model

- `RawSourceItem`: immutable inbound evidence such as email, scrape result, API payload, tender notice, or DPS update.
- `ExtractedRecord`: structured data parsed from one source item.
- `OpportunityCluster`: a grouped opportunity made from one or more extracted records.
- `PrimarySource`: the preferred source for display and decisioning at a point in time.
- `SourceComparison`: differences, overlaps, and additions across source records in a cluster.
- `AgreementSignal`: DPS or frame-agreement information that may not be assignment-related.
- `AgreementGap`: persisted potential coverage gap where repeated buyer demand appears without matching agreement signals.
- `ReviewState`: `auto_accepted`, `needs_review`, `manually_merged`, `manually_split`, `ignored`, or `watch_only`.
- `DigestItem`: generated output for Slack or reports, backed by stored evidence.
- `RoleClassification`: lightweight role category and tags inferred from cluster source content.
- `RelevanceScore`: availability-aware score used for sales filtering and digest eligibility.
- `AvailabilityProfile`: lightweight operator-provided role capacity signal used for Phase 3 filtering.
- `ExternalFitAssessment`: later KBS-provided fit assessment for consultants, CVs, references, or bid material.

## Source Priority

KOIS should store all sources and compare them. For display and decisioning, sources closer to the buyer or procurement event normally outrank broker summaries.

Initial primary-source preference:
1. Public buyer or tender source such as Doffin or procurement-platform notice.
2. Direct Kynd-owned agreement or buyer communication.
3. Broker portal or broker email.
4. Forwarded or manually entered source.

This is a default policy, not a reason to discard broker details. Broker descriptions may add useful role framing, skills, pricing signals, or market evidence.

## Phases

### Phase 1: Foundation And Inbox

Ingest `oppdrag@kynd.no` emails and current scraper outputs, preserve raw evidence, extract structured records, cluster likely duplicates, expose a basic review queue, and produce a conservative digest.

Success metric: KOIS becomes a searchable assignment archive with fewer duplicate distractions than email.

Implementation status: in progress. Current implementation uses Postgres-backed persistence, scraper + IMAP ingestion adapters, cluster/source comparison records, a minimal review API surface, and digest-item persistence.

### Phase 2: Market And Agreement Intelligence

Add Doffin and procurement monitoring, agreement-signal handling, buyer and broker analytics, and discovery of DPS or frame agreements Kynd may not have found or applied for.

Success metric: KOIS identifies market patterns and agreement coverage gaps, not only new assignments.

Implementation status: in progress. Current implementation adds procurement feed adapters, canonical source taxonomy for clustering priority, persisted agreement signals and agreement gaps, analytics summary services, and API endpoints for market intelligence and gap triage.

### Phase 3: Sales Opportunity Filtering

Add lightweight role classification, availability-aware digest modes, source/relevance thresholds, and configurable Slack cadence.

Success metric: Slack highlights fewer but better items while the archive remains complete.

Implementation status: completed for now. Current implementation adds deterministic role classification, availability-profile-aware relevance scoring, configurable digest thresholds/cadence, and relevant-opportunity API filtering while preserving archive recall; ongoing work is tuning role taxonomy and capacity-profile defaults from operator feedback.

### Phase 4: KBS Integration

Expose opportunity profiles to KBS and receive high-level fit assessments back. KOIS should not own CV or bid material.

Success metric: KOIS can indicate which opportunities deserve deeper bid-system evaluation.

### Phase 5: Recruitment Market Fit

Use KOIS market history and KBS CV data to evaluate whether candidate profiles match recent demand and identify bid-framing gaps.

Success metric: recruitment and CV positioning decisions are informed by observed market demand.

## Delivery Surfaces

- Basic UI for review, merge, split, ignore, and source comparison.
- Slack channels for conservative digests, review prompts, and optionally DPS/agreement updates.
- API view for relevance-filtered opportunities based on current Phase 3 policy.
- Periodic market reports.
- Searchable archive.
- API or export surface for KBS.

## Canvas Maintenance

The KOIS planning Canvas is the living planning surface. Keep it aligned with this PID whenever work changes:
- update phase status when implementation starts or completes phase work
- add or refine deliverables as plans become concrete
- reflect decisions that change scope, boundaries, data model, or integration strategy
- keep completed implementation details concise; link to code or plans instead of duplicating them

Canvas path:
`/Users/holene/.cursor/projects/Users-holene-repos-kynd-job-scraper/canvases/kois-planning.canvas.tsx`
