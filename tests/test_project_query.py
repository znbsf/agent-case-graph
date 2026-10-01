from __future__ import annotations

import copy
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from agent_case_graph.cli import main
from agent_case_graph.model import ACGError
from agent_case_graph.project_profile import inspect_project
from agent_case_graph.project_query import _decode_cursor, _encode_cursor, query_project
from tests.test_project_planning import RepositoryFixture


class ProjectQueryTests(RepositoryFixture):
    def test_untracked_commonjs_and_esm_edits_expire_plans_and_page_cursors(self):
        from agent_case_graph.planning import check_plan
        for name in ("prototype-check.cjs", "tools/browser-check.mjs"):
            with self.subTest(name=name):
                self.write(name, "console.log('original');\n")
                page = query_project(self.root, page_size=1)
                proposal = self.plan()
                status = self.git("status", "--porcelain=v1")
                self.write(name, "throw new Error('changed source');\n")
                self.assertEqual(status, self.git("status", "--porcelain=v1"))
                with self.assertRaisesRegex(ACGError, "repository changed"):
                    query_project(self.root, page_size=1, cursor=page["pagination"]["next_cursor"])
                self.assertIn("stale_repository_snapshot", {row["code"] for row in check_plan(self.root, proposal)["errors"]})

    def test_unicode_python_module_names_are_queryable(self):
        self.write("pkg/模块.py", "value = 1\n")
        result = query_project(self.root, module="pkg.模块", include_neighbors=False)
        self.assertEqual(result["items"][0]["path"], "pkg/模块.py")

    def test_noncanonical_path_case_is_explicitly_rejected(self):
        if os.name != "nt":
            self.skipTest("case alias is a Windows filesystem boundary")
        with self.assertRaisesRegex(ACGError, "canonical spelling"):
            query_project(self.root, path="PKG")

    def test_path_subtree_has_component_boundaries_and_preserves_spaces(self):
        self.write("pkg_extra/other.py", "x = 1\n")
        self.write("a space/helper.py", "x = 1\n")
        result = query_project(self.root, path="pkg", include_neighbors=False)
        self.assertEqual([row["path"] for row in result["items"]], ["pkg/__init__.py", "pkg/cli.py", "pkg/core.py"])
        self.assertEqual(query_project(self.root, path="a space", include_neighbors=False)["items"][0]["path"], "a space/helper.py")

    def test_exact_module_returns_only_one_hop_neighbors(self):
        self.write("pkg/deep.py", "from . import cli\n")
        result = query_project(self.root, module="pkg.core")
        self.assertEqual([row["path"] for row in result["items"]], ["pkg/cli.py", "pkg/core.py", "tests/test_core.py"])
        self.assertEqual(result["pagination"]["direct_file_count"], 1)
        self.assertEqual(query_project(self.root, module="pkg.core", include_neighbors=False)["items"][0]["selection"], "direct")

    def test_module_ambiguity_does_not_hide_distinct_paths(self):
        self.write("src/pkg/core.py", "value = 1\n")
        with self.assertRaisesRegex(ACGError, "ambiguous"):
            query_project(self.root, module="pkg.core")
        result = query_project(self.root, path="src/pkg/core.py", include_neighbors=False)
        self.assertEqual(result["items"][0]["path"], "src/pkg/core.py")
        with self.assertRaises(ACGError):
            query_project(self.root, module="pkg.missing")

    def test_pages_have_stable_order_no_duplicates_or_lost_sources_and_edges(self):
        before = self.git("status", "--porcelain=v1")
        profile = inspect_project(self.root)
        paths, edges = [], []
        cursor = None
        while True:
            page = query_project(self.root, page_size=2, cursor=cursor)
            self.assertEqual(page, query_project(self.root, page_size=2, cursor=cursor))
            self.assertEqual(page["source_snapshot_sha256"], profile["snapshot_sha256"])
            self.assertLessEqual(len(page["items"]), 2)
            self.assertEqual({row["id"] for row in page["sources"]}, {ref for row in page["items"] for ref in row["source_refs"]})
            for item in page["items"]:
                source = next(row for row in page["sources"] if row["path"] == item["path"])
                self.assertEqual(item["sha256"], source["sha256"])
            paths.extend(row["path"] for row in page["items"])
            edges.extend(page["relationships"])
            cursor = page["pagination"]["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(paths, sorted(row["path"] for row in profile["inventory"]["files"]))
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(sorted(edges, key=str), sorted(profile["relationships"], key=str))
        self.assertEqual(before, self.git("status", "--porcelain=v1"))

    def test_cursor_binds_all_query_parameters(self):
        cursor = query_project(self.root, path="pkg", page_size=1)["pagination"]["next_cursor"]
        for kwargs in ({"path": "tests"}, {"module": "pkg.core"}, {"include_neighbors": False}, {"page_size": 2}):
            options = {"path": "pkg", "page_size": 1, **kwargs}
            if "module" in kwargs:
                options.pop("path")
            with self.subTest(options=options), self.assertRaisesRegex(ACGError, "different parameters"):
                query_project(self.root, cursor=cursor, **options)

    def test_cursor_expires_for_same_dirty_status_and_new_files(self):
        self.write("pkg/core.py", "value = 2\n")
        first = query_project(self.root, page_size=1)
        status = self.git("status", "--porcelain=v1")
        self.write("pkg/core.py", "value = 3\n")
        self.assertEqual(status, self.git("status", "--porcelain=v1"))
        with self.assertRaisesRegex(ACGError, "repository changed"):
            query_project(self.root, page_size=1, cursor=first["pagination"]["next_cursor"])
        second = query_project(self.root, page_size=1)
        self.write("pkg/new.py", "value = 1\n")
        with self.assertRaisesRegex(ACGError, "repository changed"):
            query_project(self.root, page_size=1, cursor=second["pagination"]["next_cursor"])

    def test_malformed_noncanonical_and_out_of_range_cursors_are_rejected(self):
        for cursor in ("", "!invalid", "a" * 1025, 7, _encode_cursor({"version": "nope"})):
            with self.subTest(cursor=str(cursor)[:30]), self.assertRaisesRegex(ACGError, "cursor"):
                query_project(self.root, cursor=cursor)
        cursor = query_project(self.root, page_size=2)["pagination"]["next_cursor"]
        for offset in (True, -1, 1, 999):
            payload = _decode_cursor(cursor)
            payload["offset"] = offset
            with self.subTest(offset=offset), self.assertRaisesRegex(ACGError, "cursor"):
                query_project(self.root, page_size=2, cursor=_encode_cursor(payload))
        with self.assertRaises(ACGError):
            query_project(self.root, page_size=2, cursor=cursor + "=")

    def test_paths_and_parameter_types_reject_unsafe_or_excluded_inputs(self):
        for path in ("../outside", "/absolute", "C:/absolute", "pkg\\core.py", "pkg/../core.py", "pkg//core.py", ".env", "secrets./token.py", "credentials.json ", "pkg./core.py", "missing", "", 4):
            with self.subTest(path=path), self.assertRaises(ACGError):
                query_project(self.root, path=path)
        for page_size in (True, 0, -1, 51, 1.5, "2"):
            with self.subTest(page_size=page_size), self.assertRaises(ACGError):
                query_project(self.root, page_size=page_size)
        for options in ({"path": "pkg", "module": "pkg.core"}, {"module": "../core"}, {"module": 5}, {"include_neighbors": 1}):
            with self.assertRaises(ACGError):
                query_project(self.root, **options)

    def test_truncation_and_byte_skips_remain_visible_on_every_page(self):
        with patch("agent_case_graph.project_profile.MAX_FILES", 1):
            page = query_project(self.root, path="pkg", include_neighbors=False)
        self.assertEqual(page["items"], [])
        self.assertTrue(page["inspection_scope"]["truncated"])
        with patch("agent_case_graph.project_profile.MAX_FILE_BYTES", 20):
            page = query_project(self.root, path="pkg", page_size=1)
        self.assertTrue(page["inspection_scope"]["skipped"])
        self.assertIn("file_byte_limit", {row["reason"] for row in page["inspection_scope"]["skipped"]})

    def test_inspection_does_not_import_source_or_run_commands(self):
        self.write("pkg/bomb.py", "raise RuntimeError('must not execute')\n")
        page = query_project(self.root, path="pkg/bomb.py")
        self.assertEqual(page["execution_status"], "not_run")
        self.assertFalse(page["execution_authorized"])
        self.assertTrue(page["items"][0]["python_modules"]["parsed"])

    def test_cli_produces_same_context_and_actionable_errors(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["query-project", str(self.root), "--module", "pkg.core", "--no-neighbors", "--page-size", "1"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result, query_project(self.root, module="pkg.core", include_neighbors=False, page_size=1))
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(main(["query-project", str(self.root), "--page-size", "51"]), 2)
        self.assertIn("page_size", errors.getvalue())
