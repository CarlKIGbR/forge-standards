"""Self-test of the testkit: each helper must catch the defect it exists for, and must pass the correct code. Run: python -m unittest discover -s testkit -v"""
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g27_entrypoints import assert_fail_closed, check_entry_points, find_entry_points  # noqa: E402
from g28_race import EvidenceLog, Interleaver, all_schedules, assert_observed_before, hook_after, run_schedule  # noqa: E402

GOOD = '''
def guarded_dispatch(action, *, session, budget):
    if session is None or budget is None:
        raise PermissionError("rejected")
    return action()

def register_tool(t, *, session, budget):
    return guarded_dispatch(lambda: t, session=session, budget=budget)

class Hub:
    def publish(self, m, *, session, budget):
        return self._send(m, session, budget)
    def _send(self, m, session, budget):
        return guarded_dispatch(lambda: m, session=session, budget=budget)
'''
BYPASS = GOOD + '''
def release_fast(x):
    return x
'''
OPTIONAL = GOOD.replace("def register_tool(t, *, session, budget)", "def register_tool(t, *, session=None, budget=None)")


def tree(src: str) -> Path:
    d = Path(tempfile.mkdtemp()) / "pkg"
    d.mkdir()
    (d / "m.py").write_text(textwrap.dedent(src))
    return d


KW = dict(verbs=("register", "publish", "execute", "release"), guarded=("guarded_dispatch",), guard_params=("session", "budget"), exempt={})


class G27(unittest.TestCase):
    def test_enumerates(self):
        names = sorted(e.name for e in find_entry_points(tree(GOOD), KW["verbs"]))
        self.assertEqual(names, ["publish", "register_tool"])          # guarded_dispatch is not a verb; _send is private

    def test_good_tree_passes(self):
        r = check_entry_points(tree(GOOD), expected_count=2, **KW)
        self.assertTrue(r.ok, r.render())

    def test_bypass_is_caught(self):
        r = check_entry_points(tree(BYPASS), expected_count=3, **KW)
        self.assertFalse(r.ok)
        self.assertEqual([e.name for e in r.unguarded], ["release_fast"])

    def test_new_entry_point_changes_the_count(self):
        r = check_entry_points(tree(BYPASS), expected_count=2, **KW)
        self.assertTrue(any("expected 2" in p for p in r.problems))

    def test_optional_guard_param_is_caught(self):
        r = check_entry_points(tree(OPTIONAL), expected_count=2, **KW)
        self.assertEqual(len(r.optional_guard_params), 2)
        self.assertFalse(r.ok)

    def test_exemption_needs_reason_and_must_exist(self):
        kw = dict(KW, exempt={"pkg.m.release_fast": " ", "pkg.m.gone": "x"})
        r = check_entry_points(tree(BYPASS), expected_count=3, **kw)
        self.assertTrue(any("no reason" in p for p in r.problems) and any("stale" in p for p in r.problems))

    def test_exemption_with_reason_is_accepted(self):
        r = check_entry_points(tree(BYPASS), expected_count=3, **dict(KW, exempt={"pkg.m.release_fast": "pure function"}))
        self.assertTrue(r.ok, r.render())

    def test_guard_must_be_unique(self):
        r = check_entry_points(tree(GOOD + "\ndef guarded_dispatch(): pass\n"), expected_count=2, **KW)
        self.assertTrue(any("defined 2 times" in p for p in r.problems))

    def test_fail_closed_runtime(self):
        effects = []

        def closed(*, session, budget):
            if session is None or budget is None:
                raise PermissionError
            effects.append(1)

        def open_(*, session=None, budget=None):          # skips the check when state is missing
            effects.append(1)
        args = dict(session="s", budget=1)
        assert_fail_closed(closed, args, ["session", "budget"], rejects=(PermissionError, TypeError), side_effects=lambda: len(effects))
        with self.assertRaises(AssertionError):
            assert_fail_closed(open_, args, ["session", "budget"], rejects=(PermissionError,), side_effects=lambda: len(effects))


class Store:
    """Toy TOCTOU: delete a file only if it is still stale. `_stale` is the check, `_delete` the irreversible action."""
    def __init__(self, recheck: bool):
        self.stale, self.deleted, self.recheck, self.lock = True, False, recheck, threading.Lock()

    def _stale(self):
        return self.stale

    def cleanup(self):
        if self._stale():
            self._after_check()
            if self.recheck and not self._stale():     # G28: re-observe immediately before the irreversible step
                return False
            self.deleted = True
            return True
        return False

    def _after_check(self):
        pass

    def refresh(self):
        self.stale = False


class G28(unittest.TestCase):
    def race(self, recheck: bool) -> Store:
        s = Store(recheck)
        il = Interleaver()
        hook_after(s, "_after_check", il, "A.checked", only_thread="A")
        il.start("A", s.cleanup)
        il.wait_parked("A.checked")        # A saw "stale" and stands right before the delete
        s.refresh()                        # B: the file became fresh meanwhile
        il.release("A.checked")
        il.join("A")
        return s

    def test_race_detects_stale_snapshot_bug(self):
        self.assertTrue(self.race(recheck=False).deleted)       # the bug is reproduced every single run

    def test_race_passes_with_fresh_check(self):
        self.assertFalse(self.race(recheck=True).deleted)

    def test_repeatable(self):
        self.assertEqual({self.race(False).deleted for _ in range(25)}, {True})

    def test_unreleased_park_times_out_instead_of_hanging(self):
        il = Interleaver(timeout=0.2)
        il.start("A", lambda: il.park("p"))
        il.wait_parked("p")
        with self.assertRaises(TimeoutError):
            il.join("A")

    def test_thread_error_is_reraised(self):
        il = Interleaver()
        il.start("A", lambda: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            il.join("A")

    def test_schedule_order_decides_the_outcome(self):
        def make():
            st = {"v": 0, "log": []}

            def inc():
                x = st["v"]
                yield
                st["v"] = x + 1
            return st, {"a": inc, "b": inc}
        st, act = make()
        run_schedule(act, ["a", "b", "a", "b"])                 # both read 0 -> lost update
        self.assertEqual(st["v"], 1)
        st, act = make()
        run_schedule(act, ["a", "a", "b", "b"])
        self.assertEqual(st["v"], 2)

    def test_all_schedules_enumerates_every_interleaving(self):
        s = all_schedules({"a": 2, "b": 2})
        self.assertEqual(len(s), 6)
        self.assertEqual(s, sorted(s))

    def test_unfinished_actor_fails(self):
        def a():
            yield
        with self.assertRaises(AssertionError):
            run_schedule({"a": a}, ["a"])

    def test_evidence_log(self):
        ok = EvidenceLog()
        ok.observe("archive")
        ok.act("delete")
        assert_observed_before(ok, "delete", "archive")
        stale = EvidenceLog()
        stale.observe("archive")
        stale.observe("other")
        stale.act("delete")
        with self.assertRaises(AssertionError):
            assert_observed_before(stale, "delete", "archive")
        with self.assertRaises(AssertionError):                  # vacuous pass is refused
            assert_observed_before(EvidenceLog(), "delete", "archive")


if __name__ == "__main__":
    unittest.main()
