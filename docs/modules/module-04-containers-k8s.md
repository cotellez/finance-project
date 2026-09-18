# Module 4: The Container That Worked on My Machine

## 1. Narrative & Root Cause Analysis
* **The Incident (Symptom):** The finance CLI runs fine on every laptop but
  behaves differently in CI and in scheduled batch runs: a rebuilt image
  pulls a newer `python:3.12-slim` with a breaking OpenSSL change, the
  nightly report job CrashLoops because someone wrapped the CLI in a
  Kubernetes `Deployment`, and nobody notices a critical CVE in the base
  image for six months because nothing scans it.
* **Why the Narrative Happened (Systemic Flaw):** The container pipeline has
  no supply-chain controls (floating base tag, root runtime, no scan), no
  build economics (every PR rebuilds every layer from scratch), and no
  workload-shape discipline (exit-0 CLI treated like a long-running
  service). Each gap is individually survivable; together they make the
  image unreproducible, untrusted, and undeployable.
* **Are We Fixing the Symptom or the System?** We are fixing the **system**.
  Rebuilding until green is the band-aid. A pinned, non-root, cached,
  scanned image plus validated batch-shaped manifests permanently makes the
  container reproducible and the gate meaningful.

---

## 2. Step-by-Step Breakdown & Order Justification

### Step 1: Harden the Dockerfile (`Dockerfile`)
* **How-To:** Pin `python:3.12-slim` to its linux/amd64 digest with a comment
  recording the tag, digest date, and the Dependabot refresh trigger; run as
  non-root `apprunner` (uid 10001) with ownership of `/app` since the CLI
  writes `*.db`/`*.json` state into the workdir; keep metadata-before-source
  COPY order; document why there is no `HEALTHCHECK` (exit codes are the
  health contract for an exit-0 CLI). Single-stage stays: the researcher
  audit rejected multi-stage as overkill for a pure-Python CLI with no
  compiled extensions (revisit trigger: image exceeding ~500MB).
* **The "Why":** The base image is the largest unmanaged dependency in the
  repo. A floating tag means today's green build and tomorrow's red build
  can differ with zero code changes; root + unowned workdir turns a
  security fix into a runtime crash.
* **Why This Order:** The image definition is the contract everything else
  (cache, scan, manifests) operates on — harden the artifact before
  optimizing or scanning it.

### Step 2: GHA layer caching (`ci.yml` docker job)
* **How-To:** `docker/setup-buildx-action@v3` +
  `docker/build-push-action@v6` (`load: true`, `tags: finance:ci`,
  `cache-from/to: type=gha`). Scoped `actions: write` on the docker job
  only — the GHA cache API needs cache write, and the permission stays off
  the top-level token. `Report image size` step emits the size line for the
  baselines below. Closes the Module 2 docker-cache tech-debt item.
* **The "Why":** Unchanged layers restore from cache instead of rebuilding
  (pip install of NumPy/SciPy/Pandas is minutes per run). This is the same
  economics as the pip cache in Module 2, applied to image layers.
* **Why This Order:** Caching is only trustworthy on top of a pinned base
  (Step 1) — otherwise the cache restores speed but not reproducibility.

### Step 3: Blocking vulnerability scan (Trivy)
* **How-To:** `aquasecurity/trivy-action` on `finance:ci`,
  `severity: CRITICAL,HIGH`, `ignore-unfixed: true`, `exit-code: 1`.
  Scope decision (user-approved full hardening): blocking now, not advisory.
  `ignore-unfixed` is the load-bearing flag — it keeps the gate to fixable
  CVEs so unpatchable upstream noise cannot hold merges hostage (the same
  principle as quarantine: signal without fleet-blocking noise).
* **The "Why":** An unscanned image accumulates CVEs silently; a scan that
  cannot fail the build is scenery. Blocking on fixable CRITICAL/HIGH makes
  supply-chain risk merge-blocking like any other test failure.
* **Why This Order:** Scan the cached, pinned image (Steps 1–2), not a
  moving target — otherwise failures cannot be attributed to code vs base.

### Step 4: K8s manifest validation (`k8s/`, `k8s-validate` job)
* **How-To:** Training-only `k8s/cronjob.yaml` (weeknight `finance report`,
  `restartPolicy: OnFailure`, resource requests/limits, history limits)
  validated by kubeconform (`-strict -summary`) in CI and gated by
  `ci-gate`. Manifests are validated, never applied. Workload shape is the
  point: the researcher audit killed the draft's `Deployment` (an exit-0
  CLI under a Deployment CrashLoops forever) — batch CLI execution belongs
  in a `Job`/`CronJob`, where exit is the expected terminal state.
