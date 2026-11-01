"""Self-test of the testkit: each helper must catch the defect it exists for, and must pass the correct code. Run: python -m unittest discover -s testkit -v"""
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g27_entrypoints import DROP, EntryCase, assert_fail_closed, assert_guard_failures_rejected, check_entry_points, find_entry_points  # noqa: E402
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


KW = dict(verbs=("register", "publish", "execute", "release"), guarded=("guarded_dispatch",), guard_params=("session", "budget"), effect_calls=(), exempt={})


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


class Dominance(unittest.TestCase):
    """Static check: the guard must be on EVERY path, not merely somewhere in the call graph (reviewer finding)."""

    def verdict(self, body: str, *, effects=(), count=1):
        src = "def guard(): pass\ndef send(x): pass\n\n" + textwrap.dedent(body)
        return check_entry_points(tree(src), verbs=("publish",), guarded=("guard",), expected_count=count, exempt={}, guard_params=(), effect_calls=effects)

    def bad(self, body, **kw):
        r = self.verdict(body, **kw)
        self.assertFalse(r.ok, "bypass was accepted:\n" + body)
        self.assertEqual([e.name for e in r.unguarded], ["publish"], r.render())

    def good(self, body, **kw):
        r = self.verdict(body, **kw)
        self.assertTrue(r.ok, r.render())

    def test_reviewer_conditional_bypass_fails(self):
        self.bad("""
            def publish(data, trusted):
                if trusted:
                    return data
                return guard()
        """)

    def test_bypass_variants_fail(self):
        for body in [
            "def publish(d):\n    return d\n",                                                              # no guard at all
            "def publish(d, t):\n    if t:\n        guard()\n    return d\n",                                # guard in one branch only
            "def publish(d):\n    if d:\n        return d\n    guard()\n    return d\n",                  # early return before the guard
            "def publish(d):\n    try:\n        guard()\n    except Exception:\n        pass\n    return d\n",      # swallowed failure
            "def publish(d, t):\n    t and guard()\n    return d\n",                                      # short-circuit
            "def publish(d, t):\n    x = guard() if t else None\n    return d\n",                         # conditional expression
            "def publish(d):\n    f = lambda: guard()\n    return d\n",                                  # never called
            "def publish(d):\n    for _ in d:\n        guard()\n    return d\n",                         # loop may run zero times
            "def publish(d):\n    while d:\n        guard()\n        break\n    return d\n",
            "def publish(d):\n    for x in d:\n        if x:\n            break\n    else:\n        guard()\n    return d\n",   # break skips the else
            "def publish(d):\n    [guard() for _ in d]\n    return d\n",                                  # comprehension may be empty
        ]:
            self.bad(body)

    def test_falls_off_the_end(self):
        self.bad("def publish(d, t):\n    if t:\n        guard()\n")

    def test_helper_must_be_guarded_on_all_paths_too(self):
        self.bad("def _h(d, t):\n    if t:\n        return d\n    return guard()\n\ndef publish(d, t):\n    return _h(d, t)\n")

    def test_effect_before_guard_fails(self):
        self.bad("def publish(d):\n    send(d)\n    guard()\n", effects=("send",))
        self.bad("def publish(d, t):\n    if t:\n        send(d)\n    guard()\n", effects=("send",))

    def test_good_shapes_pass(self):
        for body in [
            "def publish(d):\n    guard()\n    return d\n",
            "def publish(d, t):\n    if t:\n        return guard()\n    return guard()\n",                    # guard in both branches
            "def publish(d, t):\n    if t:\n        guard()\n    else:\n        guard()\n    return d\n",
            "def publish(d, t):\n    if not t:\n        raise PermissionError('no')\n    guard()\n    return d\n",   # rejecting branch
            "def publish(d):\n    try:\n        guard()\n    except ValueError:\n        raise\n    return d\n",
            "def publish(d):\n    with open('x') as f:\n        guard()\n    return d\n",
            "def publish(d):\n    try:\n        pass\n    finally:\n        guard()\n    return d\n",
            "def _h(d):\n    return guard()\n\ndef publish(d):\n    return _h(d)\n",
            "def publish(d):\n    return send(guard() or d)\n",
            "def publish(d):\n    guard()\n    send(d)\n",
        ]:
            self.good(body, effects=("send",))

    def test_guard_after_effect_in_same_helper_chain_is_reported_with_line(self):
        r = self.verdict("def publish(d, t):\n    if t:\n        return d\n    return guard()\n")
        self.assertTrue(any("return without a guard" in x for x in r.reasons["pkg.m.publish"]), r.render())

    def test_effect_calls_argument_is_required(self):
        with self.assertRaises(TypeError):
            check_entry_points(tree(GOOD), expected_count=2, verbs=("register",), guarded=("guarded_dispatch",), guard_params=(), exempt={})


class Rejected(Exception):
    pass


class Behavioural(unittest.TestCase):
    """Behavioural half of G27, including the case static analysis cannot see."""

    def setUp(self):
        self.effects = []

        def guard(session, budget):
            if session is None or budget <= 0:
                raise Rejected()

        def safe_publish(*, session, budget):
            guard(session, budget)
            self.effects.append(1)

        def leaky_publish(*, session, budget, trusted=False):      # the reviewer's shape, wired so that data decides
            if not trusted:
                guard(session, budget)
            self.effects.append(1)
        self.safe, self.leaky = safe_publish, leaky_publish
        d = tree(GOOD)
        self.rep = check_entry_points(d, verbs=("publish",), guarded=("guarded_dispatch",), expected_count=1, exempt={}, guard_params=(), effect_calls=())
        self.q = self.rep.entry_points[0].qualname
        self.failing = {"no session": {"session": None}, "no budget": {"budget": 0}, "dropped session": {"session": DROP}}

    def run_cases(self, fn, valid=None, failing=None, **kw):
        valid = valid or dict(session="s", budget=5)
        assert_guard_failures_rejected({self.q: EntryCase(fn, valid, failing if failing is not None else self.failing)}, report=self.rep,
                                       rejects=(Rejected, TypeError), side_effects=lambda: len(self.effects), **kw)

    def test_safe_entry_passes(self):
        self.run_cases(self.safe)

    def test_bypass_by_data_is_caught(self):
        with self.assertRaises(AssertionError) as c:
            self.run_cases(self.leaky, valid=dict(session="s", budget=5, trusted=True), failing={"no session": {"session": None}})
        self.assertIn("ACCEPTED", str(c.exception))

    def test_effect_before_rejection_is_caught(self):
        def effect_first(*, session, budget):
            self.effects.append(1)
            if session is None:
                raise Rejected()
        with self.assertRaises(AssertionError) as c:
            self.run_cases(effect_first, failing={"no session": {"session": None}})
        self.assertIn("side effect", str(c.exception))

    def test_uncovered_entry_point_fails(self):
        with self.assertRaises(AssertionError) as c:
            assert_guard_failures_rejected({}, report=self.rep, rejects=(Rejected,), side_effects=lambda: 0)
        self.assertIn("missing", str(c.exception))

    def test_case_without_failing_input_or_with_noop_override_fails(self):
        with self.assertRaises(AssertionError):
            self.run_cases(self.safe, failing={})
        with self.assertRaises(AssertionError):
            self.run_cases(self.safe, failing={"noop": {"session": "s"}})

    def test_invalid_valid_input_fails(self):
        with self.assertRaises(Rejected):
            self.run_cases(self.safe, valid=dict(session=None, budget=5))


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
