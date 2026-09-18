# CI Showcase Training Modules

Self-contained, story-driven training for large-scale CI/CD and Developer
Productivity engineering (target: staff-level CI infrastructure roles).
Each module file carries its own narrative, ordered steps with why/order
justification, progress tracker, and session log — no chat scrolling required.

## Module index
- `module-01-branch-protection.md` — governance gates: branch protection,
  CODEOWNERS, linear history, `ci-gate`, merge queues. Status: enforced.
- `module-02-feedback-loops.md` — pipeline speed: pip caching, matrix builds,
  two-tier test split, benchmarks. Status: complete, CI wall-times pending.
- `module-03-flake-quarantine.md` — flake detection + quarantine tiers,
  manifest validation, CODEOWNERS escape-hatch guard. Status: Phase A
  complete (commit `94bb5be`).
- `module-04-containers-k8s.md` — hardened image (pinned digest, non-root),
  GHA layer cache, blocking Trivy, CronJob sample + kubeconform validation.
  Status: implemented, CI baselines pending.
- `module-05-developer-cli.md` — (planned) developer-facing CLI tooling.
- `module-06-merge-queues.md` — (planned) merge queues at scale.

## Resume protocol ("where did we leave off?")
A new session restores context with three reads, in order:
1. Latest `training_progress` cognitive-memory episode.
2. Unfinished checkboxes in `docs/modules/module-*.md` trackers.
3. `git log --oneline -5` on `ci-showcase`.

## Module workflow (standing SOP)
Every module follows: resume protocol → draft initial plan → `researcher`
enterprise gap audit (standing user-authorized trigger after each initial
plan; researcher reports findings only, never implements) → main agent
orchestrates findings into Phase A/B/C and seeks scope approval → implement
the approved phase → verify, update tracker/session log, record a
`training_progress` episode. Commit/push only on explicit request.

## End-of-day check ("are the logs current?")
Before closing a training day, verify:
- [ ] Module tracker checkboxes + session logs reflect today's work.
- [ ] A matching `training_progress` episode was logged.
- [ ] `git status` shows all training files committed; `git push` done.
- [ ] `git diff --stat` does NOT list `progress.md` (no ledger entries on
  training branches — `finance wrap-up` never runs on `ci-showcase`).

## Merge checklist (main stays clean)
- Training lives on `ci-showcase`; no PRs/merges to `main` without explicit opt-in.
- Always reject any merge carrying the `CI-SHOWCASE ONLY` marker (see `Agents.md`
  training section) into `main`.
