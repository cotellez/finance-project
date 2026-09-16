# Module 1 — Branch Protection, Status Checks & Merge Safety

## Narrative: The Friday Afternoon Main-Branch Outage
At 4:55 PM Friday, an engineer pushes a typo fix directly to `main`.
No branch protection, no required checks. Broken syntax lands.
Weekend batch jobs fail. Monday research builds for 150 engineers are locked.

## Are we fixing the incident or the system?
Both, in order:
1. **Symptom (immediate):** revert the bad commit, re-run CI green.
2. **System (this module):** make that class of incident *structurally impossible*.
   Relying on discipline ("please don't push to main") always fails at scale.
   Governance (protection + required checks + owners + linear history)
   must come before speed optimizations (Module 2+).

## Step order and why

### Step 1 — Lock `main`: branch protection + required status check (DO FIRST)
**Why first:** all other automation is bypassable if `git push origin main` works.
Protection is the only gate that blocks direct pushes and unreviewed merges.

**How-To (GitHub UI — 5 min, manual because `gh` has no auth here):**
1. Repo → Settings → Branches → Add classic branch protection rule
2. Branch name pattern: `main`
3. Check:
   - [x] Require a pull request before merging
     - Required approvals: 1
     - [x] Require review from Code Owners (enforces `.github/CODEOWNERS`)
     - [x] Dismiss stale pull request approvals when new commits are pushed
   - [x] Require status checks to pass before merging
     - [x] Require branches to be up to date before merging
     - Search and add required check: **`ci-gate`**
       (stable aggregator job in `.github/workflows/ci.yml` — do NOT pin
       matrix names like `fast (py 3.12)`; require the gate instead)
   - [x] Require linear history
   - [x] Do not allow bypassing the above settings
4. Save. Verify: try `git push origin main` from a test branch — expect rejection.

**Why `ci-gate` and not each job:**
Matrix jobs emit dynamic check names per Python version. Pinning them in
protection rules is brittle. `ci-gate` (needs: fast, slow, docker, flake-report,
`if: always()`) stays red if any upstream fails/cancels, green only on full pass.
Merge queue and protection both require this one stable name.

### Step 2 — CODEOWNERS: who approves what (DO SECOND)
**Why second:** once pushes are blocked, define *who* can approve PRs.
Prevents random approvals on risk/valuation/portfolio math.

**How-To:** file already added at `.github/CODEOWNERS`.
- `* @cotellez` (replace with your handle/team)
- Critical paths (`risk_guardrails.py`, `valuation.py`, `portfolio.py`,
  `backtest.py`) + infra (`.github/`, `Dockerfile`, `pyproject.toml`) pinned.
- Protection rule above enforces "Require review from Code Owners".

**Verify:** open a PR touching `src/finance/risk_guardrails.py` — GitHub
auto-requests the owner, merge button stays blocked until they approve.

### Step 3 — Linear history + squash merges (DO THIRD)
**Why third:** hygiene after access control. Merge commits create spaghetti
graphs that break `git bisect` during outages.

**How-To:**
1. Repo → Settings → General → Pull Requests:
   - [x] Allow squash merging (default)
   - [ ] Allow merge commits → uncheck
   - [ ] Allow rebase merging → uncheck (optional; squash-only is cleanest)
2. Protection rule already requires linear history (Step 1).

**Verify:** merge a test PR via Squash → `git log --oneline --graph` shows
a straight line, one commit per PR.

### Step 4 — Merge queue (finishes Module 1, leads into Module 6)
**Why last:** queue needs all gates above green first, otherwise it just
serializes broken merges.

**How-To:**
1. Repo → Settings → General → Pull Requests → [x] Allow merge queue
2. Settings → Branches → edit `main` protection → [x] Require merge queue
3. Workflow already handles `merge_group` trigger + `concurrency:
   group: ci-${{ github.ref }}, cancel-in-progress: true`.
4. Required check for queue: `ci-gate`.

## Credential hygiene (OIDC-safe default)
- Top-level `permissions: contents: read` in `ci.yml`, per-job `contents: read`.
- No long-lived secrets in workflow. Future cloud deploys must use OIDC
  (`id-token: write` + cloud IAM role) — never hardcoded keys
  (see AGENTS.md Rule 1).
- No `gh` auth available in this shell (`gh: command not found`), so all
  GitHub-side toggles above are manual UI steps, verified by a test PR.

## Verification checklist (Module 1 done when)
- [ ] Direct `git push origin main` rejected
- [ ] PR without approval cannot merge (CODEOWNERS requested)
- [ ] PR with red `ci-gate` cannot merge
- [ ] Merged PR appears as single squash commit, linear graph
- [ ] Merge queue validates batched PRs via `merge_group` runs
