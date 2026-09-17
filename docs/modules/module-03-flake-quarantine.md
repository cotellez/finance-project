# Module 3: Flaky Tests Hold Merges Hostage

## 1. Narrative & Root Cause Analysis
* **The Incident (Symptom):** One intermittently failing test (timing-sensitive,
  network-shaped, order-dependent) goes red on 1 in 20 runs. Every PR starts
  failing at random. Engineers learn the ritual: re-run CI until green, then
  merge blind. Trust in the gate collapses — real regressions hide inside the
  noise, and `ci-gate` becomes a slot machine instead of a signal.
* **Why the Narrative Happened (Systemic Flaw):** The pipeline has no
  distinction between a *stable* failure (broken code, must block) and a
  *flaky* failure (unreliable test, must not block the fleet while it is
  fixed). One red test blocks every merge, so the team routes around the gate
  instead of fixing the test.
* **Are We Fixing the Symptom or the System?** We are fixing the **system**.
  Re-running until green is the band-aid. A quarantine manifest + non-blocking
  quarantine tier permanently restores the gate: stable tests keep blocking,
  known-flaky tests run separately as informational signal until promoted back.

---

## 2. Step-by-Step Breakdown & Order Justification

### Step 1: Quarantine manifest (`tests/quarantine.json`)
* **How-To:** A single JSON file, `{"quarantined": [<pytest node IDs>]}`,
  is the source of truth. Empty list = nothing quarantined (today's state).
  Entries are full node IDs (`tests/test_x.py::test_y`) so deselect/reselect
  is exact, reviewable in PRs, and auditable in git history.
* **The "Why":** A manifest beats markers/decorators at this scale: no code
  edits to quarantine, no new pytest plugins, quarantine changes are just
  data diffs any reviewer can approve.
* **Why This Order:** The manifest is the contract everything else reads.
  CI filtering, the quarantine job, and the promotion policy all key off it —
  define the data before the automation.

### Step 2: Stable tiers exclude quarantined tests (fast + slow)
* **How-To:** Fast and slow jobs read the manifest at run time and append
  `--deselect <nodeid>` per entry to their `pytest` invocation. Empty manifest
  = zero extra args = today's behavior unchanged.
* **The "Why":** A quarantined test must never block a PR. Filtering at the
  stable tier guarantees `ci-gate` stays green-signal even while the flake is
  being fixed.
* **Why This Order:** Gate integrity comes before observability. Exclude first
  so the very next flake cannot hold merges hostage; reporting (Steps 3–4)
  rides on top of a gate that already trusts itself.

### Step 3: Non-blocking quarantine job (informational signal)
* **How-To:** New `quarantine` job (`needs: fast`, `continue-on-error: true`)
  runs *only* the manifest-listed tests (`pytest <nodeids>`), uploads
  `junit-quarantine.xml` (`retention-days: 7`), and no-ops green when the
  manifest is empty. `ci-gate` lists it in `needs` for visibility but never
  blocks on its result — it echoes `quarantine=` separately and only gates on
  fast/slow/docker/flake.
* **The "Why":** Quarantined tests still run on every PR (signal preserved),
  but their failure mode is advisory. `continue-on-error` + gate exclusion is
  the mechanism that converts "red = blocked fleet" into "red = fix this test".
* **Why This Order:** The job is only meaningful once Step 2 defines what is
  excluded from stable. Building it first would double-run tests with no
  gating semantics.

### Step 4: JUnit telemetry + promotion policy (no bot at this scale)
* **How-To:** All JUnit artifacts (`fast`, `slow`, `quarantine`) use
  `retention-days: 7` (closes the Module 2 tech-debt item on unbounded
  90-day retention). `flake-report` already globs `junit-*.xml`, so quarantine
  results flow into the slowest-test summary with zero extra wiring.
  Promotion is manual and conservative: a test leaves the manifest only after
  7 consecutive green quarantine runs + a PR removing its entry with the
  evidence linked. New flakes enter via PR adding the node ID + a tracking
  note (no auto-file bot — explicit `issues: write` escalation reserved for
  the Full tier).
* **The "Why":** History without retention bounds is storage without insight.
  Manual promotion at this suite size (144 tests, 0 known flakes) beats bot
  complexity: every quarantine entry is a deliberate, reviewed decision.
* **Why This Order:** Policy last, mechanism first. A promotion rule means
  nothing until the manifest, filter, and quarantine job exist to enforce it.

---

## 3. Current State (2026-09-17, `ci-showcase`)

* Manifest: `tests/quarantine.json` = `{"quarantined": []}` — zero known flakes.
* Suite: 146 tests (144 existing + 2 quarantine-manifest contract tests),
  slowest single test 0.30s (Module 2 baseline). No test
  exceeds 1s; the quarantine tier is currently a green no-op by design.
* Scope for this module (agreed): **Minimal quarantine** — manifest + stable
  filtering + non-blocking job + `retention-days: 7`. Retry-detection and the
  issue-bot are explicitly deferred (see tech debt below).

---

## 4. Documented tech debt (do NOT implement at this scale)
- **Retry-based flake detection:** re-run failures once (`pytest --reruns`
  via `pytest-rerunfailures`, or a retry loop) and label pass-on-retry as
  flaky. Trigger: first recurring unexplained red that survives the manifest
  workflow, or suite growth past ~500 tests.
- **Issue bot:** `flake-bot` job with `issues: write` auto-filing on new
  quarantine failures, dedup by node ID. Trigger: quarantine list churn
  exceeding ~1 entry/week (manual PRs become toil).
- **Timing-trend dashboard:** aggregate JUnit history across runs to catch
  slow-creep before it becomes flake-creep. Trigger: any tier exceeding
  ~5 minutes (Module 2 sharding trigger).

---

## 5. Module Progress & Verification Tracker

- [x] **Step 0:** Scope agreed (Minimal quarantine, no bot, no new deps).
- [x] **Step 1:** Manifest contract documented (`tests/quarantine.json`,
  node-ID entries).
- [x] **Step 2:** Fast + slow jobs deselect manifest entries at run time.
- [x] **Step 3:** `quarantine` job runs manifest-only, `continue-on-error`,
  never blocks `ci-gate`.
- [x] **Step 4:** `retention-days: 7` on all JUnit artifacts; promotion policy
  recorded (7 green runs + PR).
- [x] **Step 5:** Verification — YAML parses, full suite green locally,
  `ci-gate` logic reviewed, hygiene clean.
- [x] **Step 6 (Phase A hardening):** Line-delimited quarantine args in
  fast/slow/quarantine; blocking manifest-vs-collection validation in fast;
  `CODEOWNERS` ownership for `tests/quarantine.json`.

---

## 6. Session Log & Troubleshooting
* **Session Date:** 2026-09-17
* **Branch:** `ci-showcase`
* **Actions Taken:**
  - Implemented Steps 1–4 in `.github/workflows/ci.yml`: run-time
    `--deselect` filtering in fast + slow, new `quarantine` job
    (`needs: fast`, `continue-on-error`, manifest-only, green no-op when
    empty), `ci-gate` now needs quarantine for visibility but gates only on
    fast/slow/docker/flake, `retention-days: 7` on all JUnit uploads.
  - Phase A hardening: added `tests/test_quarantine_manifest.py` and included
    it in the fast tier; replaced space-split quarantine args with
    line-delimited Bash arrays in fast/slow/quarantine; added a blocking
    manifest-vs-collection check in fast; added `/tests/quarantine.json`
    to `.github/CODEOWNERS`.
* **Errors / Edge Cases Encountered:**
  - None. Empty manifest keeps today's behavior identical; `if-no-files-found:
    ignore` covers the no-op quarantine upload; pytest exit 5 (no tests)
    avoided by early-exit when manifest is empty.
  - Local suite has no parametrized tests, so bracket/space handling was
    proven with synthetic IDs: old word-splitting produced 5 fragments from
    2 IDs, while line-delimited reads preserved exactly 2 entries.
* **Key Learnings:**
  - Proven locally: `--deselect <node>` drops suite 144 → 143, quarantine-only
    run executes the 1. Manifest-as-data keeps quarantine decisions as
    reviewable PR diffs with no plugin or decorator churn.
  - `continue-on-error` + gate exclusion is the load-bearing pair: either one
    alone still blocks or still hides signal; together they make quarantine
    advisory without losing it.
  - Manifest validation lives in fast rather than being duplicated in
    quarantine because quarantine `needs: fast` and job-level
    `continue-on-error` would hide a duplicate check there.
