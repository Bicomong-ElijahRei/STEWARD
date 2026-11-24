"""Safety tests for the C3-I1 pure, byte-preserving patch engine."""

import ast
import builtins
import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from agents.patch_engine import PatchEngineError, decode_patch_artifact, stage_patch


MAX_EDIT_BYTES = 16 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 1024 * 1024


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _decode_source(raw):
    return raw.decode("utf-8-sig")


def _detect_newline(raw):
    text = raw.decode("utf-8-sig")
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf and (lf or cr):
        raise AssertionError("mixed newline fixture")
    if cr:
        raise AssertionError("unsupported CR fixture")
    return "crlf" if crlf else "lf"


def _line_starts(text):
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    return starts


def _qualified_names(tree):
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    names = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        parts = [node.name]
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parts.append(parent.name)
            parent = parents.get(parent)
        names[id(node)] = ".".join(["Module"] + list(reversed(parts)))
    return names


def _character_offsets(text, node):
    starts = _line_starts(text)
    lines = text.splitlines(keepends=True)
    start_byte = len(text[: starts[node.lineno - 1]].encode("utf-8"))
    start_byte += len(lines[node.lineno - 1][: node.col_offset].encode("utf-8"))
    end_line = node.end_lineno or node.lineno
    end_col = node.end_col_offset or node.col_offset
    end_byte = len(text[: starts[end_line - 1]].encode("utf-8"))
    end_byte += len(lines[end_line - 1][:end_col].encode("utf-8"))
    return len(text.encode("utf-8")[:start_byte].decode("utf-8")), len(
        text.encode("utf-8")[:end_byte].decode("utf-8")
    )


def _anchor(text, node_kind, qualified_name, occurrence=0):
    tree = ast.parse(text)
    names = _qualified_names(tree)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and type(node).__name__ == node_kind
        and names.get(id(node)) == qualified_name
    ]
    if occurrence >= len(matches):
        raise AssertionError(f"ambiguous fixture anchor {qualified_name}")
    node = matches[occurrence]
    start, end = _character_offsets(text, node)
    return {
        "node_kind": node_kind,
        "qualified_name": qualified_name,
        "occurrence": occurrence,
        "source_start": start,
        "source_end": end,
    }


def _anchor_span(source_bytes, anchor):
    text = _decode_source(source_bytes)
    return text[anchor["source_start"] : anchor["source_end"]].encode("utf-8")


def _make_edit(source_bytes, op, anchor, replacement):
    return {
        "op": op,
        "anchor": copy.deepcopy(anchor),
        "replacement": replacement,
        "expected_sha256": _sha256(_anchor_span(source_bytes, anchor)),
    }


def _make_patch(source_bytes, edits, relative_path="sample.py"):
    raw = bytes(source_bytes)
    file_object = {
        "relative_path": relative_path,
        "source_sha256": _sha256(raw),
        "source_bytes": len(raw),
        "encoding": "utf-8",
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "newline": _detect_newline(raw),
        "edits": edits,
    }
    return {
        "schema_version": 1,
        "patch_id": "11111111-1111-4111-8111-111111111111",
        "plan_id": "22222222-2222-4222-8222-222222222222",
        "workspace_fingerprint": "workspace-fingerprint",
        "files": [file_object],
        "created_utc": "2026-11-24T00:00:00Z",
    }


