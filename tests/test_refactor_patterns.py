"""Tests for the refactor-pattern rule engine."""

import textwrap
import unittest

from reviewer.models import FileDiff
from reviewer.rules.refactor_patterns import RefactorPatternsRule


class TestRefactorPatternsRule(unittest.TestCase):

    def setUp(self):
        self.rule = RefactorPatternsRule()

    def _ids(self, path, source, start=1):
        lines = textwrap.dedent(source).strip("\n").split("\n")
        diff = FileDiff(file_path=path, added_lines=list(enumerate(lines, start=start)))
        return [v.rule_id for v in self.rule.check(diff)]

    def assertFlags(self, rule_id, path, source):
        self.assertIn(rule_id, self._ids(path, source))

    def assertClean(self, rule_id, path, source):
        self.assertNotIn(rule_id, self._ids(path, source))

    # -- redundant boolean return ---------------------------------------------

    def test_boolean_return_python(self):
        self.assertFlags("quality/redundant-boolean-return", "a.py", """
            if user.active:
                return True
            else:
                return False
        """)

    def test_boolean_return_braced(self):
        self.assertFlags("quality/redundant-boolean-return", "a.ts", """
            if (isValid) {
                return true;
            } else {
                return false;
            }
        """)

    def test_boolean_ternary(self):
        self.assertFlags("quality/redundant-boolean-return", "a.py", "flag = True if x > 0 else False")
        self.assertFlags("quality/redundant-boolean-return", "a.js", "const flag = x > 0 ? true : false;")

    def test_same_boolean_both_branches_allowed(self):
        self.assertClean("quality/redundant-boolean-return", "a.py", """
            if user.active:
                return True
            return True
        """)

    def test_return_true_inside_loop_allowed(self):
        self.assertClean("quality/redundant-boolean-return", "a.py", """
            for pattern in patterns:
                if re.search(pattern, path):
                    return True
            return False
        """)

    # -- nested ternary -------------------------------------------------------

    def test_nested_ternary_python(self):
        self.assertFlags("quality/nested-ternary", "a.py",
                         'label = "a" if is_admin else ("m" if is_mod else "g")')

    def test_nested_ternary_js(self):
        self.assertFlags("quality/nested-ternary", "a.ts",
                         'const label = isAdmin ? "a" : isMod ? "m" : "g";')

    def test_single_ternary_and_optional_chaining_allowed(self):
        self.assertClean("quality/nested-ternary", "a.ts",
                         "const city = user?.profile ? user.profile.city ?? fallback : none;")
        self.assertClean("quality/nested-ternary", "a.py",
                         "names = [n if n else '-' for n in names if n is not None]")

    # -- deep nesting ---------------------------------------------------------

    def test_deep_nesting_flagged(self):
        self.assertFlags("quality/deep-nesting", "a.py", """
            def process(user):
                if user:
                    if user.is_active:
                        for perm in user.perms:
                            if perm == "write":
                                do_work(user)
        """)

    def test_shallow_nesting_allowed(self):
        self.assertClean("quality/deep-nesting", "a.py", """
            def process(user):
                if not user:
                    return
                for perm in user.perms:
                    if perm == "write":
                        do_work(user)
        """)

    # -- signatures -----------------------------------------------------------

    def test_long_parameter_list_python(self):
        self.assertFlags("quality/long-parameter-list", "a.py",
                         "def create_user(self, name, email, role, is_active, created_by):")

    def test_long_parameter_list_multiline_js(self):
        self.assertFlags("quality/long-parameter-list", "a.ts", """
            export function createUser(
                name: string,
                email: string,
                role: Role,
                isActive: boolean,
                createdBy: string,
            ): User {
        """)

    def test_keyword_only_params_not_counted(self):
        self.assertClean("quality/long-parameter-list", "a.py",
                         "def create_user(name, email, *, role, is_active, created_by):")

    def test_mutable_default_argument(self):
        self.assertFlags("quality/mutable-default-argument", "a.py", "def add(item, items=[]):")
        self.assertFlags("quality/mutable-default-argument", "a.py", "def add(item, seen: dict = {}):")
        self.assertClean("quality/mutable-default-argument", "a.py", "def add(item, items=None):")

    # -- exceptions -----------------------------------------------------------

    def test_bare_except_and_swallow(self):
        ids = self._ids("a.py", """
            try:
                risky()
            except:
                pass
        """)
        self.assertIn("quality/bare-except", ids)
        self.assertIn("quality/swallowed-exception", ids)

    def test_handled_exception_allowed(self):
        ids = self._ids("a.py", """
            try:
                risky()
            except ValueError as exc:
                logger.warning("bad value: %s", exc)
        """)
        self.assertNotIn("quality/bare-except", ids)
        self.assertNotIn("quality/swallowed-exception", ids)

    def test_empty_catch_js(self):
        self.assertFlags("quality/swallowed-exception", "a.js", "try { risky(); } catch (e) {}")
        self.assertFlags("quality/swallowed-exception", "a.ts", "fetchData().catch(() => {});")
        self.assertFlags("quality/swallowed-exception", "a.ts", """
            } catch (err) {
            }
        """)

    def test_commented_catch_allowed(self):
        self.assertClean("quality/swallowed-exception", "a.ts", """
            } catch (err) {
                // cache miss is expected on first run
            }
        """)

    # -- comparisons ----------------------------------------------------------

    def test_python_none_comparison(self):
        self.assertFlags("quality/non-idiomatic-comparison", "a.py", "if value == None:")
        self.assertFlags("quality/non-idiomatic-comparison", "a.py", "if len(items) == 0:")
        self.assertClean("quality/non-idiomatic-comparison", "a.py", "if value is None:")
        self.assertClean("quality/non-idiomatic-comparison", "a.py", 'msg = "x == None"')

    def test_js_loose_equality(self):
        self.assertFlags("quality/loose-equality", "a.js", "if (count == 0) {")
        self.assertClean("quality/loose-equality", "a.js", "if (count === 0) {")
        self.assertClean("quality/loose-equality", "a.js", "if (value == null) {")

    # -- loops ----------------------------------------------------------------

    def test_range_len_loop(self):
        self.assertFlags("quality/range-len-loop", "a.py", "for i in range(len(items)):")
        self.assertClean("quality/range-len-loop", "a.py", "for i, item in enumerate(items):")

    def test_manual_accumulation_python(self):
        self.assertFlags("quality/manual-accumulation-loop", "a.py", """
            result = []
            for item in items:
                if item.is_active:
                    result.append(item.name.upper())
            return result
        """)

    def test_manual_accumulation_js(self):
        self.assertFlags("quality/manual-accumulation-loop", "a.ts", """
            const result: string[] = [];
            for (const item of items) {
                result.push(item.name);
            }
        """)

    def test_loop_with_side_effects_allowed(self):
        self.assertClean("quality/manual-accumulation-loop", "a.py", """
            result = []
            for item in items:
                audit(item)
                result.append(item.name)
            return result
        """)

    def test_await_in_loop(self):
        self.assertFlags("quality/await-in-loop", "a.ts", """
            for (const id of ids) {
                const user = await fetchUser(id);
            }
        """)
        self.assertClean("quality/await-in-loop", "a.ts",
                         "const users = await Promise.all(ids.map(fetchUser));")

    # -- string concatenation -------------------------------------------------

    def test_string_concatenation(self):
        self.assertFlags("quality/string-concatenation", "a.py",
                         'msg = "Hello " + user.name + "! You have " + str(n) + " messages."')
        self.assertClean("quality/string-concatenation", "a.py", 'path = base + "/index"')

    # -- unreachable code -----------------------------------------------------

    def test_unreachable_after_return(self):
        self.assertFlags("quality/unreachable-code", "a.py", """
            def get_value():
                return 42
                cleanup()
        """)

    def test_code_after_exit_in_other_branch_allowed(self):
        self.assertClean("quality/unreachable-code", "a.py", """
            if cached:
                return cached
            return compute()
        """)
        self.assertClean("quality/unreachable-code", "a.js", """
            switch (kind) {
                case "a":
                    return 1;
                case "b":
                    return 2;
            }
        """)

    # -- collapsible if -------------------------------------------------------

    def test_collapsible_if_python(self):
        self.assertFlags("quality/collapsible-if", "a.py", """
            if user:
                if user.is_admin:
                    grant(user)
            done()
        """)

    def test_collapsible_if_braced(self):
        self.assertFlags("quality/collapsible-if", "a.ts", """
            if (user) {
                if (user.isAdmin) {
                    grant(user);
                }
            }
        """)

    def test_if_with_else_not_collapsible(self):
        self.assertClean("quality/collapsible-if", "a.py", """
            if user:
                if user.is_admin:
                    grant(user)
            else:
                deny()
        """)

    # -- comments -------------------------------------------------------------

    def test_commented_out_code(self):
        self.assertFlags("quality/commented-out-code", "a.py", """
            # result = compute(x)
            # save(result)
            return None
        """)
        self.assertFlags("quality/commented-out-code", "a.ts", "// const total = sum(items);")

    def test_prose_comment_not_code(self):
        self.assertClean("quality/commented-out-code", "a.py", "# Retry because the API is flaky")

    def test_narrating_comment(self):
        self.assertFlags("quality/narrating-comment", "a.py", """
            # Increment the counter
            counter += 1
        """)
        self.assertFlags("quality/narrating-comment", "a.ts", """
            // Fetch the user profile
            const profile = await fetchUserProfile(id);
        """)

    def test_multiline_comment_continuation_not_narration(self):
        self.assertClean("quality/narrating-comment", "a.py", """
            # Matches the opening of an else block:
            # else, else block.
            else_re = compile_else_block()
        """)

    def test_intent_comment_allowed(self):
        self.assertClean("quality/narrating-comment", "a.py", """
            # Retry once because the token may have just expired
            counter += 1
        """)

    # -- god function ---------------------------------------------------------

    def test_god_function_python(self):
        body = "\n".join(f"    step_{i}()" for i in range(60))
        self.assertFlags("quality/god-function", "a.py", f"def register_user(data):\n{body}")

    def test_god_function_braced(self):
        body = "\n".join(f"    step{i}();" for i in range(60))
        self.assertFlags("quality/god-function", "a.ts", f"function registerUser(data) {{\n{body}\n}}")

    def test_small_function_allowed(self):
        self.assertClean("quality/god-function", "a.py", "def ok():\n    return 1")

    # -- general --------------------------------------------------------------

    def test_bypass_directive(self):
        self.assertClean("quality/mutable-default-argument", "a.py",
                         "def add(item, items=[]):  # reviewer:ignore")

    def test_non_contiguous_hunks_not_joined(self):
        diff = FileDiff(file_path="a.py", added_lines=[
            (10, "def get_value():"),
            (11, "    return 42"),
            (40, "    cleanup()"),
        ])
        ids = [v.rule_id for v in self.rule.check(diff)]
        self.assertNotIn("quality/unreachable-code", ids)

    def test_non_code_files_skipped(self):
        self.assertEqual(self._ids("README.md", "def add(item, items=[]):"), [])


if __name__ == "__main__":
    unittest.main()
