# RivalRadar — Evaluation Results

All numbers on this page were produced by running the pipeline. Nothing is estimated, extrapolated or hand-written. Reproduce with:

```bash
rivalradar evaluate
```

Raw output is preserved in `data/reports/` as both text and JSON.

---

## Wayback Machine benchmark

**Method.** For each target URL the evaluator queries the Internet Archive CDX API from both ends of the date window, selects the two most widely separated captures with distinct content digests, downloads both through the `id_` raw endpoint (which suppresses the Archive's injected toolbar), and runs the real diff → noise-filter → classify → score pipeline over them.

The LLM is deliberately excluded so the benchmark is reproducible and free. It measures the deterministic detection layer.

**Run date:** 2026-09-19 · **Window:** 2023-01-01 → 2025-01-01 · **Targets:** 12 (10 evaluated)

```
RivalRadar Evaluation
=====================

Pages evaluated: 10

Raw changes:        1318
Noise changes:      930
Meaningful changes: 388

Noise reduction:    70.56%

High-impact changes: 12
```

### Per-page results

| Website | Snapshots compared | Raw | Noise | Meaningful | High impact | Noise reduction |
|---|---|---:|---:|---:|---:|---:|
| news.ycombinator.com | 2023-01-01 → 2025-01-01 | 327 | 212 | 115 | 1 | 64.8% |
| www.docker.com | 2023-01-01 → 2025-01-01 | 314 | 298 | 16 | 0 | 94.9% |
| redis.io | 2023-01-01 → 2025-01-01 | 216 | 133 | 83 | 6 | 61.6% |
| fastapi.tiangolo.com | 2023-01-03 → 2024-12-19 | 206 | 153 | 53 | 3 | 74.3% |
| nodejs.org | 2023-01-01 → 2025-01-01 | 76 | 52 | 24 | 2 | 68.4% |
| www.postgresql.org | 2023-01-01 → 2025-01-01 | 71 | 18 | 53 | 0 | 25.4% |
| www.python.org | 2023-01-01 → 2025-01-01 | 39 | 27 | 12 | 0 | 69.2% |
| www.djangoproject.com | 2023-01-01 → 2024-12-31 | 28 | 8 | 20 | 0 | 28.6% |
| www.sqlite.org | 2023-01-01 → 2024-12-31 | 6 | 2 | 4 | 0 | 33.3% |
| jquery.com | 2023-01-01 → 2025-01-01 | *(see report)* | | | | |
| **Total** | | **1318** | **930** | **388** | **12** | **70.6%** |

Two targets could not be evaluated, and the run reports that rather than hiding it:

- `flask.palletsprojects.com` — no archived captures in the requested window.
- `kubernetes.io` — CDX API timed out after three retries with backoff.

### Detection categories

| Category | Meaningful changes |
|---|---:|
| Other | 334 |
| Integrations | 32 |
| Product | 11 |
| Features | 8 |
| Messaging | 3 |

---

## Demo pipeline

Seeding runs the real pipeline over six fictional competitor pages, each carrying planted signals (a price rise, a plan-limit change, an AI feature launch, an ML hiring spree, new integrations) mixed with planted noise (rotating session IDs, copyright years, visitor counters, cookie banners, nav changes).

```bash
rivalradar seed
```

```
Raw changes detected:      55
Noise / irrelevant:        34
Meaningful changes:        21
High-priority changes:     14

Noise reduction:           61.8%
```

### What the filter rejected, and why

| Noise reason | Count |
|---|---:|
| canonically identical (whitespace/dynamic tokens only) | 24 |
| content too short to be meaningful (<12 chars) | 8 |
| magnitude below threshold | 1 |
| live counter / social-proof number churn | 1 |

### What it kept

| Category | Count |
|---|---:|
| Features | 5 |
| Pricing | 4 |
| Hiring | 4 |
| Product | 3 |
| Integrations | 2 |
| Messaging | 1 |
| Other | 2 |

Top-ranked detections, as scored by the pipeline:

| Severity | Score | Competitor | Detection |
|---|---:|---|---|
| Critical | 96 | NovaStack | Price increase `Rs 999/month → Rs 1,499/month` |
| Critical | 95 | DataForge | Price increase `$49 per month → $79 per month` |
| High | 84 | NovaStack | AI capability messaging added |
| High | 78 | NovaStack | Plan entitlement `5 projects → 10 projects` |
| High | 78 | DataForge | Product launch language detected |

---

## Test suite

```bash
pytest
```

```
310 passed
```

Covering scraping (success, HTTP errors, timeouts, retries, DNS failures, redirect SSRF), normalisation, diffing, classification, relevance scoring and banding, LLM output validation and fallback, Wayback client behaviour, seeding integrity, and the REST API end to end.

---

## Honest reading of these numbers

**The 70.6% benchmark figure is measured on general-purpose websites, not competitor pages.** The suite deliberately targets long-lived sites with dense archive coverage (language homepages, documentation, news) because they have reliable two-year histories. Those pages are mostly prose, so a large share of what survives filtering is genuine content change that simply isn't a *competitive* signal — which is why `Other` dominates the category breakdown (334 of 388).

On pages the product is actually aimed at — pricing tables, careers pages, product pages — the classifier has far more to work with, and the demo run shows the full category spread. The two figures answer different questions: the benchmark shows the noise filter works on real-world HTML at scale; the demo shows the classifier works on the page types the product targets.

**Per-page variance is wide (25%–95%) and that is expected.** A page's noise ratio depends on how much chrome it carries. `docker.com` is a heavily componentised marketing site (94.9% noise); `postgresql.org` is a sparse, largely static page whose changes are mostly real content (25.4%). A single averaged number hides this, so the per-page table is reported alongside it.

**High-impact counts are low on the benchmark (12) by design.** The high-impact band requires relevance ≥ 70, which effectively requires pricing, hiring or launch signals. General websites rarely produce them. This is the scorer behaving correctly, not under-detecting.

---

## Citable claims

Based on the runs above, the following are accurate:

- Processed **1,318 raw website changes** across 10 real websites spanning a two-year archive window.
- Filtered **930 changes (70.6%)** as noise using nine deterministic, individually-attributed rules.
- Surfaced **388 meaningful changes**, each with a category, a transparent 0–100 relevance score and a stored justification.
- Achieved up to **94.9% noise reduction** on heavily componentised marketing pages.
- **310 automated tests** passing.

Do not round 70.6% up to "80%+". The number is what the pipeline measured.
