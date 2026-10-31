# testkit - reusable test helpers for G27 / G28

Dependency-free Python (3.11+, stdlib only). Copy the two modules into the project's `tests/` directory (or put a pinned checkout of this repo on `sys.path`);
the project pins `standards_version`, so the helpers are versioned with the standards.

| Module | Principle | Provides |
|---|---|---|
| `g27_entrypoints.py` | G27 one guarded path | `find_entry_points`, `check_entry_points` (static AST: every register/publish/execute/release function must reach the guarded function; optional bypass parameters; count), `assert_fail_closed` (runtime: missing state is rejected, with no side effect) |
| `g28_race.py` | G28 fresh evidence | `Interleaver` + `hook_after`/`hook_before` (park a thread at a named point, run the competitor, release), `run_schedule`/`all_schedules` (cooperative generators, exact or exhaustive order), `EvidenceLog` + `assert_observed_before` |
| `test_selftest.py` | both | the helpers catch what they are for (bypass, optional param, stale snapshot) and pass correct code |

Self-test: `python3 -I -m unittest discover -s testkit -v`

## G27 template

```python
from pathlib import Path
from g27_entrypoints import check_entry_points, assert_fail_closed

def test_every_entry_point_uses_the_protected_path():
    rep = check_entry_points(
        Path("src/myapp"),
        verbs=("register", "publish", "execute", "release"),
        guarded=("guarded_dispatch",),                 # exactly one definition in the tree
        expected_count=7,                              # counted; a new entry point fails until a reviewer counts it
        exempt={"myapp.docs.release_notes": "renders text only"},
        guard_params=("customer_data", "model_locks", "session", "budget"),
    )
    assert rep.ok, rep.render()

def test_guard_is_fail_closed():
    assert_fail_closed(guarded_dispatch, VALID_KWARGS, ["customer_data", "model_locks", "session", "budget"],
                       rejects=(Rejected,), side_effects=lambda: len(db.rows))
```

All arguments of `check_entry_points` are required: a helper that skipped a check when an argument is missing would break G27 itself.
Limits: resolution is by bare function name and static; dynamic dispatch (`getattr`, registries, decorators that hide the call) is not followed - give such paths an
explicit test or list them in `exempt` with the reason. Entry points outside Python (shell, SQL) need the same count by other means.

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