def _encode_artifact(patch):
    return json.dumps(
        patch, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _stage(source_bytes, patch=None, artifact=None):
    if patch is None:
        patch = _make_patch(source_bytes, [])
    if artifact is None:
        artifact = _encode_artifact(patch)
    return stage_patch(source_bytes, patch, artifact)


class PatchSchemaTests(unittest.TestCase):
    def setUp(self):
        self.source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(self.source), "FunctionDef", "Module.alpha")
        self.edit = _make_edit(
            self.source, "replace_node", anchor, "def alpha():\n    return 2"
        )
        self.patch = _make_patch(self.source, [self.edit])

    def _reject(self, patch, artifact=None):
        with self.assertRaises(PatchEngineError):
            _stage(self.source, patch, artifact)

    def test_valid_patch_is_accepted(self):
        result = _stage(self.source, self.patch)
        self.assertEqual(b"def alpha():\n    return 2\n", result.output_bytes)

    def test_unknown_keys_are_rejected_at_every_level(self):
        cases = []
        top = copy.deepcopy(self.patch)
        top["command"] = "python target.py"
        cases.append(top)
        file_case = copy.deepcopy(self.patch)
        file_case["files"][0]["absolute_path"] = "C:\\target.py"
        cases.append(file_case)
        edit_case = copy.deepcopy(self.patch)
        edit_case["files"][0]["edits"][0]["executable"] = "target"
        cases.append(edit_case)
        anchor_case = copy.deepcopy(self.patch)
        anchor_case["files"][0]["edits"][0]["anchor"]["line"] = 1
        cases.append(anchor_case)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self._reject(candidate)

    def test_missing_fields_are_rejected(self):
        for section, key in (
            ("top", "plan_id"),
            ("file", "newline"),
            ("edit", "expected_sha256"),
            ("anchor", "occurrence"),
        ):
            candidate = copy.deepcopy(self.patch)
            target = {
                "top": candidate,
                "file": candidate["files"][0],
                "edit": candidate["files"][0]["edits"][0],
                "anchor": candidate["files"][0]["edits"][0]["anchor"],
            }[section]
            del target[key]
            with self.subTest(section=section, key=key):
                self._reject(candidate)

    def test_wrong_types_are_rejected(self):
        cases = [
            ("schema_version", "1"),
            ("schema_version", 1.0),
            ("files", {}),
            ("created_utc", 123),
            ("file.source_bytes", True),
            ("file.bom", "false"),
            ("file.edits", {}),
            ("edit.op", 1),
            ("edit.replacement", None),
            ("anchor.occurrence", True),
            ("anchor.source_start", "0"),
        ]
        for location, value in cases:
            candidate = copy.deepcopy(self.patch)
            if location in ("schema_version", "files", "created_utc"):
                candidate[location] = value
            elif location.startswith("file."):
                candidate["files"][0][location[5:]] = value
            elif location.startswith("edit."):
                candidate["files"][0]["edits"][0][location[5:]] = value
            else:
                candidate["files"][0]["edits"][0]["anchor"][location[7:]] = value
            with self.subTest(location=location):
                self._reject(candidate)

    def test_duplicate_json_keys_are_rejected(self):
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(PatchEngineError):
            decode_patch_artifact(raw)

    def test_nested_duplicate_json_keys_are_rejected(self):
        raw = (
            b'{"schema_version":1,"patch_id":"x","patch_id":"y",'
            b'"plan_id":"z","workspace_fingerprint":"f","files":[],'
            b'"created_utc":"2026-11-24T00:00:00Z"}'
        )
        with self.assertRaises(PatchEngineError):
            decode_patch_artifact(raw)

    def test_bad_hashes_are_rejected(self):
        for location in ("source", "expected"):
            candidate = copy.deepcopy(self.patch)
            if location == "source":
                candidate["files"][0]["source_sha256"] = "0" * 64
            else:
                candidate["files"][0]["edits"][0]["expected_sha256"] = "not-a-hash"
            with self.subTest(location=location):
                self._reject(candidate)

    def test_uppercase_hash_is_rejected(self):
        candidate = copy.deepcopy(self.patch)
        candidate["files"][0]["source_sha256"] = candidate["files"][0][
            "source_sha256"
        ].upper()
        self._reject(candidate)

    def test_unsafe_relative_paths_are_rejected(self):
        paths = (
            "/absolute.py",
            "C:\\absolute.py",
            "C:/absolute.py",
            "\\\\server\\share\\absolute.py",
            "../escape.py",
            "dir/../escape.py",
            "./sample.py",
            "dir\\sample.py",
            "sample.py/",
            "sample.py\x00",
        )
        for path in paths:
            candidate = copy.deepcopy(self.patch)
            candidate["files"][0]["relative_path"] = path
            with self.subTest(path=path):
                self._reject(candidate)

    def test_artifact_must_decode_to_the_supplied_object(self):
        other = copy.deepcopy(self.patch)
        other["workspace_fingerprint"] = "different"
        with self.assertRaises(PatchEngineError):
            _stage(self.source, self.patch, _encode_artifact(other))

    def test_artifact_and_object_must_match_exact_types(self):
        artifact = _encode_artifact(self.patch)
        other = copy.deepcopy(self.patch)
        other["files"][0]["source_bytes"] = float(other["files"][0]["source_bytes"])
        with self.assertRaises(PatchEngineError):
            _stage(self.source, other, artifact)

    def test_patch_object_is_not_mutated(self):
        before = copy.deepcopy(self.patch)
        _stage(self.source, self.patch)
        self.assertEqual(before, self.patch)


