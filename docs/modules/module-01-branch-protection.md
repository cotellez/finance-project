# Module 1: Branch Protection, Status Checks, & Secure Control Planes

## 1. Narrative & Root Cause Analysis
* **The Incident (Symptom):** At 4:55 PM on Friday, an engineer pushes a minor typo fix directly to `main`. Because there are no branch protections or required status checks, the broken syntax bypasses review. Over the weekend, automated jobs fail across the board, locking out Monday morning research builds for 150 engineers.
* **Why the Narrative Happened (Systemic Flaw):** The repository lacked **governance controls and automated gating**. Relying on human discipline ("please don't push to main") always fails at scale.
* **Are We Fixing the Symptom or the System?** We are fixing the **system**. Reverting the bad commit only solves Friday's symptom; implementing branch protection, required status checks, and linear history prevents *any* unverified code from ever touching `main` again.

---

## 2. Step-by-Step Breakdown & Order Justification

### Step 1: Enforce Branch Protection & Required Status Checks on `main`
* **How-To:** On the **repository page** (`github.com/cotellez/finance-project`),
  click the repo-level **Settings tab** (top bar inside the repo — NOT your avatar
  menu → Settings, which is profile settings and has no Branches entry).
  Then Branches (or Rules → Rulesets on newer UI) targeting `main`. Check "Require a pull request before merging", "Require status checks to pass before merging" (targeting `ci-gate`), and linear history.
* **The "Why":** This is the ultimate defensive gatekeeper. It cryptographically and processually blocks any direct push or unreviewed merge.
* **Why This Order:** This must be Step 1 because all other checks (lint, tests, code owners) are useless if an engineer can bypass them with a direct push. Governance must precede automation.

### Step 2: Implement CODEOWNERS and Mandatory Reviewers
* **How-To:** Create a `.github/CODEOWNERS` file defining path-based ownership (`/src/finance/risk_guardrails.py @cotellez`, etc.) and enable "Require review from Code Owners" in branch protection.
* **The "Why":** Ensures domain experts review changes to critical code paths (risk guardrails, valuation engines) rather than just any random approver.
* **Why This Order:** Once `main` is locked down against direct pushes (Step 1), we must define *who* has the authority to approve PRs entering `main`.

### Step 3: Enforce Linear History & Squash Merges
* **How-To:** Enable "Require linear history" and "Allow squash merging" in repository settings, disabling merge commits.
* **The "Why":** Prevents messy, spaghetti merge graphs that make `git bisect` and incident root-cause analysis nearly impossible during a production outage.
* **Why This Order:** This is a hygiene step applied right after access control and ownership rules are established, ensuring clean git history hygiene for the controlled merge pipeline.

---

## 4. Advanced Staff-Level Enhancements

### A. Infrastructure-as-Code (IaC) via `gh api` (Scaling Beyond Click-Ops)
At Anthropic scale, managing branch protection across hundreds of repositories via UI clicks is an anti-pattern. Instead, repository policies are enforced programmatically via Terraform or the GitHub REST API (`gh api`).
* **Prereqs:** `gh` is the GitHub CLI — it is NOT bundled with Git Bash (MINGW64).
  Install it first (`winget install --id GitHub.cli` in PowerShell, restart Bash),
  then `gh auth login`. Replace `{owner}/{repo}` with your repo
  (e.g. `cotellez/finance-project`). UI path in `docs/ci-branch-protection.md`
  works with no CLI.
* **Example command to enforce branch protection programmatically:**
```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  -X PUT \
  -F required_status_checks[strict]=true \
  -F 'required_status_checks[checks][][context]=ci-gate' \
  -F enforce_admins=true \
  -F required_pull_request_reviews[required_approving_review_count]=1 \
  -F required_pull_request_reviews[dismiss_stale_reviews]=true \
  -F required_pull_request_reviews[require_code_owner_reviews]=true
```

### B. The 3 AM Break-Glass Protocol (Admin Bypass)
Strict branch protection can become a liability during a catastrophic production outage when CI itself is hung and an emergency hotfix must land immediately.
* **Break-Glass Procedure:**
  1. Incident Commander declares an SEV-1 outage.
  2. Designated Tech Lead with Admin privileges temporarily disables `enforce_admins=true` or bypasses checks via GitHub CLI/UI.
  3. Hotfix PR merges with explicit justification comment.
  4. Mandatory Post-Mortem required within 24 hours explaining why emergency bypass was necessary and how to prevent recurrence.

### C. Preventing the "Bait-and-Switch" PR Exploit (Stale Approvals)
* **The Rule:** Always enable **"Dismiss stale pull request approvals when new commits are pushed"**.
* **Why:** If an approver signs off on PR v1, but the author pushes modified or untested code in v2 right before merging, stale approval dismissal forces a re-review of the exact diff entering production.

---

## 5. Module Progress & Verification Tracker

- [x] **Step 1:** Audit CI workflow triggers and add stable `ci-gate` aggregator job in `.github/workflows/ci.yml`.
- [x] **Step 2:** Create `.github/CODEOWNERS` mapping critical paths to domain experts.
- [x] **Step 3:** Document branch protection, linear history, and merge queue configuration in `docs/ci-branch-protection.md`.
- [ ] **Step 4:** Apply branch protection rule in GitHub UI or via `gh api` and verify PR blocking (User Action).

---

## 6. Session Log & Troubleshooting
* **Session Date:** 2026-09-15
* **Branch:** `ci-showcase`
* **Actions Taken:**
  - Hardened `.github/workflows/ci.yml` with least-privilege permissions (`contents: read`), job timeouts, and the `ci-gate` job to act as a single required check.
  - Created `.github/CODEOWNERS` protecting quant/risk modules and infra configs.
  - Documented complete GitHub UI setup steps in `docs/ci-branch-protection.md`.
  - Created standalone self-contained training module document (`docs/modules/module-01-branch-protection.md`) incorporating IaC/API management, break-glass protocols, and stale review dismissal.
* **Errors / Edge Cases Encountered:**
  - Matrix jobs (`fast (py 3.12)`, `fast (py 3.13)`) generate dynamic names which are tedious to pin individually in branch protection. Solved by introducing the `ci-gate` aggregator job that depends on all matrix/slow/docker/flake jobs and acts as the single required status check.
* **Key Learnings:**
  - Governance must precede performance optimizations. Protecting `main` ensures no broken code enters production even as build speed increases. Staff-level engineering requires thinking beyond UI clicks to automated policy enforcement (IaC/API) and operational safety valves (break-glass).
