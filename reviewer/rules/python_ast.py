"""AST-backed implementations of the Python checks in ``refactor_patterns``.

The line-based heuristics cannot tell code from text inside docstrings or
triple-quoted fixtures. When the full post-change source of a ``.py`` file is
available and parses, these exact checks replace the regex versions for the
rule IDs listed in ``AST_RULE_IDS``. Findings are only reported when their
anchor line is one of the added lines, preserving diff-only semantics.
"""

import ast
import re
import warnings
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from reviewer.config import get_config
from reviewer.models import FileDiff
from reviewer.rules.code_quality import _is_bypass
from reviewer.rules.refactor_patterns import (
    BARE_EXCEPT,
    BOOLEAN_RETURN,
    COLLAPSIBLE_IF,
    DEEP_NESTING,
    GOD_FUNCTION,
    LONG_PARAMS,
    MUTABLE_DEFAULT,
    NON_IDIOMATIC_COMPARISON,
    RANGE_LEN_LOOP,
    SWALLOWED_EXCEPTION,
    UNREACHABLE_CODE,
    _Hit,
    _Smell,
)

AST_RULE_IDS = frozenset(
    smell.rule_id
    for smell in (
        LONG_PARAMS, MUTABLE_DEFAULT, GOD_FUNCTION, DEEP_NESTING, UNREACHABLE_CODE,
        BARE_EXCEPT, SWALLOWED_EXCEPTION, BOOLEAN_RETURN, COLLAPSIBLE_IF,
        RANGE_LEN_LOOP, NON_IDIOMATIC_COMPARISON,
    )
)

_FuncDef = (ast.FunctionDef, ast.AsyncFunctionDef)
_TRY_TYPES = tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t is not None)
_NESTING_TYPES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith) + _TRY_TYPES
_EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_MUTABLE_LITERALS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
_MUTABLE_FACTORIES = {"list", "dict", "set", "defaultdict"}
_NEWLINE_RE = re.compile(r"\r\n|\r|\n")


def parse_source(source: Optional[str]) -> Optional[ast.AST]:
    """Parse ``source``; return None when it is missing or not valid Python."""
    if source is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def find_hits(file_diff: FileDiff) -> Optional[List[_Hit]]:
    """Return AST-derived hits, or None if the AST path is unavailable."""
    tree = parse_source(file_diff.full_content)
    if tree is None or file_diff.full_content is None:
        return None
    return _Collector(
        _NEWLINE_RE.split(file_diff.full_content), dict(file_diff.added_lines)
    ).collect(tree)


def _start_line(node: ast.stmt) -> int:
    decorators = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decorators])


def _bool_const(node: Optional[ast.AST]) -> Optional[bool]:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _returned_bool(stmt: ast.stmt) -> Optional[bool]:
    if isinstance(stmt, ast.Return):
        return _bool_const(stmt.value)
    return None


