# EcoEvidence development roadmap

Last reviewed: 2026-08-15

## Purpose

This Roadmap converts the long-term Literature-to-Data vision into small,
independently reviewable milestones. It is the project status source of truth;
`README.md` remains the concise public entry point.

Status vocabulary:

- **Completed**: runnable, documented, and supported by proportionate tests.
- **In progress**: the active milestone has a branch or PR.
- **Planned**: accepted direction without a verified implementation.
- **Blocked**: cannot proceed without a named product, data, credential, or
  external decision.

## Verified baseline

The current public MVP runs the following path:

```text
research requirement -> local PDF parsing -> four-level screening
-> explainable hybrid retrieval -> human Gold evidence
-> Hit@K / Recall@K / Precision@K / MRR
```

Implemented and tested:

- natural-language requirement decomposition into reviewable fields;
- text-layer PDF parsing into stable evidence blocks;
- document, page, section, block, and bounding-box provenance;
- `usable`, `relative`, `nodata`, and `failed` screening states;
- BM25 + character n-gram hashing + terminology + section-prior retrieval;
- optional pinned `multilingual-e5-small` local neural retrieval;
- local SQLite state and PDF-hash-based parse reuse;
- human Gold evidence marking and retrieval metrics;
- bundled synthetic PDF Demo, frontend workbench, backend tests, and CI.

Not yet implemented as production-ready functionality:

- representative multi-paper neural-retrieval quality and throughput evidence;
- approximate nearest-neighbor indexing for corpora where exact scan is too slow;
- LLM schema-guided structured extraction and RAG generation;
- final field-level provenance manifests and structured export;
- OCR for scanned PDFs and robust table structure extraction;
- unit normalization and broader rule-based data quality checks;
- literature discovery and managed PDF acquisition in the mainline;
- representative correction sets and cross-PDF stability reporting.

## Milestone overview

| ID | Milestone | Status | Primary evidence of completion |
| --- | --- | --- | --- |
| M0 | Reproducible portfolio baseline | Completed | Public Demo, README, tests, CI, PR #1 |
| M1 | Repository rules and measurable Roadmap | Completed | `AGENTS.md`, this Roadmap, PR #2 |
| M2 | Versioned neural Embedding and Vector Retrieval | In progress | Baseline comparison with Hit@K, Recall@K, MRR, latency |
| M3 | Schema-guided RAG structured extraction | Planned | Validated field output with evidence and offline tests |
| M4 | Field provenance, quality rules, and export | Planned | Traceable manifest plus JSON/CSV export |
| M5 | OCR and table-aware parsing | Planned | Scanned/table fixtures with parsing and recall tests |
| M6 | Literature discovery and PDF acquisition | Planned | Reproducible candidate manifest and acquisition states |
| M7 | Human review evaluation and portfolio release | Planned | Correction set, failure analysis, end-to-end metrics |

Only one milestone should normally be **In progress** at a time.

## M0 — Reproducible portfolio baseline

Status: **Completed**

Delivered:

- honest public feature-status boundary;
- synthetic, redistributable PDF Demo;
- local full-text evidence workbench;
- retrieval evaluation and provenance inspection;
- lint, backend tests, frontend production build, rendered-page tests, and CI.

The hashing vector component is a reproducible lexical baseline, not a neural
Embedding model. Public descriptions must preserve that distinction.

## M1 — Repository rules and measurable Roadmap

Status: **Completed** — delivered in PR #2

Scope:

- add repository-level `AGENTS.md` instructions;
- document milestone order, boundaries, acceptance criteria, and metrics;
- link the Roadmap from the public README;
- establish branch, PR, CI, data-safety, and documentation-truth rules.

Acceptance criteria:

- a new task can identify the repository, current capability boundary, test
  commands, branch convention, and pause conditions without restating them;
- the Roadmap explicitly distinguishes completed and planned capabilities;
- documentation changes pass whitespace/link/path review and CI.

Out of scope: retrieval or product behavior changes.

## M2 — Versioned neural Embedding and Vector Retrieval

