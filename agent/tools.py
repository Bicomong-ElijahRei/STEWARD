import os
import shutil
import send2trash
import hashlib
import glob
import time
import uuid
import PyPDF2
from datetime import datetime
from utils.helpers import FILE_PREVIEW_LIMIT, truncate_file_preview

try:
    import docx  # python-docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

# ----- Basic tools (lightweight) -----
class ToolResult(str):
    """String-compatible tool result carrying verified mutation metadata."""
    def __new__(cls, value, **metadata):
        result = super().__new__(cls, value)
        result.metadata = metadata
        return result


class MutationOutcomeError(Exception):
    """Failure with an explicit filesystem outcome for journal handling."""

    def __init__(self, state, message, actual_destination=None):
        super().__init__(message)
        self.state = state
        self.actual_destination = actual_destination


def _remove_published_source(source, destination):
    """Remove a published source and roll back the destination on failure."""
    try:
        os.remove(source)
    except Exception as source_error:
        cleanup_error = None
        try:
            if os.path.lexists(destination):
                os.remove(destination)
        except Exception as exc:
            cleanup_error = exc

        source_exists = os.path.lexists(source)
        destination_exists = os.path.lexists(destination)
        if source_exists and not destination_exists:
            state = "failed"
            detail = str(source_error)
        else:
            state = "uncertain"
            detail = (
                f"{source_error}; destination rollback failed: {cleanup_error}"
                if cleanup_error is not None
                else f"{source_error}; destination rollback could not be verified"
            )
        raise MutationOutcomeError(
            state, detail, actual_destination=destination
        ) from source_error


def resolve_move_destination(source, destination):
    """Return the concrete final path used by move semantics."""
    destination = os.path.normpath(destination)
    if os.path.isdir(destination):
        return os.path.join(destination, os.path.basename(os.path.normpath(source)))
    return destination


