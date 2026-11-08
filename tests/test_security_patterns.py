"""Tests for the security and suppression-hygiene rule pack.

Fixtures are single-line string literals on purpose: the reviewer masks string
contents, so risky snippets in this file do not flag the file itself.
"""

import unittest

from reviewer.models import FileDiff, Severity
from reviewer.rules.security_patterns import SecurityPatternsRule


class SecurityRuleTestCase(unittest.TestCase):

    def setUp(self):
        self.rule = SecurityPatternsRule()

    def violations(self, path, *lines):
        diff = FileDiff(file_path=path, added_lines=list(enumerate(lines, start=1)))
        return self.rule.check(diff)

    def ids(self, path, *lines):
        return [v.rule_id for v in self.violations(path, *lines)]

    def assertFlags(self, rule_id, path, *lines):
        self.assertIn(rule_id, self.ids(path, *lines))

    def assertClean(self, rule_id, path, *lines):
        self.assertNotIn(rule_id, self.ids(path, *lines))


class TestSqlStringFormat(SecurityRuleTestCase):
    RULE = "security/sql-string-format"

    def test_fstring(self):
        self.assertFlags(self.RULE, "a.py", 'cur.execute(f"SELECT * FROM users WHERE id = {uid}")')

    def test_percent_format(self):
        self.assertFlags(self.RULE, "a.py", 'cur.execute("DELETE FROM t WHERE id = %s" % uid)')

    def test_dot_format(self):
        self.assertFlags(self.RULE, "a.py", 'cur.executemany("INSERT INTO t VALUES ({})".format(v), rows)')

    def test_concat(self):
        self.assertFlags(self.RULE, "a.py", 'cur.execute("SELECT * FROM t WHERE n = \'" + name + "\'")')

    def test_concat_variable_first(self):
        self.assertFlags(self.RULE, "a.py", 'cur.execute(prefix + "UPDATE t SET a = 1")')

    def test_js_template_literal(self):
        self.assertFlags(self.RULE, "a.ts", "db.query(`SELECT * FROM t WHERE id = ${id}`)")

    def test_severity_is_error(self):
        found = self.violations("a.py", 'cur.execute(f"SELECT * FROM t WHERE id = {x}")')
        self.assertEqual(found[0].severity, Severity.ERROR)

    def test_parameterised_query_clean(self):
        self.assertClean(self.RULE, "a.py", 'cur.execute("SELECT * FROM t WHERE id = %s", (uid,))')

    def test_parameterised_with_arithmetic_in_params_clean(self):
        self.assertClean(self.RULE, "a.py", 'cur.execute("SELECT * FROM t WHERE id = %s", (a + b,))')

    def test_non_sql_fstring_clean(self):
        self.assertClean(self.RULE, "a.py", 'cur.execute(f"{name}")')
        self.assertClean(self.RULE, "a.py", 'logger.query(f"updating {name}")')

    def test_constant_sql_clean(self):
        self.assertClean(self.RULE, "a.py", 'cur.execute("SELECT * FROM t")')

    def test_definition_clean(self):
        self.assertClean(self.RULE, "a.py", "def execute(self, query):")

    def test_call_inside_string_or_comment_clean(self):
        self.assertClean(self.RULE, "a.py", 'text = "cur.execute(f\'SELECT * FROM t {x}\')"')
        self.assertClean(self.RULE, "a.py", "# cur.execute(sql + 'SELECT * FROM t')")

    def test_bypass(self):
        self.assertClean(self.RULE, "a.py", 'cur.execute(f"SELECT * FROM {TABLE}")  # reviewer:ignore')


class TestUnsafeDeserialization(SecurityRuleTestCase):
    RULE = "security/unsafe-deserialization"

    def test_pickle(self):
        self.assertFlags(self.RULE, "a.py", "obj = pickle.loads(blob)")
        self.assertFlags(self.RULE, "a.py", "obj = pickle.load(fh)")

    def test_marshal(self):
        self.assertFlags(self.RULE, "a.py", "code = marshal.loads(blob)")

    def test_yaml_load_bare(self):
        self.assertFlags(self.RULE, "a.py", "cfg = yaml.load(fh)")

    def test_yaml_load_wrong_loader(self):
        self.assertFlags(self.RULE, "a.py", "cfg = yaml.load(fh, Loader=yaml.Loader)")

    def test_yaml_safe_load_clean(self):
        self.assertClean(self.RULE, "a.py", "cfg = yaml.safe_load(fh)")

    def test_yaml_safe_loader_clean(self):
        self.assertClean(self.RULE, "a.py", "cfg = yaml.load(fh, Loader=yaml.SafeLoader)")

    def test_yaml_safe_loader_next_line_clean(self):
        self.assertClean(self.RULE, "a.py", "cfg = yaml.load(", "    fh, Loader=yaml.CSafeLoader", ")")

    def test_json_clean(self):
        self.assertClean(self.RULE, "a.py", "obj = json.loads(blob)")

    def test_mention_in_string_clean(self):
        self.assertClean(self.RULE, "a.py", 'msg = "never call pickle.loads on input"')

    def test_non_python_clean(self):
        self.assertClean(self.RULE, "a.js", "const x = pickle.loads(y);")


