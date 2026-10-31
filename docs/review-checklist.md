# Review checklist (profile key `review.checklist_required` / `review.checklist_recommended`)

The reviewer answers every listed item **in the review report**, with evidence (file:line, test name, command output). An unanswered **required** item is a
blocking finding; an unanswered **recommended** item is a non-blocking finding. Profiles: `kritisch`, `produktion` = required; `standard` = recommended; `spike` = not required.

## G27_entry_points — one guarded path (owner principle G27)

1. **Enumerate** every entry point in the diff and in the touched modules that registers, publishes, executes or releases (name them: `module.func`, `file:line`).
2. Name the **one guarded function** they all pass through, and the checks it carries: customer data, model locks, handle/session, budget (say which apply).
3. For each entry point: where does it reach the guarded function? An entry point without that path, or exempted, needs a written reason.
4. List every **optional parameter** on those functions whose absence could skip a check (a default `None`, `skip_*`, `force`, `bypass`). There must be none; missing state must reject (fail closed).
5. Point to the **counting test** (`testkit/g27_entrypoints.py` or equivalent) and confirm it fails when a new entry point bypasses the guard (name the mutation or the failing run that proves it).

## G28_fresh_evidence — fresh evidence before irreversible decisions (owner principle G28)

1. List every **irreversible action** in the diff: abort, delete, publish, retry/replay (and anything equivalent).
2. For each: name the **re-observation step** that happens immediately before it (what is read: file, log, archive, report, database; `file:line`). A snapshot taken earlier in the run, or passed in as an argument, does not count.
3. State what happens between the re-observation and the action (nothing that can change the state, or the action itself re-checks atomically, e.g. conditional UPDATE/DELETE, compare-and-swap, lock held).
4. Point to the **deterministic race test** (`testkit/g28_race.py` or equivalent: hook/park or fixed schedule, no sleeps) that changes the state between observation and action and shows the action is refused or safe.
5. No `sleep`-based or retry-until-green race test; a flaky race test is a finding.