Status: **In progress** — branch `feature/embedding-retrieval`; Draft PR
[#4](https://github.com/ZhangHan200005/EcoData_Extraction/pull/4)

Goal: introduce a real semantic retrieval backend without losing the current
offline, explainable baseline or the ability to compare results.

Smallest useful vertical slice:

1. Define an embedding/retrieval backend interface and versioned configuration.
2. Retain the existing hashing ranker as the default offline baseline.
3. Add one real neural Embedding backend after recording its model, dimension,
   license, download size, privacy behavior, and runtime requirements.
4. Store or cache vectors using document hash, block ID, model/version, and
   normalized-text hash so stale vectors cannot be reused silently.
5. Compare baseline and neural retrieval on versioned Gold queries.
6. Expose the active backend and score components in API/UI output.

Acceptance criteria:

- clean interfaces allow the baseline and neural backend to run against the
  same evidence blocks and query set;
- tests do not require an API key or live paid service;
- retrieval runs record backend, model/version, parameters, query count, corpus
  size, and elapsed time;
- evaluation reports Hit@K, Recall@K, MRR, and latency for both systems;
- failure cases are inspectable by query and evidence block;
- README labels results as fixture-scale until a representative evaluation set
  exists.

Two-hour first slice:

- add the backend contract and version metadata;
- add a deterministic comparison fixture with multiple field queries;
- add a benchmark/report shape that the neural implementation can fill;
- avoid claiming a neural gain until the actual model has been run.

First-slice implementation evidence:

- `EmbeddingBackend` defines a replaceable vector encoder contract with backend,
  model, version, dimension, parameters, and neural/non-neural metadata;
- the existing character n-gram hashing implementation remains the active,
  dependency-free default and retains the original hybrid ranking weights;
- retrieval runs persist backend/model identity, parameters, query count, corpus
  size, and elapsed time through a non-destructive SQLite schema migration;
- evaluation reports backend metadata, retrieval/evaluation latency, corpus work,
  and inspectable Gold/top-block IDs for each query;
- `synthetic-retrieval-comparison-v1` covers three fields over four synthetic
  blocks and runs both the production hashing backend and a clearly test-only,
  deterministic backend without network access or credentials. Configuration,
  reproducible command, fixture-scale results, and limitations are recorded in
  [the M2 first-slice evaluation](M2_RETRIEVAL_EVALUATION.md).

First-slice limitation: this slice proved the versioned interface and
comparison path, not a production neural model or a neural quality improvement.

Second-slice implementation evidence:

- SQLite now persists block vectors in `embedding_vectors` and reads/writes a
  whole retrieval corpus through one connection rather than one connection per
  block;
- cache identity includes document SHA-256, block ID, normalized-text SHA-256,
  backend/model versions, dimensions, embedding-parameter SHA-256, and an
  explicit cache-key version;
- cold, warm, document-change, text-change, model-version-change, and
  parameter-change paths are covered by offline tests;
- retrieval runs, evaluation reports, health output, and the UI expose cache
  enabled/hit/miss/write state;
- the local learning and implementation history is maintained in
  [the Chinese M2 guide](M2_IMPLEMENTATION_GUIDE_CN.md).

Third-slice implementation evidence:

- the optional local backend pins `intfloat/multilingual-e5-small` to commit
  `614241f622f53c4eeff9890bdc4f31cfecc418b3` and pins Sentence Transformers,
  Transformers, and PyTorch runtime versions;
- the model is lazy-loaded, uses asymmetric `query: ` / `passage: ` prefixes,
  batches cold passage encoding, normalizes vectors, and never silently falls
  back to hashing after the user selects the neural backend;
- core install and CI remain offline and model-free; a separate optional extra
  enables the real local path, and Python 3.10 compatibility has its own CI job;
- a frozen three-query synthetic comparison ran from local cached weights and
  reported Hit@1, Recall@1, MRR, latency, cache counts, backend/model versions,
  and per-query ranks for both hashing and the real model;
- both systems scored 1.0 on the tiny fixture, so no neural quality gain is
  claimed. Broader multi-paper Gold queries remain the next evidence target.

Fourth-slice implementation evidence:

- `POST /api/retrieve/compare` runs BM25-only, hashing hybrid, and E5 hybrid
  against the same document, field query, Top K, and verified Gold set;
- every available strategy persists its own retrieval run with strategy,
  weights, backend/model/version, cache counts, and elapsed time; BM25-only
  skips vector encoding rather than computing and discarding embeddings;
- the retrieval audit UI shows the three rankings side by side, including
  score components, rank movement relative to BM25, first Gold rank, Hit@K,
  Recall@K, model identity, and cold/warm latency;
- the optional E5 column reports an actionable unavailable state when the
  pinned runtime is absent, while BM25-only and hashing remain runnable;
- reviewers can mark Gold from any comparison column and load all current
  document blocks (up to the API's explicit 300-block review limit) for
  Top-K miss auditing.

Current M2 limitation: the real model path is runnable and measured, but the
frozen set is too small to establish quality or throughput beyond the bundled
Demo. Side-by-side interaction makes differences inspectable but does not turn
the synthetic corpus into representative evidence. The milestone remains **In
progress** while Draft PR #4 is reviewed and the broader Gold set is built.

Out of scope: LLM generation, OCR, and final field extraction.

## M3 — Schema-guided RAG structured extraction

Status: **Planned**

Goal: convert retrieved evidence into validated field candidates while keeping
model output separate from verified facts.

Scope:

- explicit target Schema with field definition, type, unit, required context,
  and evidence requirements;
- RAG context builder combining field definitions with Top-K evidence blocks;
- provider-neutral LLM adapter and prompt/extraction versioning;
- structured response validation and explicit `missing`, `conflicting`,
  `excluded`, and `failed` states;
- deterministic fake-provider tests plus optional live integration evaluation;
- value, evidence reference, model confidence/status, and review state for every
  candidate field.

Acceptance criteria:

- no field is accepted without valid source-evidence references;
- malformed or unsupported model output cannot enter verified records;
- offline CI covers success, missing evidence, conflicting evidence, invalid
  schema output, and provider failure;
- evaluation reports field accuracy, evidence hit rate, and processing time on
  a named fixture or correction set.

## M4 — Field provenance, quality rules, and export

Status: **Planned**

Goal: make every exported record auditable and safe for human correction.

Scope:

- record/field manifest connecting document hash, page, block, evidence text,
  bounding box where available, parser version, retrieval version, extraction
  version, and reviewer state;
- schema validation, range rules, cross-field consistency checks, unit parsing,
  and unit conversion with original values retained;
- JSON and CSV export plus machine-readable provenance manifest;
- review history that distinguishes model prediction, rule warning, human edit,
  and verified output.

Acceptance criteria:

- every exported field can be traced back to the original evidence;
- unit conversions are reversible and tested against a versioned fixture;
- exports include warnings and missing/conflicting states rather than silently
  dropping them;
- evaluation adds unit-conversion accuracy and human modification rate.

## M5 — OCR and table-aware parsing

Status: **Planned**

Goal: improve evidence coverage across scanned and table-heavy PDFs.

Scope:

- detect text-layer, scanned, and mixed PDFs;
- isolate OCR behind a provider/tool interface with page-level status;
- extract table cells, captions, headers, page, and coordinates into evidence
  blocks that retrieval and provenance can consume;
- preserve raw OCR/table output alongside normalized text;
- add redistributable scanned and table fixtures.

Acceptance criteria:

- failures are classified per document/page instead of disappearing;
- text, OCR, and table evidence share stable provenance contracts;
- table recall and OCR evidence recall are reported on named fixtures;
- CI can run a bounded fixture without private PDFs or paid services.

## M6 — Literature discovery and PDF acquisition

Status: **Planned**

Goal: produce a reproducible document candidate manifest before parsing.

Scope:

- integrate literature search behind a provider interface, beginning with the
  preserved OpenAlex candidate work only after review against current main;
- store query, source ID, DOI, title, authors, year, access URL, license/access
  state, and deduplication decision;
- distinguish metadata discovery from legal PDF availability and successful
  local acquisition;
- prevent duplicate records across DOI, source IDs, and document hashes.

Acceptance criteria:

- a fixed query produces an inspectable candidate manifest;
- tests use recorded public metadata fixtures rather than live network access;
- acquisition status and failure reasons are explicit;
- no workflow bypasses copyright, access-control, or redistribution rules.

## M7 — Human review evaluation and portfolio release

Status: **Planned**

Goal: measure system quality and failure modes across the complete workflow.

Scope:

- versioned human correction set covering multiple PDF layouts and field types;
- review queue, edit history, reviewer status, and failure taxonomy;
- end-to-end timing and per-stage diagnostics;
- comparison tables for retrieval, extraction, evidence, unit, review, and
  runtime metrics;
- resume-facing Demo and release documentation grounded in measured behavior.

Acceptance criteria:

- report dataset/fixture composition and denominators for every metric;
- report field accuracy, evidence hit rate, human modification rate, unit
  accuracy, table recall, and processing time where supported;
- document common failure types and the next corrective experiment;
- a new user can reproduce the public Demo from a clean clone;
- `main` is green and a tagged release matches the documented capability set.

## Evaluation contract

Metrics must be tied to versioned inputs and configurations.

| Stage | Required metrics/evidence |
| --- | --- |
| Parsing | parse success by PDF type, page/block counts, classified failures |
| Retrieval | Hit@K, Recall@K, MRR, query/corpus count, latency |
| Table retrieval | table recall with named Gold table/cell evidence |
| Extraction | field accuracy, missing/conflict counts, evidence hit rate |
| Units and rules | conversion accuracy, warning precision where available |
| Human review | modification rate, verified/rejected counts, review time |
| End to end | document and field throughput, total and per-stage time |

Do not compare numbers produced from different fixtures, schemas, or evaluation
definitions without labeling the difference.

## Milestone update checklist

When a milestone changes status:

1. Record its branch and PR in this document.
2. Update the verified baseline and public README feature-status sections.
3. Update `docs/ARCHITECTURE.md` if data flow or module ownership changed.
4. Record evaluation configuration, results, and limitations.
5. Confirm tests and GitHub CI pass.
6. Move the next accepted milestone to **In progress** only when work actually
   begins.
