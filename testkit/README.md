# testkit - reusable test helpers for G27 / G28

Dependency-free Python (3.11+, stdlib only). Copy the two modules into the project's `tests/` directory (or put a pinned checkout of this repo on `sys.path`);
the project pins `standards_version`, so the helpers are versioned with the standards.

| Module | Principle | Provides |
|---|---|---|
| `g27_entrypoints.py` | G27 one guarded path | `find_entry_points`, `check_entry_points` (static AST: the guard call must **dominate every return / the end of the function on every path**; optional bypass parameters; effect calls before the guard; exact count), `assert_guard_failures_rejected` (**behavioural, required companion**: every counted entry point is invoked with guard-failing input and must reject without side effect), `assert_fail_closed` (guarded function: missing state rejected) |
| `g28_race.py` | G28 fresh evidence | `Interleaver` + `hook_after`/`hook_before` (park a thread at a named point, run the competitor, release), `run_schedule`/`all_schedules` (cooperative generators, exact or exhaustive order), `EvidenceLog` + `assert_observed_before` |
| `test_selftest.py` | both | the helpers catch what they are for (bypass, optional param, stale snapshot) and pass correct code |

Self-test: `python3 -I -m unittest discover -s testkit -v`

## G27 template

**The static check is necessary, not sufficient.** G27 needs both halves; a review accepts neither alone.

```python
from pathlib import Path
from g27_entrypoints import DROP, EntryCase, assert_fail_closed, assert_guard_failures_rejected, check_entry_points

REPORT = check_entry_points(
    Path("src/myapp"),
    verbs=("register", "publish", "execute", "release"),
    guarded=("guarded_dispatch",),                 # exactly one definition in the tree
    expected_count=7,                              # counted; a new entry point fails until a reviewer counts it
    exempt={"myapp.docs.release_notes": "renders text only"},
    guard_params=("customer_data", "model_locks", "session", "budget"),
    effect_calls=("send", "write_row"),            # must not run before the guard; () is allowed but must be stated
)

def test_static_every_path_passes_the_guard():
    assert REPORT.ok, REPORT.render()

CASES = {   # key = qualname of EVERY counted, non-exempt entry point (missing or unknown keys fail the test)
    "myapp.hub.Hub.publish": EntryCase(
        call=lambda **kw: Hub().publish(**kw),
        valid=dict(msg="m", session="s", budget=5, customer_data=False),
        failing={"no session": {"session": None}, "session dropped": {"session": DROP},
                 "budget exhausted": {"budget": 0}, "customer data not cleared": {"customer_data": True}},
    ),
}

def test_behaviour_guard_failures_are_rejected():
    assert_guard_failures_rejected(CASES, report=REPORT, rejects=(Rejected,), side_effects=lambda: len(db.rows))

def test_guard_is_fail_closed():
    assert_fail_closed(guarded_dispatch, VALID_KWARGS, ["customer_data", "model_locks", "session", "budget"],
                       rejects=(Rejected,), side_effects=lambda: len(db.rows))
```

What the static half does: for each entry function it walks `if`/`try`/`with`/loops/`match` and requires a call to the guarded function (or to an intra-tree helper that itself
passes the same test) before every `return` and before the function can end. A guard in only one branch, after an early return, after a swallowing `except`, behind `and`/`or`,
in a lambda/comprehension, or in a loop body that may not run does **not** count. `raise` ends a path as a rejection. Reported with line numbers, e.g.
`line 5: return without a guard call on this path`.

What it cannot do (hence the behavioural half): dynamic dispatch (`getattr`, registries, decorators that hide the call), aliasing (`g = guard; g()`), a guard that exists but is
fed the wrong value, effects hidden in calls not listed in `effect_calls`, bypass by data inside the guard itself, code outside the tree, non-Python entry points (shell, SQL).
Resolution is by bare function name; a helper name with several definitions counts only if all of them are guarded. All arguments are required on purpose: a helper that skipped a
check when an argument is missing would break G27 itself.

## G28 template (TOCTOU: observe -> decide -> irreversible action)

```python
from g28_race import Interleaver, hook_after

def test_cleanup_does_not_delete_a_file_that_became_fresh():
    il = Interleaver()
    hook_after(store, "_is_stale", il, "A.checked", only_thread="A")   # hook after the observation
    il.start("A", store.cleanup)
    il.wait_parked("A.checked")        # A has seen "stale", the action is next
    store.refresh()                    # competitor B runs completely, now
    il.release("A.checked")
    il.join("A")
    assert store.exists()
```

Rules: no `sleep`, no retry-until-green; every wait has a timeout that fails the test; the test must fail on the buggy implementation (run it once against the
variant without the re-observation). For many interleavings use `all_schedules` with `run_schedule`. `EvidenceLog`/`assert_observed_before` verifies in a
unit test that the re-observation is the event directly before the irreversible action.
