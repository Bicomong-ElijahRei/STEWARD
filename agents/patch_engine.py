"""Pure C3-I1 patch staging over already-admitted source bytes.

This module deliberately has no filesystem, process, import, or execution API.
Callers supply the original bytes, a decoded patch object, and the exact encoded
JSON artifact used to decode that object.
"""

import ast
import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


MAX_FILES = 1
MAX_EDITS = 20
MAX_EDIT_BYTES = 16 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024

TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "patch_id",
        "plan_id",
        "workspace_fingerprint",
        "files",
        "created_utc",
    }
)
FILE_KEYS = frozenset(
    {
        "relative_path",
        "source_sha256",
        "source_bytes",
        "encoding",
        "bom",
        "newline",
        "edits",
    }
)
EDIT_KEYS = frozenset({"op", "anchor", "replacement", "expected_sha256"})
ANCHOR_KEYS = frozenset(
    {"node_kind", "qualified_name", "occurrence", "source_start", "source_end"}
)
SUPPORTED_OPS = frozenset({"replace_node", "insert_before", "insert_after"})
SUPPORTED_NODE_KINDS = frozenset({"FunctionDef", "AsyncFunctionDef", "ClassDef"})
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PatchEngineError(ValueError):
    """Raised when a patch cannot be staged safely and deterministically."""


@dataclass(frozen=True)
class PatchResult:
    """Staged bytes, exact diff bytes, and the unrelated-byte proof."""

    output_bytes: bytes
    unified_diff: bytes
    proof: dict


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _reject_constant(value):
    raise PatchEngineError(f"Non-standard JSON constant is forbidden: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PatchEngineError(f"Duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def decode_patch_artifact(encoded_artifact):
    """Decode strict UTF-8 JSON while rejecting duplicate keys and non-JSON values."""
    if not isinstance(encoded_artifact, bytes):
        raise PatchEngineError("Encoded patch artifact must be bytes")
    if len(encoded_artifact) > MAX_ARTIFACT_BYTES:
        raise PatchEngineError("Encoded patch artifact exceeds 256 KiB")
    try:
        text = encoded_artifact.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PatchEngineError("Encoded patch artifact must be UTF-8") from exc
    if text.startswith("\ufeff"):
        raise PatchEngineError("Encoded patch artifact must not contain a BOM")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, PatchEngineError):
            raise
        raise PatchEngineError("Encoded patch artifact is not valid strict JSON") from exc
    if not isinstance(value, dict):
        raise PatchEngineError("Patch artifact must decode to a JSON object")
    return value


def _exact_keys(value, expected, label):
    if not isinstance(value, dict):
        raise PatchEngineError(f"{label} must be a JSON object")
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise PatchEngineError(
            f"{label} keys are invalid (missing={missing}, extra={extra})"
        )


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int):
        raise PatchEngineError(f"{label} must be an integer")
    if value < minimum:
        raise PatchEngineError(f"{label} must be at least {minimum}")
    return value


def _text(value, label, maximum, nonempty=True):
    if not isinstance(value, str):
        raise PatchEngineError(f"{label} must be a string")
    if nonempty and not value:
        raise PatchEngineError(f"{label} must not be empty")
    if len(value) > maximum:
        raise PatchEngineError(f"{label} exceeds its deterministic bound")
    return value


def _uuid(value, label):
    _text(value, label, 64)
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise PatchEngineError(f"{label} must be a UUID") from exc
    return value


