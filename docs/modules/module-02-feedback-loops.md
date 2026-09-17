# Module 2: The 45-Minute Feedback Loop Death Spiral

## 1. Narrative & Root Cause Analysis
* **The Incident (Symptom):** As the codebase grows, the full suite takes 45 minutes
  per PR. Engineers stop waiting — they batch-merge blind, regressions slip in,
  velocity dies because feedback is too slow to trust.
* **Why the Narrative Happened (Systemic Flaw):** The pipeline is monolithic and
  single-threaded: every PR reinstalls all dependencies from scratch, runs every
  test (including heavy quant/market paths) on one runner, with no caching, no
  parallelism, and no conditional skip for irrelevant changes.
* **Are We Fixing the Symptom or the System?** We are fixing the **system**.
  Shaving seconds off one test is a band-aid; a cached, matrixed, two-tier
  pipeline with fail-fast gating permanently restores sub-minute feedback.

---

## 2. Step-by-Step Breakdown & Order Justification

### Step 1: Implement Robust Pip Caching (`actions/setup-python`)
* **How-To:** `actions/setup-python@v5` with `cache: 'pip'` and
  `cache-dependency-path: pyproject.toml` in every Python job
  (`ci.yml:47-52` fast, `ci.yml:104-110` slow).
* **The "Why":** `pip install` of NumPy/SciPy/Pandas/yfinance from scratch costs
  3–5 minutes per CI run — it dwarfs actual test time. Cached wheels restore the
  environment in ~15 seconds.
* **Why This Order:** Dependency installation is the prerequisite for everything.
  Optimize setup before optimizing execution. Status: already in `ci.yml` —
  verified during this module's audit.

### Step 2: Introduce Matrix Builds Across Python Versions
* **How-To:** `strategy.matrix.python-version: ["3.12", "3.13"]` with
  `fail-fast: false` on the fast job (`ci.yml:38-41`). `pyproject.toml`
  declares `requires-python = ">=3.12"`, so the matrix matches supported runtimes.
* **The "Why":** Catches version-specific breakage (typing changes, deprecations,
  stdlib behavior) before users hit it in production. `fail-fast: false` ensures
  one version's failure doesn't hide the other's signal.
* **Why This Order:** Once caching makes environments cheap (Step 1), fanning out
  across runtimes is nearly free. Status: already in `ci.yml` — verified.

### Step 3: Implement Two-Tier Test Splitting (Fast Unit vs Slow Quant/Market)
* **How-To:** Fast tier (`ci.yml:57-72`) runs 12 pure unit/logic files with
  `--junitxml=junit-fast.xml --durations=20`. Slow tier (`ci.yml:119-129`) runs
  6 heavy quant/market/broker files, `needs: fast` (fail-fast gating), with
  changed-files detection (`ci.yml:93-102`) that skips the tier entirely when a
  PR touches none of `src/`, `tests/`, `pyproject.toml`, `.github/`.
* **The "Why":** Developers get a fast signal without waiting on heavy paths;
  broken unit logic never burns quant-runner minutes; docs-only PRs skip the
  slow tier 100%.
* **Why This Order:** Splitting is only measurable on top of a stable cached
  environment (Steps 1–2). Status: already in `ci.yml` — verified.

### Step 4: Benchmark and Document CI Time Metrics
* **How-To:** Every test run emits `--durations=20` plus JUnit XML artifacts;
  `flake-report` prints the 10 slowest tests per file. Record local baselines
  below, then record CI wall-times from the Actions UI for the resume bullet.
* **The "Why":** Quantified deltas ("PR feedback from 45m → 2m30s") separate
  staff-level infra engineers from script runners at screening.
* **Why This Order:** You cannot measure an optimized system until all layers
  (cache, matrix, split) are in place. Status: baselines recorded this module.

---

## 3. Benchmark Results (local baseline, Windows, 2026-09-16)

| Tier | Files | Tests | Wall time |
|------|-------|-------|-----------|
| Fast (unit/logic) | 12 | 110 passed | **10.21s** |
| Slow (quant/market, mocked per AGENTS.md) | 6 | 34 passed | **4.09s** |
| Full suite (sequential) | 18 | 144 passed | **~14.3s** |

Slowest single test: `test_mcp_server_tools_and_resources` (0.30s). No test
exceeds 1s — the suite is fully mocked/offline by design, so **test time is not
the bottleneck here; environment setup is**. That is exactly why Step 1 (pip
cache, minutes saved per CI run) dominates the economics, Step 3's conditional
skip saves whole jobs on irrelevant PRs, and `needs: fast` gating avoids burning
slow-tier minutes on broken unit logic.