class PatchBoundsTests(unittest.TestCase):
    def setUp(self):
        self.source = b"def alpha():\n    return 1\n"
        self.text = _decode_source(self.source)
        self.anchor = _anchor(self.text, "FunctionDef", "Module.alpha")

    def _edit(self, replacement="def alpha():\n    return 2"):
        return _make_edit(self.source, "replace_node", self.anchor, replacement)

    def test_exactly_one_file_is_accepted_and_two_are_rejected(self):
        patch = _make_patch(self.source, [self._edit()])
        _stage(self.source, patch)
        patch["files"].append(copy.deepcopy(patch["files"][0]))
        with self.assertRaises(PatchEngineError):
            _stage(self.source, patch)

    def test_twenty_edits_pass_and_twenty_one_reject(self):
        source = b"".join(
            f"def f{index}():\n    return {index}\n".encode("ascii")
            for index in range(21)
        )
        text = _decode_source(source)
        edits = []
        for index in range(21):
            anchor = _anchor(text, "FunctionDef", f"Module.f{index}")
            edits.append(
                _make_edit(
                    source,
                    "replace_node",
                    anchor,
                    f"def f{index}():\n    return {index + 1}",
                )
            )
        _stage(source, _make_patch(source, edits[:20]))
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, edits))

    def _sized_edit(self, encoded_size):
        replacement = "#x\n"
        while True:
            candidate = {
                "op": "replace_node",
                "anchor": copy.deepcopy(self.anchor),
                "replacement": replacement,
                "expected_sha256": _sha256(_anchor_span(self.source, self.anchor)),
            }
            size = len(candidate["replacement"].encode("utf-8")) + len(
                json.dumps(
                    candidate["anchor"], ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")
                ).encode("utf-8")
            )
            if size == encoded_size:
                return candidate
            if size > encoded_size:
                self.fail("could not construct exact-sized edit")
            replacement = "#" + "x" * (len(replacement) - 1) + "\n"

    def test_edit_at_16_kib_passes_and_limit_plus_one_rejects(self):
        exact = self._sized_edit(MAX_EDIT_BYTES)
        _stage(self.source, _make_patch(self.source, [exact]))
        oversized = self._sized_edit(MAX_EDIT_BYTES + 1)
        with self.assertRaises(PatchEngineError):
            _stage(self.source, _make_patch(self.source, [oversized]))

    def _artifact_exact_patch(self, target_size):
        count = 20
        source = b"".join(
            f"def f{index}():\n    return {index}\n".encode("ascii")
            for index in range(count)
        )
        text = _decode_source(source)
        anchors = [_anchor(text, "FunctionDef", f"Module.f{index}") for index in range(count)]
        edits = []
        for anchor in anchors:
            replacement = "#" + "x" * 12000 + "\n"
            edits.append(_make_edit(source, "replace_node", anchor, replacement))
        patch = _make_patch(source, edits)
        difference = target_size - len(_encode_artifact(patch))
        if difference < 0:
            self.fail("base artifact is too large")
        per_edit = difference // count
        remainder = difference % count
        for index, anchor in enumerate(anchors):
            addition = per_edit + (1 if index < remainder else 0)
            replacement = "#" + "x" * (12000 + addition - 1) + "\n"
            edits[index] = _make_edit(source, "replace_node", anchor, replacement)
        patch = _make_patch(source, edits)
        compact = _encode_artifact(patch)
        difference = target_size - len(compact)
        artifact = compact + (b" " * difference)
        self.assertEqual(target_size, len(artifact))
        return source, patch, artifact

    def test_artifact_at_256_kib_passes_and_limit_plus_one_rejects(self):
        source, patch, artifact = self._artifact_exact_patch(MAX_ARTIFACT_BYTES)
        _stage(source, patch, artifact)
        with self.assertRaises(PatchEngineError):
            _stage(source, patch, artifact + b" ")

    def _one_mib_source(self, final_size):
        prefix = b"# " + (b"x" * (MAX_SOURCE_BYTES - 32)) + b"\n"
        suffix = b"def alpha():\n    return 1\n"
        source = prefix + suffix
        self.assertLessEqual(len(source), final_size)
        source += b" " * (final_size - len(source))
        return source

    def test_original_at_one_mib_passes_and_limit_plus_one_rejects(self):
        source = self._one_mib_source(MAX_SOURCE_BYTES)
        text = _decode_source(source)
        anchor = _anchor(text, "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        _stage(source, _make_patch(source, [edit]))
        with self.assertRaises(PatchEngineError):
            _stage(source + b" ", _make_patch(source + b" ", [edit]))

    def test_output_at_one_mib_passes_and_limit_plus_one_rejects(self):
        source = self._one_mib_source(MAX_SOURCE_BYTES)
        text = _decode_source(source)
        anchor = _anchor(text, "FunctionDef", "Module.alpha")
        span = _anchor_span(source, anchor)
        same_size = "#" + "x" * (len(span) - 1)
        edit = _make_edit(source, "replace_node", anchor, same_size)
        result = _stage(source, _make_patch(source, [edit]))
        self.assertEqual(MAX_SOURCE_BYTES, len(result.output_bytes))
        larger = "#" + "x" * len(span)
        edit = _make_edit(source, "replace_node", anchor, larger)
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))


