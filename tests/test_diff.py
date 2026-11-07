"""Unit tests for diff parsing."""

import unittest
from reviewer.git_diff import parse_unified_diff

SAMPLE_DIFF = """diff --git a/src/app.ts b/src/app.ts
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/src/app.ts
@@ -0,0 +1,5 @@
+import express from "express";
+const app = express();
+if (!app) return;
+export default app;
+console.log("Ready");
diff --git a/package-lock.json b/package-lock.json
index 2222222..3333333 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,3 +1,3 @@
 {
-  "version": "1.0.0"
+  "version": "1.0.1"
 }
"""


class TestDiffParser(unittest.TestCase):
    def test_parse_unified_diff_extracts_added_lines_and_filters_ignored(self):
        diffs = parse_unified_diff(SAMPLE_DIFF)
        # package-lock.json should be ignored
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "src/app.ts")
        self.assertEqual(diffs[0].status, "added")
        self.assertEqual(len(diffs[0].added_lines), 5)
        # Check line numbering
        line_numbers = [line_no for line_no, _ in diffs[0].added_lines]
        self.assertEqual(line_numbers, [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