class TestTlsVerifyDisabled(SecurityRuleTestCase):
    RULE = "security/tls-verify-disabled"
    # Assembled at runtime so this file does not contain the literal setting.
    ENV = "NODE_TLS_REJECT" + "_UNAUTHORIZED"

    def test_python_verify_false(self):
        self.assertFlags(self.RULE, "a.py", "requests.get(url, verify=False)")

    def test_node_reject_unauthorized(self):
        self.assertFlags(self.RULE, "a.js", "const agent = new https.Agent({ rejectUnauthorized: false });")

    def test_go_insecure_skip_verify(self):
        self.assertFlags(self.RULE, "a.go", "cfg := &tls.Config{InsecureSkipVerify: true}")

    def test_node_tls_env_js(self):
        self.assertFlags(self.RULE, "a.js", f"process.env.{self.ENV} = '0';")

    def test_node_tls_env_python(self):
        self.assertFlags(self.RULE, "a.py", f'os.environ["{self.ENV}"] = "0"')

    def test_node_tls_env_shell(self):
        self.assertFlags(self.RULE, "run.sh", f"export {self.ENV}=0")

    def test_verify_true_clean(self):
        self.assertClean(self.RULE, "a.py", "requests.get(url, verify=True)")
        self.assertClean(self.RULE, "a.py", "requests.get(url, verify=ca_bundle)")

    def test_reject_unauthorized_true_clean(self):
        self.assertClean(self.RULE, "a.js", "const o = { rejectUnauthorized: true };")

    def test_node_tls_env_enabled_clean(self):
        self.assertClean(self.RULE, "a.js", f"process.env.{self.ENV} = '1';")

    def test_string_or_comment_clean(self):
        self.assertClean(self.RULE, "a.py", 'hint = "do not pass verify=False"')
        self.assertClean(self.RULE, "a.py", "# verify=False is bad")


class TestInnerHtml(SecurityRuleTestCase):
    RULE = "security/inner-html"
    DANGEROUS = "dangerouslySet" + "InnerHTML"
    PROP = "inner" + "HTML"  # assembled so style rules do not flag this file

    def test_inner_html_assignment(self):
        self.assertFlags(self.RULE, "a.js", f"el.{self.PROP} = userInput;")
        self.assertFlags(self.RULE, "a.ts", f"el.{self.PROP} += chunk;")

    def test_dangerously_set(self):
        self.assertFlags(self.RULE, "a.tsx", f"<div {self.DANGEROUS}={{{{ __html: html }}}} />")

    def test_document_write(self):
        self.assertFlags(self.RULE, "a.js", "document.write(payload);")

    def test_severity_is_warning(self):
        found = self.violations("a.js", f"el.{self.PROP} = x;")
        self.assertEqual(found[0].severity, Severity.WARNING)

    def test_text_content_clean(self):
        self.assertClean(self.RULE, "a.js", "el.textContent = userInput;")

    def test_read_and_compare_clean(self):
        self.assertClean(self.RULE, "a.js", f"const html = el.{self.PROP};")
        self.assertClean(self.RULE, "a.js", f"if (el.{self.PROP} === '') {{ return; }}")

    def test_clearing_clean(self):
        self.assertClean(self.RULE, "a.js", f"el.{self.PROP} = '';")

    def test_python_clean(self):
        self.assertClean(self.RULE, "a.py", f"el.{self.PROP} = value")