class PatchAnchorTests(unittest.TestCase):
    def test_non_ascii_anchor_uses_character_offsets(self):
        source = "def alpha():\n    value = 'π'\n    return value\n".encode("utf-8")
        text = _decode_source(source)
        anchor = _anchor(text, "FunctionDef", "Module.alpha")
        self.assertEqual(text.index("def alpha"), anchor["source_start"])
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 'π'")
        result = _stage(source, _make_patch(source, [edit]))
        self.assertEqual("π".encode("utf-8"), "π".encode("utf-8"))
        self.assertIn("return 'π'".encode("utf-8"), result.output_bytes)

    def test_edits_must_be_in_source_order(self):
        source = b"def first():\n    return 1\ndef second():\n    return 2\n"
        text = _decode_source(source)
        first = _anchor(text, "FunctionDef", "Module.first")
        second = _anchor(text, "FunctionDef", "Module.second")
        first_edit = _make_edit(source, "replace_node", first, "def first():\n    return 3")
        second_edit = _make_edit(source, "replace_node", second, "def second():\n    return 4")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [second_edit, first_edit]))

    def test_missing_anchor_is_rejected(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        anchor["qualified_name"] = "missing"
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))

    def test_ambiguous_occurrence_is_rejected(self):
        source = b"def dup():\n    return 1\ndef dup():\n    return 2\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.dup", 0)
        anchor["occurrence"] = 2
        edit = _make_edit(source, "replace_node", anchor, "def dup():\n    return 3")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))

    def test_offset_inconsistent_anchor_is_rejected(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        anchor["source_end"] += 1
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))

    def test_overlapping_edits_are_rejected(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        replace = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        insert = _make_edit(source, "insert_before", anchor, "VALUE = 1\n")
        with self.assertRaises(PatchEngineError) as caught:
            _stage(source, _make_patch(source, [replace, insert]))
        self.assertIn("overlap", str(caught.exception).casefold())

    def test_delete_node_is_rejected_as_unsupported(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "delete_node", anchor, "")
        with self.assertRaises(PatchEngineError) as caught:
            _stage(source, _make_patch(source, [edit]))
        self.assertIn("unsupported", str(caught.exception).casefold())


class PatchSplicingTests(unittest.TestCase):
    def test_output_parses_and_outside_bytes_are_identical(self):
        source = (
            b"# leading comment\n"
            b"x = 'quoted'   \n"
            b"\n"
            b"def alpha():\n"
            b"    old = 1\n"
            b"    return old\n"
            b"# trailing comment\n"
        )
        text = _decode_source(source)
        anchor = _anchor(text, "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        result = _stage(source, _make_patch(source, [edit]))
        ast.parse(_decode_source(result.output_bytes))
        self.assertEqual(
            result.proof["original_outside_sha256"],
            result.proof["output_outside_sha256"],
        )
        self.assertTrue(result.proof["outside_bytes_equal"])
        self.assertEqual(
            source[: anchor["source_start"]],
            result.output_bytes[: result.proof["edited_ranges"][0]["output"][0]],
        )

    def test_insertions_parse_in_target_context(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        before = _make_edit(source, "insert_before", anchor, "VALUE = 1\n")
        after = _make_edit(source, "insert_after", anchor, "\nAFTER = 2\n")
        result = _stage(source, _make_patch(source, [before, after]))
        ast.parse(_decode_source(result.output_bytes))
        self.assertIn(b"VALUE = 1", result.output_bytes)
        self.assertIn(b"AFTER = 2", result.output_bytes)

    def test_malformed_insertion_is_rejected(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "insert_before", anchor, "def broken(\n")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))

    def test_invalid_replacement_output_is_rejected(self):
        source = b"def alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "replace_node", anchor, "def broken(\n")
        with self.assertRaises(PatchEngineError):
            _stage(source, _make_patch(source, [edit]))


class PatchEncodingTests(unittest.TestCase):
    def _replace(self, source):
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        return _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")

    def test_utf8_bom_is_preserved_exactly(self):
        source = b"\xef\xbb\xbfdef alpha():\n    return 1\n"
        result = _stage(source, _make_patch(source, [self._replace(source)]))
        self.assertTrue(result.output_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(source[:3], result.output_bytes[:3])

    def test_lf_and_crlf_are_preserved(self):
        for newline, encoded in (("lf", b"\n"), ("crlf", b"\r\n")):
            source = encoded.join((b"def alpha():", b"    return 1", b""))
            result = _stage(source, _make_patch(source, [self._replace(source)]))
            self.assertEqual(newline, _detect_newline(result.output_bytes))

    def test_no_final_newline_is_preserved(self):
        source = b"def alpha():\n    return 1"
        result = _stage(source, _make_patch(source, [self._replace(source)]))
        self.assertFalse(result.output_bytes.endswith(b"\n"))

    def test_utf16_undecodable_and_mixed_newlines_are_refused(self):
        cases = (
            "def alpha():\n    return 1\n".encode("utf-16"),
            b"def alpha():\n    return \xff1\n",
        )
        valid = b"def alpha():\n    return 1\n"
        patch = _make_patch(valid, [self._replace(valid)])
        for source in cases:
            candidate = copy.deepcopy(patch)
            candidate["files"][0]["source_sha256"] = _sha256(source)
            candidate["files"][0]["source_bytes"] = len(source)
            with self.subTest(source=source):
                with self.assertRaises(PatchEngineError):
                    _stage(source, candidate)
        mixed = b"def alpha():\r\n    return 1\n"
        patch = _make_patch(valid, [self._replace(valid)])
        patch["files"][0]["source_sha256"] = _sha256(mixed)
        patch["files"][0]["source_bytes"] = len(mixed)
        patch["files"][0]["newline"] = "crlf"
        with self.assertRaises(PatchEngineError) as caught:
            _stage(mixed, patch)
        self.assertIn("mixed", str(caught.exception).casefold())


class PatchDeterminismAndPurityTests(unittest.TestCase):
    def _fixture(self):
        source = b"# keep\ndef alpha():\n    return 1\n"
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        return source, _make_patch(source, [edit])

    def test_identical_inputs_produce_identical_results(self):
        source, patch = self._fixture()
        first = _stage(source, copy.deepcopy(patch))
        second = _stage(source, copy.deepcopy(patch))
        self.assertEqual(first.output_bytes, second.output_bytes)
        self.assertEqual(first.unified_diff, second.unified_diff)
        self.assertEqual(first.proof, second.proof)

    def test_generation_performs_no_filesystem_process_or_execution_calls(self):
        source, patch = self._fixture()
        forbidden = [
            mock.patch.object(builtins, "open", side_effect=AssertionError("open")),
            mock.patch.object(os, "replace", side_effect=AssertionError("replace")),
            mock.patch.object(os, "remove", side_effect=AssertionError("remove")),
            mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess")),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")),
            mock.patch.object(builtins, "exec", side_effect=AssertionError("exec")),
            mock.patch.object(builtins, "eval", side_effect=AssertionError("eval")),
        ]
        for patcher in forbidden:
            patcher.start()
        try:
            result = _stage(source, patch)
        finally:
            for patcher in reversed(forbidden):
                patcher.stop()
        self.assertEqual(b"# keep\ndef alpha():\n    return 2\n", result.output_bytes)

    def test_target_module_is_not_imported(self):
        source = b"import forbidden_patch_target\n\ndef alpha():\n    return 1\n"
        sys.modules.pop("forbidden_patch_target", None)
        anchor = _anchor(_decode_source(source), "FunctionDef", "Module.alpha")
        edit = _make_edit(source, "replace_node", anchor, "def alpha():\n    return 2")
        _stage(source, _make_patch(source, [edit]))
        self.assertNotIn("forbidden_patch_target", sys.modules)


if __name__ == "__main__":
    unittest.main()

