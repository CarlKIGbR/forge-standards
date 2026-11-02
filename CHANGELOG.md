# Changelog

## v0.2.1 - 2026-11-02 (proposed)

- **Profiles**: new required key `review.round_budget` (integer 1..5; schema `profile.schema.json`): the ADR-016 round budget per milestone - spike 1, standard 2, produktion 3, kritisch 3.
  forge-core mirrors it with the profile into `core.profiles.spec`; the run graph (F5c part 2, slice S3a) reads it from there - `config/graph.yaml` carries no round numbers.
- Same inventory as v0.2.0 (minor line 0.2): no forge-core inventory change needed. A forge-core before S3a ignores the key; a sync of v0.2.1 into a database is what makes the graph able to start milestones (a profile without the key is refused by the graph, fail closed).

## v0.2.0 - 2026-10-31 (proposed)

- **Owner principles G27, G28** (Owner-Freigabe 2026-10-31; sources F5c part 1, S2a, forge-node N1). Cap raised from <=25 to <=30 principles
  (`schema/owner.schema.json`: `maxItems` 30, id pattern up to G30).
  - G27 one guarded path: register/publish/execute/release run through exactly one path carrying all checks; no optional skip parameters; fail closed; a test counts all entry points.
  - G28 fresh evidence before irreversible decisions: re-observe immediately before abort/delete/publish/retry; races tested deterministically.
- **Profiles**: new keys `review.checklist_required` / `review.checklist_recommended` (schema: required keys, strictness `superset`). `kritisch`, `produktion`: G27+G28 required;
  `standard`: recommended; `spike`: none. Item texts: `docs/review-checklist.md`.
- **testkit/**: stdlib-only Python helpers `g27_entrypoints.py` (entry-point enumeration, guarded-path proof, fail-closed check), `g28_race.py` (hook/park interleaver,
  cooperative schedules, evidence log) with docs and a self-test.
- Rework after review (still v0.2.0, untagged): `check_entry_points` now requires the guard to dominate every return/end of the entry function on every path (was: any guard call in the call graph), gains the required `effect_calls` argument; new behavioural helper `assert_guard_failures_rejected`; docs state that the static check is necessary, not sufficient; checklist item G27 #6 asks for the behavioural test.
- `manifest.yaml` lists the new files. **Needs forge-core with a `0.2` inventory line** (`INVENTORY` in `forge_core/standards/repo.py`) before this tag can be validated or synced.

## v0.1.1

- Required-file manifest (the v0.1.0 checker accepted incomplete checkouts).

## v0.1.0

- Initial proposal: owner principles G1-G25, four profiles, language rows, test duties, tool configs, schemas.