def _timestamp(value):
    _text(value, "created_utc", 64)
    if not value.endswith("Z"):
        raise PatchEngineError("created_utc must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PatchEngineError("created_utc must be an ISO-8601 UTC timestamp") from exc
    return value


def _relative_path(value):
    _text(value, "relative_path", 4096)
    if value.startswith(("/", "\\")) or "\\" in value:
        raise PatchEngineError("relative_path must be a normalized POSIX relative path")
    if ":" in value or "\x00" in value:
        raise PatchEngineError("relative_path contains forbidden path syntax")
    components = value.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise PatchEngineError("relative_path must be normalized and non-traversing")
    if value.endswith("/"):
        raise PatchEngineError("relative_path must name a file")
    return value


def _validate_schema(patch):
    _exact_keys(patch, TOP_LEVEL_KEYS, "Patch")
    if (
        isinstance(patch["schema_version"], bool)
        or not isinstance(patch["schema_version"], int)
        or patch["schema_version"] != 1
    ):
        raise PatchEngineError("schema_version must be exactly integer 1")
    _uuid(patch["patch_id"], "patch_id")
    _uuid(patch["plan_id"], "plan_id")
    _text(patch["workspace_fingerprint"], "workspace_fingerprint", 512)
    _timestamp(patch["created_utc"])
    files = patch["files"]
    if not isinstance(files, list):
        raise PatchEngineError("files must be an array")
    if len(files) != MAX_FILES:
        raise PatchEngineError("C3-I1 permits exactly one file")
    file_object = files[0]
    _exact_keys(file_object, FILE_KEYS, "files[0]")
    _relative_path(file_object["relative_path"])
    if not HEX_SHA256.fullmatch(file_object["source_sha256"]):
        raise PatchEngineError("source_sha256 must be lowercase SHA-256 hex")
    _integer(file_object["source_bytes"], "source_bytes", 1)
    if file_object["source_bytes"] > MAX_SOURCE_BYTES:
        raise PatchEngineError("source_bytes exceeds 1 MiB")
    if file_object["encoding"] != "utf-8":
        raise PatchEngineError("encoding must be exactly utf-8")
    if not isinstance(file_object["bom"], bool):
        raise PatchEngineError("bom must be a boolean")
    if file_object["newline"] not in ("lf", "crlf"):
        raise PatchEngineError("newline must be exactly lf or crlf")
    edits = file_object["edits"]
    if not isinstance(edits, list) or not edits:
        raise PatchEngineError("edits must be a non-empty array")
    if len(edits) > MAX_EDITS:
        raise PatchEngineError("edits exceeds the 20-edit limit")
    for index, edit in enumerate(edits):
        label = f"edits[{index}]"
        _exact_keys(edit, EDIT_KEYS, label)
        if edit["op"] not in SUPPORTED_OPS:
            raise PatchEngineError(
                f"{label}.op is unsupported in C3-I1 v1: {edit['op']}"
            )
        _text(edit["replacement"], f"{label}.replacement", MAX_EDIT_BYTES, nonempty=False)
        if len(edit["replacement"].encode("utf-8")) > MAX_EDIT_BYTES:
            raise PatchEngineError("Replacement text exceeds 16 KiB")
        if not HEX_SHA256.fullmatch(edit["expected_sha256"]):
            raise PatchEngineError(f"{label}.expected_sha256 must be lowercase SHA-256 hex")
        anchor = edit["anchor"]
        _exact_keys(anchor, ANCHOR_KEYS, f"{label}.anchor")
        _text(anchor["node_kind"], f"{label}.anchor.node_kind", 64)
        _text(anchor["qualified_name"], f"{label}.anchor.qualified_name", 512)
        _integer(anchor["occurrence"], f"{label}.anchor.occurrence", 0)
        _integer(anchor["source_start"], f"{label}.anchor.source_start", 0)
        _integer(anchor["source_end"], f"{label}.anchor.source_end", 0)
        if anchor["source_end"] <= anchor["source_start"]:
            raise PatchEngineError("Anchor source_end must exceed source_start")
        anchor_metadata = json.dumps(
            anchor, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(edit["replacement"].encode("utf-8")) + len(anchor_metadata) > MAX_EDIT_BYTES:
            raise PatchEngineError("Replacement plus anchor metadata exceeds 16 KiB")


def _detect_source_encoding(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise PatchEngineError("UTF-16 source is unsupported")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise PatchEngineError("UTF-32 source is unsupported")
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PatchEngineError("Source must be valid UTF-8") from exc
    if "\x00" in text:
        raise PatchEngineError("Source must not contain NUL bytes")
    crlf_count = text.count("\r\n")
    lf_count = text.count("\n") - crlf_count
    cr_count = text.count("\r") - crlf_count
    if cr_count:
        raise PatchEngineError("Bare CR newlines are unsupported")
    if crlf_count and lf_count:
        raise PatchEngineError("Mixed LF and CRLF newlines are forbidden")
    newline = "crlf" if crlf_count else "lf"
    return text, bom, newline


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


def _ast_char_span(text, node):
    starts = _line_starts(text)
    lines = text.splitlines(keepends=True)
    start_byte = len(text[: starts[node.lineno - 1]].encode("utf-8"))
    start_byte += len(lines[node.lineno - 1][: node.col_offset].encode("utf-8"))
    end_line = node.end_lineno or node.lineno
    end_col = node.end_col_offset or node.col_offset
    end_byte = len(text[: starts[end_line - 1]].encode("utf-8"))
    end_byte += len(lines[end_line - 1][:end_col].encode("utf-8"))
    start = len(text.encode("utf-8")[:start_byte].decode("utf-8"))
    end = len(text.encode("utf-8")[:end_byte].decode("utf-8"))
    return start, end


def _resolve_anchor(tree, text, anchor, label):
    node_kind = anchor["node_kind"]
    if node_kind not in SUPPORTED_NODE_KINDS:
        raise PatchEngineError(f"{label}.anchor.node_kind is unsupported")
    names = _qualified_names(tree)
    matches = [
        node
        for node in ast.walk(tree)
        if type(node).__name__ == node_kind
        and names.get(id(node)) == anchor["qualified_name"]
    ]
    matches.sort(key=lambda node: (node.lineno, node.col_offset))
    occurrence = anchor["occurrence"]
    if occurrence >= len(matches):
        raise PatchEngineError(f"{label}.anchor is missing or ambiguous")
    node = matches[occurrence]
    start, end = _ast_char_span(text, node)
    if start != anchor["source_start"] or end != anchor["source_end"]:
        raise PatchEngineError(f"{label}.anchor offsets are inconsistent")
    return node, start, end


def _normalize_replacement(text, newline):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "crlf":
        normalized = normalized.replace("\n", "\r\n")
    return normalized


def _char_to_byte(text, offset):
    return len(text[:offset].encode("utf-8"))


def _build_splices(source_text, edits, tree):
    prepared = []
    for index, edit in enumerate(edits):
        label = f"edits[{index}]"
        node, start, end = _resolve_anchor(
            tree, source_text, edit["anchor"], label
        )
        expected = _sha256(source_text[start:end].encode("utf-8"))
        if expected != edit["expected_sha256"]:
            raise PatchEngineError(f"{label}.expected_sha256 does not match its pre-image")
        byte_start = _char_to_byte(source_text, start)
        byte_end = _char_to_byte(source_text, end)
        if edit["op"] == "insert_before":
            edit_start = edit_end = byte_start
        elif edit["op"] == "insert_after":
            edit_start = edit_end = byte_end
        else:
            edit_start, edit_end = byte_start, byte_end
        prepared.append(
            {
                "index": index,
                "op": edit["op"],
                "start": start,
                "end": end,
                "byte_start": byte_start,
                "byte_end": byte_end,
                "edit_start": edit_start,
                "edit_end": edit_end,
                "replacement": edit["replacement"],
                "node": node,
            }
        )
    prepared.sort(key=lambda item: (item["byte_start"], item["byte_end"], item["index"]))
    if [item["index"] for item in prepared] != list(range(len(prepared))):
        raise PatchEngineError("Edits must be ordered by source position")
    previous_end = 0
    for item in prepared:
        if item["edit_start"] < previous_end:
            raise PatchEngineError("Edits overlap")
        previous_end = max(previous_end, item["edit_end"])
    for left in range(len(prepared)):
        for right in range(left + 1, len(prepared)):
            first, second = prepared[left], prepared[right]
            if first["edit_start"] == second["edit_start"] and first["op"] in (
                "insert_before",
                "insert_after",
            ) and second["op"] in ("insert_before", "insert_after"):
                raise PatchEngineError("Insertions at the same boundary overlap")
            first_is_replacement = first["op"] == "replace_node"
            second_is_replacement = second["op"] == "replace_node"
            if first_is_replacement and second["op"] in ("insert_before", "insert_after"):
                if first["edit_start"] <= second["edit_start"] <= first["edit_end"]:
                    raise PatchEngineError("Edits overlap")
            if second_is_replacement and first["op"] in ("insert_before", "insert_after"):
                if second["edit_start"] <= first["edit_start"] <= second["edit_end"]:
                    raise PatchEngineError("Edits overlap")
    return prepared


def _apply_splices(source_bytes, prepared, newline):
    body = source_bytes[3:] if source_bytes.startswith(b"\xef\xbb\xbf") else source_bytes
    output = bytearray()
    cursor = 0
    ranges = []
    for item in prepared:
        replacement = _normalize_replacement(item["replacement"], newline).encode("utf-8")
        output.extend(body[cursor : item["edit_start"]])
        output.extend(replacement)
        cursor = item["edit_end"]
        ranges.append(
            {
                "original": [item["edit_start"], item["edit_end"]],
                "output": [len(output) - len(replacement), len(output)],
            }
        )
    output.extend(body[cursor:])
    if source_bytes.startswith(b"\xef\xbb\xbf"):
        output = bytearray(b"\xef\xbb\xbf") + output
        for item in ranges:
            item["original"][0] += 3
            item["original"][1] += 3
            item["output"][0] += 3
            item["output"][1] += 3
    return bytes(output), ranges


def _outside_bytes(data, ranges, source_side):
    pieces = []
    cursor = 0
    for item in sorted(ranges, key=lambda entry: entry[source_side][0]):
        start, end = item[source_side]
        pieces.append(data[cursor:start])
        cursor = max(cursor, end)
    pieces.append(data[cursor:])
    return b"".join(pieces)


def _unified_diff(source_bytes, output_bytes, relative_path):
    source_text = source_bytes.decode("utf-8-sig")
    output_text = output_bytes.decode("utf-8-sig")
    source_lines = source_text.splitlines(keepends=True)
    output_lines = output_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        source_lines,
        output_lines,
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
    )
    diff_text = "".join(diff)
    if source_bytes.endswith(b"\r\n") or output_bytes.endswith(b"\r\n"):
        diff_text = diff_text.replace("\r\n", "\n").replace("\n", "\r\n")
    return diff_text.encode("utf-8")


def _validate_source_binding(file_object, source_bytes, source_text, bom, newline):
    if len(source_bytes) != file_object["source_bytes"]:
        raise PatchEngineError("source_bytes does not match the supplied source")
    if _sha256(source_bytes) != file_object["source_sha256"]:
        raise PatchEngineError("source_sha256 does not match the supplied source")
    if bom != file_object["bom"]:
        raise PatchEngineError("bom does not match the supplied source")
    if newline != file_object["newline"]:
        raise PatchEngineError("newline does not match the supplied source")


def _validate_final_newline(source_bytes, output_bytes):
    source_has_newline = source_bytes.endswith((b"\n", b"\r"))
    output_has_newline = output_bytes.endswith((b"\n", b"\r"))
    if source_has_newline != output_has_newline:
        raise PatchEngineError("An edit must explicitly preserve final-newline state")


def stage_patch(source_bytes, patch, encoded_artifact):
    """Stage one already-admitted Python file and return bytes plus byte proof.

    The function performs no I/O, import, execution, lint, or test of either the
    original or patched content. A rejection raises ``PatchEngineError`` and
    returns no staged output.
    """
    if not isinstance(source_bytes, bytes):
        raise PatchEngineError("Source must be bytes")
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise PatchEngineError("Original source exceeds 1 MiB")
    decoded = decode_patch_artifact(encoded_artifact)
    _validate_schema(decoded)
    if decoded != patch:
        raise PatchEngineError("Patch object must equal the decoded artifact")
    _validate_schema(patch)
    file_object = patch["files"][0]
    source_text, bom, newline = _detect_source_encoding(source_bytes)
    _validate_source_binding(file_object, source_bytes, source_text, bom, newline)
    try:
        tree = ast.parse(source_text)
    except (SyntaxError, ValueError) as exc:
        raise PatchEngineError("Original source must parse as Python") from exc
    prepared = _build_splices(source_text, file_object["edits"], tree)
    output_bytes, ranges = _apply_splices(source_bytes, prepared, newline)
    if len(output_bytes) > MAX_OUTPUT_BYTES:
        raise PatchEngineError("Output exceeds 1 MiB")
    try:
        output_text = output_bytes[3:].decode("utf-8", errors="strict") if bom else output_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PatchEngineError("Output must be valid UTF-8") from exc
    try:
        ast.parse(output_text)
    except (SyntaxError, ValueError) as exc:
        raise PatchEngineError("Patched output must parse as Python") from exc
    _validate_final_newline(source_bytes, output_bytes)
    original_outside = _outside_bytes(source_bytes, ranges, "original")
    output_outside = _outside_bytes(output_bytes, ranges, "output")
    outside_equal = original_outside == output_outside
    if not outside_equal:
        raise PatchEngineError("Outside-edit byte preservation proof failed")
    proof = {
        "original_sha256": _sha256(source_bytes),
        "output_sha256": _sha256(output_bytes),
        "original_bytes": len(source_bytes),
        "output_bytes": len(output_bytes),
        "edited_ranges": ranges,
        "original_outside_sha256": _sha256(original_outside),
        "output_outside_sha256": _sha256(output_outside),
        "outside_bytes_equal": outside_equal,
    }
    diff = _unified_diff(source_bytes, output_bytes, file_object["relative_path"])
    return PatchResult(output_bytes=output_bytes, unified_diff=diff, proof=proof)