* **The "Why":** Manifest errors are cheapest at PR time; an invalid or
  mis-shaped manifest that reaches a cluster is an incident. CI validation
  is the `ci-gate` equivalent for infrastructure-as-data.
* **Why This Order:** Validate only after the image contract is stable
  (Steps 1–3) — manifests reference `finance:ci`, and scanning must pass
  before any manifest deserves a green signal.

---

## 3. Researcher Audit Outcomes (2026-09-17)
* **Critical — Deployment rejected:** draft Step 4 specified a `Deployment`;
  replaced with `CronJob`. Lesson: workload shape (exit-0 batch vs
  long-running service) dictates the K8s kind, not habit.
* **High — non-root vs state writes:** `USER 10001` ships with `chown /app`
  so `*.db`/`*.json` writes keep working; verified by the smoke step.
* **High — digest without updater:** pin documented with refresh trigger
  (Dependabot/Renovate on first audit/compliance requirement).
* **Medium — multi-stage rejected:** single-stage stays until compiled deps
  push the image past ~500MB.
* **Medium — scan blocking now:** advisory-first was the researcher default;
  user approved full hardening, mitigated by `ignore-unfixed`.
* **Medium — health contract:** exit codes documented; no `HEALTHCHECK`.

---

## 4. Baselines (record after first `ci-showcase` push)
* Image size (`Report image size` step): ___
* Docker job wall-time, cached rebuild (PR touching only `src/`): ___
* Docker job wall-time, cold cache: ___
* kubeconform resolved version (then pin it): ___
* Trivy CRITICAL/HIGH fixable count at baseline: ___

---

## 5. Documented tech debt (do NOT implement at this scale)
- **Registry push + signed provenance:** `push: true` on `main` with
  cosign signatures and SBOM attestations. Trigger: any real deployment
  target (today there is none — manifests are training-only).
- **Dependabot/Renovate digest bumps:** automated base-image updates.
  Trigger: first external audit/compliance requirement (see Step 1).
- **Pinned kubeconform:** today's job resolves `latest` at runtime; pin to
  the Section 4 version after the first green run.
- **Action-version automation:** Trivy/build-push pins refreshed by
  Dependabot. Same trigger as digest bumps.

---

## 6. Module Progress & Verification Tracker

- [x] **Step 0:** Scope agreed (full hardening: Dockerfile + cache +
  blocking Trivy + K8s sample; researcher audit consumed).
- [x] **Step 1:** Dockerfile pinned, non-root with owned workdir, no
  HEALTHCHECK by documented design, single-stage kept deliberately.
- [x] **Step 2:** Buildx + GHA layer cache, scoped `actions: write`,
  image-size reporting.
- [x] **Step 3:** Blocking Trivy (`CRITICAL,HIGH`, `ignore-unfixed`).
- [x] **Step 4:** `k8s/cronjob.yaml` sample + kubeconform validation gated
  by `ci-gate`; `/k8s/` added to CODEOWNERS.
- [ ] **Step 5:** Verification — YAML parses, suite green, baselines in
  Section 4 recorded after first push, hygiene clean.

---

## 7. Session Log & Troubleshooting
* **Session Date:** 2026-09-17
* **Branch:** `ci-showcase`
* **Actions Taken:**
  - Ran the standing SOP: resume protocol → draft plan → researcher audit
    (returned 6 findings, 1 critical) → merged into phases → user approved
    full hardening.
  - Rewrote `Dockerfile` (digest pin, non-root, layer-order note, no
    HEALTHCHECK rationale), added `k8s/cronjob.yaml`, reworked the CI
    `docker` job (build-push + cache + size + smoke + Trivy), added the
    `k8s-validate` job, extended `ci-gate`, added `/k8s/` to CODEOWNERS.
* **Errors / Edge Cases Encountered:**
  - No local Docker daemon: base digest resolved via Docker Hub API
    (linux/amd64 `sha256:2fe5…ce79`, pushed 2026-09-01); local image build
    and Trivy run deferred to CI — YAML parse + suite green verified
    locally, build/scan proof comes from the Actions run after push.
* **Key Learnings:**
  - Workload shape dictates K8s kind: exit-0 CLIs are Jobs, not Deployments.
  - `ignore-unfixed` is to image scanning what quarantine is to tests:
    the mechanism that keeps signal from becoming fleet-blocking noise.
  - GHA layer cache needs `actions: write` — scope it to the one job that
    writes cache, never the top-level token.