def _is_pass_like(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _is_call_to(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


def _is_mutable_default(node: ast.AST) -> bool:
    if isinstance(node, _MUTABLE_LITERALS):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in _MUTABLE_FACTORIES
        if isinstance(func, ast.Attribute):
            return func.attr == "defaultdict"
    return False


def _non_idiomatic(node: ast.Compare) -> bool:
    operands = [node.left] + list(node.comparators)
    for op, left, right in zip(node.ops, operands, operands[1:]):
        if isinstance(op, (ast.Eq, ast.NotEq)):
            for side in (left, right):
                if isinstance(side, ast.Constant) and (side.value is None or isinstance(side.value, bool)):
                    return True
        if (
            isinstance(op, (ast.Eq, ast.NotEq, ast.Gt))
            and _is_call_to(left, "len")
            and isinstance(right, ast.Constant)
            and right.value == 0
            and not isinstance(right.value, bool)
        ):
            return True
    return False


class _Collector:
    def __init__(self, lines: List[str], added: Dict[int, str]) -> None:
        self.lines = lines
        self.added = added
        self.hits: List[_Hit] = []
        self._seen: Set[Tuple[str, int]] = set()

    def collect(self, tree: ast.AST) -> List[_Hit]:
        methods = {
            id(child)
            for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            for child in node.body if isinstance(child, _FuncDef)
        }
        for node in ast.walk(tree):
            self._check_node(node, id(node) in methods)
            for name in ("body", "orelse", "finalbody"):
                stmts = getattr(node, name, None)
                if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                    self._check_stmt_list(stmts)
        self._check_nesting(getattr(tree, "body", []), 0, None)
        self.hits.sort(key=lambda hit: hit[1])
        return self.hits

    # --- reporting ----------------------------------------------------------

    def _report(self, smell: _Smell, line_no: int) -> None:
        text = self.added.get(line_no)
        if text is None or _is_bypass(text) or (smell.rule_id, line_no) in self._seen:
            return
        self._seen.add((smell.rule_id, line_no))
        self.hits.append((smell, line_no, text))

    # --- per-node checks ----------------------------------------------------

    def _check_node(self, node: ast.AST, is_method: bool) -> None:
        if isinstance(node, _FuncDef):
            self._check_function(node, is_method)
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                self._report(BARE_EXCEPT, node.lineno)
            if node.body and all(_is_pass_like(s) for s in node.body):
                self._report(SWALLOWED_EXCEPTION, node.lineno)
        elif isinstance(node, ast.IfExp):
            value, other = _bool_const(node.body), _bool_const(node.orelse)
            if value is not None and other is not None and value != other:
                self._report(BOOLEAN_RETURN, node.lineno)
        elif isinstance(node, ast.If):
            if (
                not node.orelse and len(node.body) == 1
                and isinstance(node.body[0], ast.If) and not node.body[0].orelse
            ):
                self._report(COLLAPSIBLE_IF, node.lineno)
        elif isinstance(node, ast.For):
            it = node.iter
            if _is_call_to(it, "range") and it.args and _is_call_to(it.args[0], "len"):
                self._report(RANGE_LEN_LOOP, node.lineno)
        elif isinstance(node, ast.Compare) and _non_idiomatic(node):
            self._report(NON_IDIOMATIC_COMPARISON, node.lineno)

    def _check_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], is_method: bool) -> None:
        line_no = node.lineno
        if line_no not in self.added:
            return
        args = node.args
        positional = list(args.posonlyargs) + list(args.args)
        if is_method and positional and positional[0].arg in ("self", "cls"):
            positional = positional[1:]
        max_params = get_config().max_params
        if len(positional) > max_params:
            message = f"Function takes {len(positional)} positional parameters (max {max_params})."
            self._report(replace(LONG_PARAMS, message=message), line_no)

        defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
        if any(_is_mutable_default(d) for d in defaults):
            self._report(MUTABLE_DEFAULT, line_no)

        body = self._body_length(node)
        max_lines = get_config().max_function_lines
        if body > max_lines:
            self._report(replace(GOD_FUNCTION, message=f"Function body is {body} lines (max {max_lines})."), line_no)

    def _body_length(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> int:
        stmts = list(node.body)
        first = stmts[0]
        if (
            isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            stmts = stmts[1:]
        if not stmts:
            return 0
        start = _start_line(stmts[0])
        end = node.end_lineno or start
        return sum(1 for text in self.lines[start - 1:end] if text.strip())

    # --- statement lists ----------------------------------------------------

    def _check_stmt_list(self, stmts: Sequence[ast.stmt]) -> None:
        for idx, stmt in enumerate(stmts[:-1]):
            if isinstance(stmt, _EXITS):
                self._report(UNREACHABLE_CODE, _start_line(stmts[idx + 1]))
                break
        for idx, stmt in enumerate(stmts):
            if isinstance(stmt, ast.If) and self._is_boolean_branch(stmt, stmts[idx + 1:idx + 2]):
                self._report(BOOLEAN_RETURN, stmt.lineno)

    @staticmethod
    def _is_boolean_branch(stmt: ast.If, following: Sequence[ast.stmt]) -> bool:
        if len(stmt.body) != 1:
            return False
        first = _returned_bool(stmt.body[0])
        if first is None:
            return False
        if stmt.orelse:
            second = _returned_bool(stmt.orelse[0]) if len(stmt.orelse) == 1 else None
        else:
            second = _returned_bool(following[0]) if following else None
        return second is not None and second != first

    # --- nesting ------------------------------------------------------------

    def _check_nesting(self, stmts: Sequence[ast.stmt], level: int, state: Optional[Dict[str, bool]]) -> None:
        for stmt in stmts:
            if isinstance(stmt, _FuncDef + (ast.ClassDef,)):
                self._check_nesting(stmt.body, 0, None)
            elif isinstance(stmt, _NESTING_TYPES):
                self._check_nesting_stmt(stmt, level, state if state is not None else {"flagged": False})

    def _check_nesting_stmt(self, stmt: ast.stmt, level: int, state: Dict[str, bool]) -> None:
        current = level + 1
        max_nesting = get_config().max_nesting
        if current >= max_nesting and not state["flagged"]:
            state["flagged"] = True
            smell = replace(DEEP_NESTING, message=f"Control flow is nested {max_nesting}+ levels deep.")
            self._report(smell, stmt.lineno)
        if isinstance(stmt, _TRY_TYPES):
            self._check_nesting(stmt.body, current, state)
            for handler in stmt.handlers:
                self._check_nesting(handler.body, current, state)
            self._check_nesting(stmt.orelse, current, state)
            self._check_nesting(stmt.finalbody, current, state)
            return
        self._check_nesting(stmt.body, current, state)
        orelse = stmt.orelse if hasattr(stmt, "orelse") else []
        if self._is_elif(stmt, orelse):
            self._check_nesting(orelse, level, state)
        else:
            self._check_nesting(orelse, current, state)

    def _is_elif(self, stmt: ast.stmt, orelse: Sequence[ast.stmt]) -> bool:
        if not isinstance(stmt, ast.If) or len(orelse) != 1 or not isinstance(orelse[0], ast.If):
            return False
        return self.lines[orelse[0].lineno - 1].lstrip().startswith("elif")
