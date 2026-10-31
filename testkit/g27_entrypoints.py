"""G27 helper: enumerate every register/publish/execute/release entry point and prove each goes through the one guarded function.

Static (AST) and dependency-free. Copy this file into the project's tests/ directory (or import it from a pinned forge-standards checkout).

    report = check_entry_points(
        Path("src/myapp"),
        verbs=("register", "publish", "execute", "release"),
        guarded=("guarded_dispatch",),            # the single protected path
        expected_count=7,                         # the counted entry points; a new one fails the test until counted
        exempt={"myapp.cli.release_notes": "renders text, releases nothing"},   # every exemption needs a reason
        guard_params=("customer_data", "model_locks", "session", "budget"),
    )
    assert report.ok, report.render()

Resolution is by bare function name (`foo()` or `x.foo()`), so a same-named unrelated function can mask a bypass: keep guarded names unique in the
tree (`check_entry_points` rejects a guarded name defined more than once). A call counts only when it is reachable, in the same tree, from the entry point.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

BYPASS_PARAM = re.compile(r"^(skip|bypass|no_check|unsafe|force|disable)(_|$)|(^|_)(skip|bypass)$")


@dataclass(frozen=True)
class EntryPoint:
    qualname: str          # module.path.Class.func
    name: str
    path: str
    lineno: int


@dataclass
class Report:
    entry_points: list[EntryPoint] = field(default_factory=list)
    unguarded: list[EntryPoint] = field(default_factory=list)
    optional_guard_params: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.unguarded or self.optional_guard_params or self.problems)

    def render(self) -> str:
        out = [f"{len(self.entry_points)} entry point(s) counted"]
        out += [f"UNGUARDED {e.qualname} ({e.path}:{e.lineno}) does not reach the guarded path" for e in self.unguarded]
        out += [f"OPTIONAL-GUARD {x}" for x in self.optional_guard_params]
        out += [f"PROBLEM {x}" for x in self.problems]
        return "\n".join(out)


@dataclass
class _Fn:
    entry: EntryPoint
    node: ast.AST
    calls: set[str]


def _callee(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _collect(root: Path) -> list[_Fn]:
    root = Path(root)
    fns: list[_Fn] = []
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = f.relative_to(root.parent)
        mod = ".".join(rel.with_suffix("").parts).removesuffix(".__init__")
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))

        def walk(body, prefix):
            for n in body:
                if isinstance(n, ast.ClassDef):
                    walk(n.body, f"{prefix}.{n.name}")
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    calls = {c for x in ast.walk(n) if isinstance(x, ast.Call) and (c := _callee(x))}
                    fns.append(_Fn(EntryPoint(f"{prefix}.{n.name}", n.name, rel.as_posix(), n.lineno), n, calls))
        walk(tree.body, mod)
    return fns


def _is_entry(name: str, verbs: Iterable[str], include_private: bool) -> bool:
    if name.startswith("_") and not include_private:
        return False
    return bool(set(name.strip("_").lower().split("_")) & set(verbs))


def _reaches(fns: list[_Fn], start: _Fn, guarded: set[str]) -> bool:
    by_name: dict[str, list[_Fn]] = {}
    for fn in fns:
        by_name.setdefault(fn.entry.name, []).append(fn)
    seen: set[str] = set()
    todo = [start]
    while todo:
        cur = todo.pop()
        if cur.entry.qualname in seen:
            continue
        seen.add(cur.entry.qualname)
        if cur.calls & guarded:
            return True
        for c in cur.calls:
            todo += by_name.get(c, [])
    return False


def find_entry_points(root: Path, verbs: Iterable[str], include_private: bool = False) -> list[EntryPoint]:
    return [f.entry for f in _collect(root) if _is_entry(f.entry.name, verbs, include_private)]


def check_entry_points(root: Path, *, verbs: Iterable[str], guarded: Iterable[str], expected_count: int, exempt: Mapping[str, str],
                       guard_params: Iterable[str], include_private: bool = False) -> Report:
    """Every argument is required on purpose (G27: no optional parameter whose absence skips a check)."""
    guarded_set, verbs = set(guarded), tuple(verbs)
    rep = Report()
    if not guarded_set:
        rep.problems.append("no guarded function named: nothing to prove")
        return rep
    fns = _collect(root)
    for g in sorted(guarded_set):
        n = sum(1 for f in fns if f.entry.name == g)
        if n != 1:
            rep.problems.append(f"guarded function '{g}' is defined {n} times in the tree (must be exactly once)")
    for q, why in exempt.items():
        if not str(why).strip():
            rep.problems.append(f"exemption {q} has no reason")
    names = {f.entry.qualname for f in fns}
    rep.problems += [f"exemption {q} matches no function (stale)" for q in exempt if q not in names]
    gparams = set(guard_params)
    for fn in fns:
        if fn.entry.name in guarded_set:
            continue                                   # the guard itself is proven by assert_fail_closed
        if not _is_entry(fn.entry.name, verbs, include_private):
            continue
        rep.entry_points.append(fn.entry)
        if fn.entry.qualname in exempt:
            continue
        if not _reaches(fns, fn, guarded_set):
            rep.unguarded.append(fn.entry)
    # optional parameters that can switch a check off: on every counted entry point and on the guarded functions
    for fn in fns:
        if fn.entry.name in guarded_set or fn.entry in rep.entry_points:
            a = fn.node.args
            pos = a.posonlyargs + a.args
            defaulted = {p.arg for p in pos[len(pos) - len(a.defaults):]} | {p.arg for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None}
            for p in sorted(defaulted):
                if p in gparams or BYPASS_PARAM.search(p):
                    rep.optional_guard_params.append(f"{fn.entry.qualname}({p}=...) has a default; a missing check input must reject, not skip")
    if len(rep.entry_points) != expected_count:
        rep.problems.append(f"counted {len(rep.entry_points)} entry point(s), expected {expected_count}: "
                            f"{sorted(e.qualname for e in rep.entry_points)} (update expected_count only after reviewing the new entry point)")
    return rep


def assert_fail_closed(fn: Callable, valid_kwargs: Mapping, required_state: Iterable[str], *, rejects: tuple[type[BaseException], ...],
                       side_effects: Callable[[], int]) -> None:
    """Runtime half of G27: calling the guarded function with any required state missing (key absent, None) must raise one of `rejects`
    and must leave `side_effects()` unchanged. Also proves the call with all state present is accepted (else the test proves nothing)."""
    fn(**valid_kwargs)
    for key in required_state:
        for variant in ("absent", "none"):
            kw = {k: v for k, v in valid_kwargs.items() if k != key}
            if variant == "none":
                kw[key] = None
            before = side_effects()
            try:
                fn(**kw)
            except rejects:
                pass
            except TypeError as e:
                if variant == "none":
                    raise AssertionError(f"{key}=None raised TypeError instead of a clean rejection: {e}") from e
            else:
                raise AssertionError(f"missing state '{key}' ({variant}) was accepted: the check is skipped, not fail-closed")
            if side_effects() != before:
                raise AssertionError(f"missing state '{key}' ({variant}) was rejected only after a side effect happened")