class TestWeakHash(SecurityRuleTestCase):
    RULE = "security/weak-hash"

    def test_hashlib_md5_sha1(self):
        self.assertFlags(self.RULE, "a.py", "digest = hashlib.md5(data).hexdigest()")
        self.assertFlags(self.RULE, "a.py", "digest = hashlib.sha1(data).hexdigest()")

    def test_node_create_hash(self):
        self.assertFlags(self.RULE, "a.js", "crypto.createHash('md5').update(x)")
        self.assertFlags(self.RULE, "a.ts", 'crypto.createHash("sha1").update(x)')

    def test_usedforsecurity_false_clean(self):
        self.assertClean(self.RULE, "a.py", "digest = hashlib.md5(data, usedforsecurity=False)")

    def test_sha256_clean(self):
        self.assertClean(self.RULE, "a.py", "digest = hashlib.sha256(data)")
        self.assertClean(self.RULE, "a.js", "crypto.createHash('sha256').update(x)")

    def test_string_mention_clean(self):
        self.assertClean(self.RULE, "a.py", 'note = "hashlib.md5( is weak"')

    def test_severity_is_warning(self):
        found = self.violations("a.py", "h = hashlib.md5(b)")
        self.assertEqual(found[0].severity, Severity.WARNING)


class TestUnexplainedSuppression(SecurityRuleTestCase):
    RULE = "quality/unexplained-suppression"

    def test_bare_type_ignore(self):
        self.assertFlags(self.RULE, "a.py", "x = foo()  # type: ignore")

    def test_bare_noqa(self):
        self.assertFlags(self.RULE, "a.py", "import os  # noqa")

    def test_bare_ts_ignore(self):
        self.assertFlags(self.RULE, "a.ts", "// @ts-ignore")

    def test_bare_eslint_disable(self):
        self.assertFlags(self.RULE, "a.js", "// eslint-disable-next-line")
        self.assertFlags(self.RULE, "a.js", "/* eslint-disable */")

    def test_type_ignore_with_code_clean(self):
        self.assertClean(self.RULE, "a.py", "x = foo()  # type: ignore[attr-defined]")

    def test_type_ignore_with_reason_clean(self):
        self.assertClean(self.RULE, "a.py", "x = foo()  # type: ignore  # stubs lack this attribute")

    def test_noqa_with_code_clean(self):
        self.assertClean(self.RULE, "a.py", "import os  # noqa: F401")
        self.assertClean(self.RULE, "a.py", "x = 3  # noqa: magic-literal")

    def test_noqa_with_reason_clean(self):
        self.assertClean(self.RULE, "a.py", "import os  # noqa re-exported for plugins")

    def test_ts_ignore_with_reason_clean(self):
        self.assertClean(self.RULE, "a.ts", "// @ts-ignore upstream typing bug, see #12")

    def test_eslint_disable_with_rule_clean(self):
        self.assertClean(self.RULE, "a.js", "// eslint-disable-next-line no-console")
        self.assertClean(self.RULE, "a.js", "foo(); // eslint-disable-line no-undef -- legacy global")

    def test_reviewer_directives_clean(self):
        self.assertClean(self.RULE, "a.py", "x = 1  # noqa  # reviewer:allow-debug")
        self.assertClean(self.RULE, "a.js", "// @ts-ignore reviewer:ignore")

    def test_marker_inside_string_clean(self):
        self.assertClean(self.RULE, "a.py", 'label = "# noqa"')
        self.assertClean(self.RULE, "a.js", "const s = '// @ts-ignore';")

    def test_python_directive_in_js_clean(self):
        self.assertClean(self.RULE, "a.js", "foo(); // noqa")


class TestTsAny(SecurityRuleTestCase):
    RULE = "quality/ts-any"

    def test_annotation(self):
        self.assertFlags(self.RULE, "a.ts", "function f(x: any) { return x; }")

    def test_cast(self):
        self.assertFlags(self.RULE, "a.tsx", "const y = value as any;")

    def test_angle_bracket(self):
        self.assertFlags(self.RULE, "a.ts", "const z = <any>value;")
        self.assertFlags(self.RULE, "a.ts", "const p: Promise<any> = go();")

    def test_severity_is_info(self):
        found = self.violations("a.ts", "let x: any;")
        self.assertEqual(found[0].severity, Severity.INFO)

    def test_unknown_and_identifiers_clean(self):
        self.assertClean(self.RULE, "a.ts", "function f(x: unknown) { return x; }")
        self.assertClean(self.RULE, "a.ts", "const anyone: Anything = company;")
        self.assertClean(self.RULE, "a.ts", "let x: anyValue;")

    def test_js_clean(self):
        self.assertClean(self.RULE, "a.js", "const y = value as any;")

    def test_comment_and_string_clean(self):
        self.assertClean(self.RULE, "a.ts", "// x: any is discouraged")
        self.assertClean(self.RULE, "a.ts", "const m = 'use as any sparingly';")


if __name__ == "__main__":
    unittest.main()