**Honest framing for the resume:** do NOT claim "cut tests from 45m to 14s" —
this repo never had a 45-minute suite. The transferable bullet is the
*architecture*: "Built cached matrix CI with two-tier fail-fast gating and
changed-files skip; JUnit timing telemetry on every run." CI-side wall times
(from Actions → upload after next push) go here when available:
- Fast (3.12): ___ · Fast (3.13): ___ · Slow: ___ · Setup (cached): ___

---

## 5. Advanced Enterprise Enhancements (post-benchmark gap review)

### Critical fix A — Cache-hit observability (implemented)
`actions/setup-python` hides cache hit/miss. Added `id: setup` plus a
`Report pip cache status` step in both tiers
(`echo "pip cache-hit=${{ steps.setup.outputs.cache-hit }}"`), so every run
logs proof of the setup-time saving and a poisoned cache is diagnosable.

### Critical fix B — merge_group made explicit (hardened, was incidentally covered)
Gap review initially flagged the changed-files gate as blind to `merge_group`.
Implementation check proved otherwise: `merge_group != pull_request`, so the
existing condition already ran the slow tier. Left as implicit, that guarantee
is invisible and one refactor away from silently breaking merge-queue
validation — so it is now an explicit first branch with a comment stating the
invariant (merge-queue batches must always run slow; a skip would let `ci-gate`
pass unvalidated). Lesson logged: verify before "fixing"; make implicit
guarantees explicit instead.

### Documented tech debt (do NOT implement at this scale)
- **Reusable setup workflow:** fast + slow duplicate setup-python/install.
  At monorepo scale extract to `.github/workflows/python-setup.yml`
  (`on: workflow_call`) and call it from both jobs. Trigger: 3rd duplicated
  setup block or 2nd repo reusing this pipeline.
- **Intra-tier sharding:** `pytest --splits --group` + matrix shards.
  Trigger: any single tier exceeding ~5 minutes.
- **Docker layer cache:** `docker/build-push-action` with `cache-from/to: gha`.
  Trigger: Docker job exceeding ~3 minutes on unchanged deps.
- **Affected-package mapping:** binary skip → monorepo `path_filters`.
  Trigger: repo split into independently releasable packages (Module 6 preview).
- **Timing trends:** JUnit artifacts default to 90-day retention with no trend.
  Add `retention-days: 7` + dashboard when flakes/history matter (Module 3).

---

## 6. Module Progress & Verification Tracker

- [x] **Step 1:** Verify pip caching in fast + slow jobs (`cache: pip`,
  `cache-dependency-path: pyproject.toml`).
- [x] **Step 2:** Verify matrix `["3.12", "3.13"]`, `fail-fast: false`,
  matching `requires-python = ">=3.12"`.
- [x] **Step 3:** Verify two-tier split (12 fast files / 6 slow files),
  `needs: fast` gating, changed-files conditional skip.
- [x] **Step 4:** Local benchmark recorded (110 in 10.21s / 34 in 4.09s).
- [x] **Step 5:** Enterprise gap review — cache-hit reporting added (both
  tiers), merge_group made explicit, tech debt documented above.
- [ ] **Step 6 (User Action):** After next `ci-showcase` push, record CI
  wall-times from Actions UI into Section 3 above and commit.

---

## 7. Session Log & Troubleshooting
* **Session Date:** 2026-09-16
* **Branch:** `ci-showcase`
* **Actions Taken:**
  - Audited `.github/workflows/ci.yml` against the Module 2 spec: Steps 1–3
    found already implemented (cache lines 47-52/104-110, matrix lines 38-41,
    split lines 57-72/93-102/119-129). No workflow edits needed.
  - Ran full local benchmark: fast tier 110 passed/10.21s, slow tier
    34 passed/4.09s, slowest test 0.30s.
  - Wrote this module document with baselines and honest resume framing.
* **Errors / Edge Cases Encountered:**
  - None in test execution. Both tiers green on first run (144/144).
  - Gap-review correction: the `merge_group` blind-spot flag was a false
    positive on re-read (`merge_group != pull_request` already ran slow).
    Resolved by making the coverage explicit rather than editing blindly.
* **Key Learnings:**
  - In a fully-mocked suite, setup time (pip install) dominates test time —
    caching is the highest-ROI optimization, not test sharding.
  - The split's value here is economic (skip + gate runner minutes), not
    wall-clock: conditional skip saves 100% of slow-tier cost on docs-only
    PRs, and `needs: fast` prevents burning quant minutes on broken units.
  - Never inflate metrics: report the architecture + measured numbers, not a
    fictional "before" time this repo never had.
