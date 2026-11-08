"""Tests for the AST-backed Python checks in the refactor-pattern rule."""

import textwrap
import unittest
from typing import List, Optional, Set

from reviewer.config import ReviewerConfig, set_config
from reviewer.models import FileDiff
from reviewer.rules.refactor_patterns import RefactorPatternsRule

LONG = "quality/long-parameter-list"
MUTABLE = "quality/mutable-default-argument"
GOD = "quality/god-function"
NEST = "quality/deep-nesting"
DEAD = "quality/unreachable-code"
BARE = "quality/bare-except"
SWALLOW = "quality/swallowed-exception"
BOOL = "quality/redundant-boolean-return"
COLLAPSE = "quality/collapsible-if"
RANGE = "quality/range-len-loop"
COMPARE = "quality/non-idiomatic-comparison"


class TestPythonAst(unittest.TestCase):

    def setUp(self):
        set_config(None)
        self.rule = RefactorPatternsRule()

    def tearDown(self):
        set_config(None)

    def _check(self, source: str, added: Optional[Set[int]] = None, path: str = "a.py"):
        source = textwrap.dedent(source).strip("\n") + "\n"
        lines = source.split("\n")[:-1]
        numbered = list(enumerate(lines, start=1))
        if added is not None:
            numbered = [(n, t) for n, t in numbered if n in added]
        return self.rule.check(FileDiff(file_path=path, added_lines=numbered, full_content=source))

    def _ids(self, source: str, added: Optional[Set[int]] = None) -> List[str]:
        return [v.rule_id for v in self._check(source, added)]

    def _lines(self, rule_id: str, source: str) -> List[int]:
        return [v.line_number for v in self._check(source) if v.rule_id == rule_id]

    # -- long parameter list ---------------------------------------------------

    def test_multiline_signature(self):
        src = """
            def f(
                a,
                b,
                c,
                d,
                e,
            ):
                return a
        """
        self.assertEqual(self._lines(LONG, src), [1])

    def test_decorated_function_anchors_on_def_line(self):
        src = """
            @decorator(1, 2, 3, 4, 5, 6)
            def f(a, b, c, d, e):
                return a
        """
        self.assertEqual(self._lines(LONG, src), [2])

    def test_method_self_and_cls_not_counted(self):
        src = """
            class A:
                def m(self, a, b, c, d):
                    return a

                @classmethod
                def c(cls, a, b, c, d):
                    return a

                def too_many(self, a, b, c, d, e):
                    return a
        """
        self.assertEqual(self._lines(LONG, src), [9])

    def test_nested_and_async_functions(self):
        src = """
            def outer():
                def inner(a, b, c, d, e):
                    return a
                return inner

            async def run(a, b, c, d, e):
                return a
        """
        self.assertEqual(self._lines(LONG, src), [2, 6])

    def test_kwonly_varargs_not_counted(self):
        src = """
            def f(a, b, c, d, *args, e=1, f=2, **kw):
                return a

            def g(a, b, c, d, *, e, f, g):
                return a
        """
        self.assertNotIn(LONG, self._ids(src))

    def test_posonly_counted(self):
        src = """
            def f(a, b, /, c, d, e):
                return a
        """
        self.assertIn(LONG, self._ids(src))

    def test_message_uses_threshold(self):
        set_config(ReviewerConfig(max_params=2))
        violations = self._check("def f(a, b, c):\n    return a\n")
        messages = [v.message for v in violations if v.rule_id == LONG]
        self.assertEqual(messages, ["Function takes 3 positional parameters (max 2)."])

    def test_code_in_string_not_flagged(self):
        src = '''
            FIXTURE = """
            def f(a, b, c, d, e, f):
                x = None
                try:
                    pass
                except:
                    pass
            """
        '''
        self.assertEqual(self._ids(src), [])

    def test_docstring_code_not_flagged(self):
        src = '''
            def f():
                """Example:

                def g(a, b, c, d, e, f=[]):
                    if x == None:
                        return True
                """
                return 1
        '''
        self.assertEqual(self._ids(src), [])

    # -- mutable defaults ------------------------------------------------------

    def test_mutable_defaults(self):
        src = """
            def a(x=[]): pass
            def b(x={}): pass
            def c(x={1}): pass
            def d(x=[i for i in y]): pass
            def e(x={i: 1 for i in y}): pass
            def f(x={i for i in y}): pass
            def g(x=list()): pass
            def h(x=dict()): pass
            def i(x=set()): pass
            def j(x=defaultdict(list)): pass
            def k(*, x=[]): pass
            def ok(x=None, y=(), z=1): pass
        """
        self.assertEqual(self._lines(MUTABLE, src), list(range(1, 12)))

    # -- god function ----------------------------------------------------------

    def test_god_function_excludes_docstring(self):
        set_config(ReviewerConfig(max_function_lines=3))
        body = "\n".join(f"    x{i} = {i}" for i in range(3))
        src = f'def f():\n    """Doc\n\n    more doc\n    """\n{body}\n'
        self.assertNotIn(GOD, self._ids(src))
        src = f'def f():\n    """Doc"""\n{body}\n    y = 1\n'
        violations = [v for v in self._check(src) if v.rule_id == GOD]
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].message, "Function body is 4 lines (max 3).")
        self.assertEqual(violations[0].line_number, 1)

    def test_god_function_ignores_blank_lines(self):
        set_config(ReviewerConfig(max_function_lines=2))
        src = "def f():\n    a = 1\n\n\n    b = 2\n"
        self.assertNotIn(GOD, self._ids(src))

    # -- deep nesting ----------------------------------------------------------

    def test_deep_nesting_flagged_once(self):
        src = """
            def f(x):
                if x:
                    for i in x:
                        while i:
                            with i:
                                try:
                                    pass
                                finally:
                                    pass
        """
        self.assertEqual(self._lines(NEST, src), [5])

    def test_elif_chain_is_not_nesting(self):
        set_config(ReviewerConfig(max_nesting=2))
        src = """
            def f(x):
                if x == 1:
                    return 1
                elif x == 2:
                    return 2
                elif x == 3:
                    return 3
        """
        self.assertNotIn(NEST, self._ids(src))

    def test_explicit_else_if_is_nesting(self):
        src = """
            if a:
                pass
            else:
                if b:
                    for i in c:
                        if i:
                            pass
        """
        self.assertEqual(self._lines(NEST, src), [6])

    def test_nesting_threshold_respected(self):
        src = """
            def f(x):
                if x:
                    for i in x:
                        use(i)
        """
        self.assertNotIn(NEST, self._ids(src))
        set_config(ReviewerConfig(max_nesting=2))
        self.assertEqual(self._lines(NEST, src), [3])
        violations = [v for v in self._check(src) if v.rule_id == NEST]
        self.assertEqual(violations[0].message, "Control flow is nested 2+ levels deep.")

    def test_nested_function_resets_depth(self):
        src = """
            def f(x):
                if x:
                    for i in x:
                        def g(y):
                            if y:
                                return 1
        """
        self.assertNotIn(NEST, self._ids(src))

    # -- unreachable code ------------------------------------------------------

    def test_unreachable_after_exit(self):
        src = """
            def f(xs):
                for x in xs:
                    if x:
                        continue
                        use(x)
                    break
                    use(1)
                return 1
                use(2)
        """
        self.assertEqual(self._lines(DEAD, src), [5, 7, 9])

    def test_reachable_code_not_flagged(self):
        src = """
            def f(x):
                if x:
                    return 1
                try:
                    raise ValueError
                except ValueError:
                    return 2
                return 3
        """
        self.assertNotIn(DEAD, self._ids(src))

    # -- exceptions ------------------------------------------------------------

    def test_bare_and_swallowed(self):
        src = """
            try:
                pass
            except:
                pass
            try:
                pass
            except ValueError:
                ...
            try:
                pass
            except KeyError:
                x = 1
        """
        self.assertEqual(self._lines(BARE, src), [3])
        self.assertEqual(self._lines(SWALLOW, src), [3, 7])

    # -- boolean return --------------------------------------------------------

    def test_boolean_return_forms(self):
        src = """
            def a(c):
                if c:
                    return True
                __ELSE__
                    return False

            def b(c):
                if c:
                    return False
                return True

            def d(c):
                return True if c else False

            def ok(c):
                if c:
                    return True
                return True
        """
        self.assertEqual(self._lines(BOOL, src), [2, 8, 13])

    # -- collapsible if --------------------------------------------------------

    def test_collapsible_if(self):
        src = """
            if a:
                if b:
                    pass

            if a:
                if b:
                    pass
            else:
                pass

            if a:
                if b:
                    pass
                else:
                    pass

            if a:
                x = 1
                if b:
                    pass
        """
        self.assertEqual(self._lines(COLLAPSE, src), [1])

    # -- loops and comparisons -------------------------------------------------

    def test_range_len(self):
        src = """
            for i in range(len(xs)):
                pass
            for i in range(3):
                pass
            for i in range(1, len(xs)):
                pass
        """
        self.assertEqual(self._lines(RANGE, src), [1])

    def test_non_idiomatic_comparison(self):
        src = """
            a = x == None
            b = x != True
            c = False == x
            d = len(x) == 0
            e = len(x) > 0
            f = len(x) != 0
            g = x is None
            h = x == 0
            i = len(x) > 1
            j = len(x) < 0
        """
        self.assertEqual(self._lines(COMPARE, src), [1, 2, 3, 4, 5, 6])

    # -- diff-only semantics ---------------------------------------------------

    def test_findings_outside_added_lines_not_reported(self):
        src = """
            def f(a, b, c, d, e):
                try:
                    pass
                except:
                    pass
                return x == None
        """
        self.assertEqual(self._ids(src, added={2, 3}), [])
        self.assertIn(LONG, self._ids(src, added={1}))
        self.assertEqual(
            sorted(self._ids(src, added={4, 6})),
            sorted([BARE, SWALLOW, COMPARE]),
        )

    def test_bypass_on_anchor_line(self):
        src = "def f(a, b, c, d, e):  # noqa\n    return a\n"
        self.assertNotIn(LONG, self._ids(src))

    # -- fallback and coexistence ----------------------------------------------

    def test_syntax_error_falls_back_to_heuristics(self):
        src = "def f(a, b, c, d, e):\n    return a\nelse:\n    x = ==\n"
        self.assertIn(LONG, self._ids(src))

    def test_null_bytes_fall_back(self):
        src = "def f(a, b, c, d, e):\n    return a\n\x00\n"
        lines = src.split("\n")[:-1]
        diff = FileDiff(file_path="a.py", added_lines=list(enumerate(lines, 1)), full_content=src)
        self.assertIn(LONG, [v.rule_id for v in self.rule.check(diff)])

    def test_no_full_content_uses_heuristics(self):
        diff = FileDiff(file_path="a.py", added_lines=[(1, "def f(a, b, c, d, e):"), (2, "    return a")])
        self.assertIn(LONG, [v.rule_id for v in self.rule.check(diff)])

    def test_no_duplicate_findings(self):
        src = """
            def f(a, b, c, d, e, x=[]):
                if x == None:
                    return True
                __ELSE__
                    return False
        """.replace("__ELSE__", "else:")
        ids = self._ids(src)
        for rule_id in (LONG, MUTABLE, COMPARE, BOOL):
            self.assertEqual(ids.count(rule_id), 1, rule_id)

    def test_non_ast_checks_still_run(self):
        src = """
            def f(x):
                msg = "a" + x + "b" + x
                return msg
        """
        self.assertIn("quality/string-concatenation", self._ids(src))

    def test_other_extensions_unaffected(self):
        source = "function f(a, b, c, d, e) {\n  return a;\n}\n"
        lines = source.split("\n")[:-1]
        diff = FileDiff(file_path="a.js", added_lines=list(enumerate(lines, 1)), full_content=source)
        self.assertIn(LONG, [v.rule_id for v in self.rule.check(diff)])


if __name__ == "__main__":
    unittest.main()
