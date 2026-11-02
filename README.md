# forge-standards

Declarative, versioned standards and coding profiles for the AI Forge. Git is canonical; the Forge database (`core.standards`, `core.profiles`) and
the memory (`mem.documents`, `source_kind = standard`) are read copies written by `python -m forge_core.standards sync`.

**Status of this release: `v0.2.1` — `proposed`. G27/G28 are owner-approved (Owner-Freigabe 2026-10-31); approval of the release as a whole is pending.** Every file carries `status: proposed`. Values that the source specification
marks as `ANNAHME` (assumption) are applied as written and listed per profile under `assumptions:`; they are to be confirmed or corrected by the owner.

## Layers (precedence top to bottom)

| Layer | Files | Changed by |
|---|---|---|
| 0 Owner principles | `owner/grundsaetze.yaml` (+ `grundsaetze.md`, a generated reading copy) | owner only |
| 1 Profile | `profiles/{spike,standard,produktion,kritisch}.yaml` | PR + owner approval |
| 2 Language | `languages/*.yaml`, `testing/standard.yaml` (test duties), `configs/*` (tool configs) | PR + planner review |
| 3 Project override | `.forge/project.yaml` in the project repo (`schema/project.schema.json`) | PR in the project |

An override may **tighten** a profile value freely. **Loosening** needs a `reason` and an `expires` date (in the future). **Nothing in layer 0 can be overridden.**
Strictness per key is declared in `schema/profile.schema.json` (`x-strict`); a key without a rule counts every change as loosening.

## Layout

```
owner/       grundsaetze.yaml  grundsaetze.md          principles G1-G28, cap <=30 (`short` form is what briefs carry)
profiles/    spike standard produktion kritisch .yaml    coder/review/judge, tests + thresholds, gates, budget, context, docs, deploy
languages/   python typescript bash sql docker rust common .yaml
testing/     standard.yaml                               test duties for all projects (levels, failing-first, mutation sample, flake policy, CI gate)
manifest.yaml                                                list of required files
docs/        review-checklist.md                     reviewer checklist items (profile `review.checklist_*`)
testkit/     g27_entrypoints.py g28_race.py ...      reusable Python test helpers for G27/G28 + self-test (see testkit/README.md)
configs/     ruff.toml .shellcheckrc .sqlfluff .hadolint.yaml .gitleaks.toml eslint.config.js
schema/      owner profile language testing project manifest .schema.json   JSON Schema (draft 2020-12), one per file kind
```

## Validation

Every YAML file validates against its schema; additionally the checker verifies: exactly the four profiles, file name equals `name`, one `version` across files,
`assumptions` paths resolve, `config_files` exist, tool configs parse, and `grundsaetze.md` equals the rendering of `grundsaetze.yaml`.

```
python -m forge_core.standards validate <checkout-of-this-repo>     # in the forge-core image or venv
```

## Versioning

SemVer tags (`v0.1.0`, `v0.1.1`, `v0.2.0`, ...); the `version` inside each file must equal the tag. Projects pin `standards_version`; an upgrade is one PR per project.

## Owner questions (section 7 of the spec) — defaults applied since v0.1.1

1. Thresholds: diff coverage 70/85/95 % and mutation score 60/80 % for standard/produktion/kritisch; to be tuned after 4 weeks of measurement.
2. Monthly API budgets 20/50/150/300 USD per profile as **soft** limits with owner info (`budget.hard: false`); hard only after measurement.
3. `kritisch` merge: planner GO + judge PASS (`gates.merge_approval: planner_go_judge_pass`); the owner is needed only for G11 topics.
4. Python type checker: `mypy --strict` (pyright only on demand).
5. Conventional Commits in English for all repos; old history stays.
6. Visibility: private; only the forge GitHub App reads.

## Required-file manifest

`manifest.yaml` lists every file that must exist at a tag (`required_files`). A checkout missing any listed file, or a manifest that drops a core file,
fails validation before anything is written. 

## Change log

See `CHANGELOG.md`.

## Not in this release

Reusable CI workflows, the nightly drift check and `standards.propose` are later steps.