def _same_effective_path(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def _publish_without_overwrite(source, destination):
    """Publish a regular file without replacing an existing destination."""
    if os.path.lexists(destination):
        raise FileExistsError(f"Destination already exists: '{destination}'")

    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    temporary = os.path.join(
        parent, f".steward-move-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        try:
            with open(temporary, "rb") as handle:
                os.fsync(handle.fileno())
        except (AttributeError, OSError):
            pass
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise
        except (AttributeError, OSError):
            # O_EXCL reserves the name; copying through that handle cannot
            # replace a destination that appeared after reservation.
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            try:
                with open(source, "rb") as source_handle:
                    with os.fdopen(fd, "wb") as destination_handle:
                        shutil.copyfileobj(source_handle, destination_handle)
            except Exception:
                try:
                    os.remove(destination)
                except OSError:
                    pass
                raise
        os.remove(temporary)
        return destination
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def _move_without_overwrite(source, destination):
    """Move one regular file while refusing every occupied final destination."""
    source = os.path.normpath(source)
    destination = os.path.normpath(destination)
    if not os.path.isfile(source):
        raise ValueError(f"Source is not a regular file: '{source}'")
    final_destination = resolve_move_destination(source, destination)
    if _same_effective_path(source, final_destination):
        raise FileExistsError(f"Source and destination are the same path: '{source}'")
    _publish_without_overwrite(source, final_destination)
    _remove_published_source(source, final_destination)
    return final_destination


def move_file(source, destination):
    try:
        source = os.path.normpath(source)
        destination = os.path.normpath(destination)
        actual_destination = _move_without_overwrite(source, destination)
        return ToolResult(
            f"Moved '{source}' → '{actual_destination}'",
            actual_destination=actual_destination,
        )
    except MutationOutcomeError as exc:
        return ToolResult(
            f"Error: {exc}",
            mutation_state=exc.state,
            actual_destination=exc.actual_destination or destination,
        )
    except Exception as e:
        return f"Error: {e}"

def delete_file(path):
    try:
        path = os.path.normpath(path)
        send2trash.send2trash(path)
        return f"Deleted '{path}' (recycle bin)"
    except Exception as e:
        return f"Error: {e}"

def rename_file(old_path, new_name):
    try:
        old_path = os.path.normpath(old_path)
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        new_path = os.path.normpath(new_path)
        if _same_effective_path(old_path, new_path):
            return ToolResult(
                f"No-op rename: '{old_path}' already has that name",
                actual_destination=new_path,
                no_op=True,
            )
        if os.path.lexists(new_path):
            raise FileExistsError(f"Destination already exists: '{new_path}'")
        _publish_without_overwrite(old_path, new_path)
        _remove_published_source(old_path, new_path)
        return ToolResult(
            f"Renamed '{old_path}' → '{new_path}'",
            actual_destination=new_path,
        )
    except MutationOutcomeError as exc:
        return ToolResult(
            f"Error: {exc}",
            mutation_state=exc.state,
            actual_destination=exc.actual_destination or new_path,
        )
    except Exception as e:
        return f"Error: {e}"

def create_folder(path):
    created_paths = []
    try:
        path = os.path.normpath(path)
        if os.path.exists(path):
            if not os.path.isdir(path):
                raise FileExistsError(f"Path exists and is not a folder: '{path}'")
            return ToolResult(
                f"Folder already exists: '{path}'",
                created_paths=[],
                no_op=True,
            )

        # os.mkdir is atomic, so only components actually created by this
        # invocation are attributed to STEWARD.
        absolute = os.path.abspath(path)
        missing = []
        cursor = absolute
        while not os.path.exists(cursor):
            missing.append(cursor)
            parent = os.path.dirname(cursor)
            if parent == cursor:
                break
            cursor = parent
        for directory in reversed(missing):
            try:
                os.mkdir(directory)
                created_paths.append(directory)
            except FileExistsError:
                if not os.path.isdir(directory):
                    raise
        return ToolResult(
            f"Created folder '{path}'",
            created_paths=created_paths,
        )
    except Exception as e:
        return ToolResult(
            f"Error: {e}",
            mutation_state="uncertain" if created_paths else "failed",
            created_paths=created_paths,
        )

def list_directory(directory):
    try:
        directory = os.path.normpath(directory)
        items = os.listdir(directory)
        files = [f for f in items if os.path.isfile(os.path.join(directory, f))]
        dirs = [d + "/" for d in items if os.path.isdir(os.path.join(directory, d))]
        result = "Directories:\n" + "\n".join(dirs) + "\n\nFiles:\n" + "\n".join(files)
        return result if result.strip() else "Empty"
    except Exception as e:
        return f"Error: {e}"

def read_file_content(file_path):
    file_path = os.path.normpath(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return truncate_file_preview(f.read(FILE_PREVIEW_LIMIT + 1))
        elif ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages[:3]:
                    text += page.extract_text() or ''
                return truncate_file_preview(text)
        elif ext == '.docx':
            if docx is None:
                return "python-docx not installed. Install with: pip install python-docx"
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return truncate_file_preview("\n".join(paragraphs))
        elif ext == '.xlsx':
            if openpyxl is None:
                return "openpyxl not installed. Install with: pip install openpyxl"
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            result = []
            for sheet_name in wb.sheetnames[:3]:
                ws = wb[sheet_name]
                result.append(f"--- Sheet: {sheet_name} ---")
                for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                    values = [str(v) for v in row if v is not None]
                    if values:
                        result.append(" | ".join(values))
            return truncate_file_preview("\n".join(result))
        else:
            return "[Content extraction not supported]"
    except Exception as e:
        return f"Error reading file: {e}"

def get_file_info(file_path):
    try:
        file_path = os.path.normpath(file_path)
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        return f"Size: {size} bytes, Modified: {mtime}"
    except Exception as e:
        return f"Error: {e}"

# ----- Phase 4 heavy tools (with progress callback & safe file access) -----
REPORT_MAX_FILES_VISITED = 1000
REPORT_MAX_DIRECTORY_DEPTH = 8
REPORT_MAX_RESULT_ENTRIES = 50
REPORT_MAX_SERIALIZED_BYTES = 32768
REPORT_MAX_DIRECTORY_PATH_LENGTH = 1024
REPORT_MAX_SIZE_MB = 10240
REPORT_MAX_AGE_DAYS = 3650


def _is_link_or_junction(path):
    """Recognize symbolic links and Windows junctions without a new dependency."""
    is_junction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or (is_junction is not None and is_junction(path))


def _collect_report_files(directory, progress_callback=None):
    """Return a deterministic, bounded inventory of regular files below a root."""
    canonical_root = os.path.realpath(os.path.abspath(directory))
    files = []
    for root, directories, filenames in os.walk(
        canonical_root, topdown=True, followlinks=False
    ):
        directories.sort()
        filenames.sort()
        relative = os.path.relpath(root, canonical_root)
        depth = 0 if relative == "." else len(relative.split(os.sep))
        if depth == REPORT_MAX_DIRECTORY_DEPTH and directories:
            return [], (
                "Error: Report traversal bound exceeded: maximum directory depth is "
                f"{REPORT_MAX_DIRECTORY_DEPTH}."
            )

        safe_directories = []
        for name in directories:
            path = os.path.join(root, name)
            if _is_link_or_junction(path):
                continue
            resolved = os.path.realpath(os.path.abspath(path))
            try:
                inside = os.path.commonpath((resolved, canonical_root)) == canonical_root
            except ValueError:
                inside = False
            if inside:
                safe_directories.append(name)
        directories[:] = safe_directories

        for name in filenames:
            path = os.path.join(root, name)
            if _is_link_or_junction(path):
                continue
            resolved = os.path.realpath(os.path.abspath(path))
            try:
                inside = os.path.commonpath((resolved, canonical_root)) == canonical_root
            except ValueError:
                inside = False
            if not inside or not os.path.isfile(resolved):
                continue
            if len(files) >= REPORT_MAX_FILES_VISITED:
                return [], (
                    "Error: Report traversal bound exceeded: maximum files visited is "
                    f"{REPORT_MAX_FILES_VISITED}."
                )
            files.append(resolved)
            if progress_callback:
                progress_callback(len(files), REPORT_MAX_FILES_VISITED, resolved)
    return files, None


def bounded_report_output(text, max_bytes=None):
    """Bound a report's serialized bytes while retaining a truncation marker."""
    if max_bytes is None:
        max_bytes = REPORT_MAX_SERIALIZED_BYTES
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    marker = "\n[serialized output truncated]"
    marker_bytes = marker.encode("utf-8")
    if max_bytes <= len(marker_bytes):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[:max_bytes - len(marker_bytes)].decode("utf-8", errors="ignore")
    return prefix + marker


def _limit_result_lines(lines):
    """Apply the result-entry bound and report deterministic omissions."""
    if len(lines) <= REPORT_MAX_RESULT_ENTRIES:
        return lines, 0
    omitted = len(lines) - REPORT_MAX_RESULT_ENTRIES
    return lines[:REPORT_MAX_RESULT_ENTRIES], omitted


def find_duplicates(directory, progress_callback=None):
    """Return a deterministic, bounded report of duplicate files."""
    try:
        all_files, traversal_error = _collect_report_files(
            directory, progress_callback
        )
        if traversal_error:
            return traversal_error
        if not all_files:
            return bounded_report_output("No files found.")

        hash_map = {}
        duplicate_pairs = []
        skipped = 0
        for filepath in all_files:
            try:
                file_hash = hashlib.sha256()
                with open(filepath, "rb") as handle:
                    for chunk in iter(lambda: handle.read(8192), b""):
                        file_hash.update(chunk)
                digest = file_hash.hexdigest()
            except (OSError, PermissionError, IOError):
                skipped += 1
                continue
            if digest in hash_map:
                duplicate_pairs.append((filepath, hash_map[digest]))
            else:
                hash_map[digest] = filepath

        if not duplicate_pairs:
            message = "No duplicate files found."
            if skipped:
                message += f" Skipped {skipped} inaccessible file(s)."
            return bounded_report_output(message)

        lines = [f"  {duplicate}  (duplicate of {original})"
                 for duplicate, original in duplicate_pairs]
        lines, omitted = _limit_result_lines(lines)
        report = "Duplicate pairs:\n" + "\n".join(lines)
        if omitted:
            report += f"\n  [result entries truncated: {omitted} omitted]"
        if skipped:
            report += f"\nSkipped {skipped} inaccessible file(s)."
        return bounded_report_output(report)
    except Exception as exc:
        return bounded_report_output(f"Error: {exc}")

def cleanup_empty_folders(directory, progress_callback=None):
    directory = os.path.normpath(directory)
    try:
        all_dirs = []
        for root, dirs, files in os.walk(directory, topdown=False):
            for dir_name in dirs:
                all_dirs.append(os.path.join(root, dir_name))
        total = len(all_dirs)
        count = 0
        for i, dir_path in enumerate(all_dirs):
            if progress_callback:
                progress_callback(i + 1, total, dir_path)
            try:
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    count += 1
            except OSError:
                pass
        return f"Removed {count} empty folder(s)."
    except Exception as e:
        return f"Error: {e}"

def cleanup_temp_files(directory, progress_callback=None):
    temp_extensions = ('.tmp', '.temp', '.cache', '.log', '.bak', '.swp', 'thumbs.db', 'desktop.ini')
    directory = os.path.normpath(directory)
    all_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(temp_extensions) or file.lower() in ('thumbs.db', 'desktop.ini'):
                all_files.append(os.path.join(root, file))
    total = len(all_files)
    removed = []
    for i, filepath in enumerate(all_files):
        if progress_callback:
            progress_callback(i + 1, total, filepath)
        try:
            os.remove(filepath)
            removed.append(filepath)
        except (OSError, PermissionError):
            pass
    result = f"Removed {len(removed)} temporary file(s).\n" + "\n".join(removed[:20])
    if len(removed) > 20:
        result += "\n..."
    return result

def find_large_files(directory, size_mb, progress_callback=None):
    """Return a deterministic, bounded report of files above a size threshold."""
    try:
        all_files, traversal_error = _collect_report_files(
            directory, progress_callback
        )
        if traversal_error:
            return traversal_error
        size_bytes = size_mb * 1024 * 1024
        large_files = []
        skipped = 0
        for filepath in all_files:
            try:
                size = os.path.getsize(filepath)
                if size > size_bytes:
                    large_files.append((filepath, size))
            except (OSError, PermissionError):
                skipped += 1
        large_files.sort(key=lambda item: (-item[1], item[0]))
        if not large_files:
            message = f"No files larger than {size_mb} MB found."
            if skipped:
                message += f" Skipped {skipped} inaccessible file(s)."
            return bounded_report_output(message)

        lines = [f"  {path} ({size // (1024 * 1024)} MB)"
                 for path, size in large_files]
        lines, omitted = _limit_result_lines(lines)
        report = f"Files larger than {size_mb} MB:\n" + "\n".join(lines)
        if omitted:
            report += f"\n  [result entries truncated: {omitted} omitted]"
        if skipped:
            report += f"\nSkipped {skipped} inaccessible file(s)."
        return bounded_report_output(report)
    except Exception as exc:
        return bounded_report_output(f"Error: {exc}")

def batch_move(source_pattern, destination_folder, progress_callback=None):
    try:
        source_pattern = os.path.normpath(source_pattern)
        destination_folder = os.path.normpath(destination_folder)
        files = glob.glob(source_pattern, recursive=True)
        if not files:
            return f"No files matching pattern '{source_pattern}' found."
        os.makedirs(destination_folder, exist_ok=True)
        total = len(files)
        moved = []
        for i, src in enumerate(files):
            if progress_callback:
                progress_callback(i + 1, total, src)
            dest = os.path.join(destination_folder, os.path.basename(src))
            try:
                shutil.move(src, dest)
                moved.append(src)
            except (OSError, PermissionError, shutil.Error) as e:
                print(f"[WARN] Could not move {src}: {e}")
        return f"Moved {len(moved)} file(s) to {destination_folder}:\n" + "\n".join(moved[:20]) + ("\n..." if len(moved)>20 else "")
    except Exception as e:
        return f"Error: {e}"

def suggest_deletions(directory, size_mb_threshold=100, age_days_threshold=30, use_ai=False):
    """Return bounded, advisory-only deletion recommendations.

    The report never deletes files and is not an approved execution plan. The
    ``use_ai`` compatibility argument is intentionally ignored: exposing an
    unbounded external model response would violate the report's size budget.
    """
    try:
        all_files, traversal_error = _collect_report_files(directory)
        if traversal_error:
            return traversal_error
        age_cutoff = time.time() - (age_days_threshold * 86400)
        size_bytes = size_mb_threshold * 1024 * 1024
        candidates = []
        for filepath in all_files:
            try:
                stat = os.stat(filepath)
                if stat.st_size > size_bytes or stat.st_mtime < age_cutoff:
                    candidates.append((filepath, stat.st_size, stat.st_mtime))
            except (OSError, PermissionError):
                continue
        candidates.sort(key=lambda item: (-item[1], item[0]))
        report = (
            "RECOMMENDATIONS ONLY - NOT AN APPROVED PLAN\n"
            f"Deletion suggestions for '{directory}':\n"
            f"Heuristics: files >{size_mb_threshold} MB or older than "
            f"{age_days_threshold} days.\n"
            "No files will be deleted or scheduled by this report.\n"
        )
        if not candidates:
            report += "No files found for deletion suggestions."
            return bounded_report_output(report)

        lines = []
        for path, size, mtime in candidates:
            modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            lines.append(f"  {path} ({size // (1024 * 1024)} MB, modified {modified})")
        lines, omitted = _limit_result_lines(lines)
        report += "Top candidates (by size):\n" + "\n".join(lines)
        if omitted:
            report += f"\n  [result entries truncated: {omitted} omitted]"
        report += "\nReview manually before any separately approved deletion."
        return bounded_report_output(report)
    except Exception as exc:
        return bounded_report_output(f"Error: {exc}")

# Dictionary of all tool functions
tool_functions = {
    "move_file": move_file,
    "delete_file": delete_file,
    "rename_file": rename_file,
    "create_folder": create_folder,
    "list_directory": list_directory,
    "read_file_content": read_file_content,
    "get_file_info": get_file_info,
    "find_duplicates": find_duplicates,
    "cleanup_empty_folders": cleanup_empty_folders,
    "cleanup_temp_files": cleanup_temp_files,
    "find_large_files": find_large_files,
    "batch_move": batch_move,
    "suggest_deletions": suggest_deletions,
}