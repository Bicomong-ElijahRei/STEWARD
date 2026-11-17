import os
import shutil
import send2trash
import hashlib
import glob
import PyPDF2
from datetime import datetime

try:
    import docx  # python-docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

# ----- Basic tools (lightweight) -----
def move_file(source, destination):
    try:
        source = os.path.normpath(source)
        destination = os.path.normpath(destination)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.move(source, destination)
        return f"Moved '{source}' → '{destination}'"
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
        os.rename(old_path, new_path)
        return f"Renamed '{old_path}' → '{new_path}'"
    except Exception as e:
        return f"Error: {e}"

def create_folder(path):
    try:
        path = os.path.normpath(path)
        os.makedirs(path, exist_ok=True)
        return f"Created folder '{path}'"
    except Exception as e:
        return f"Error: {e}"

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
                return f.read(2000)
        elif ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages[:3]:
                    text += page.extract_text() or ''
                return text[:2000]
        elif ext == '.docx':
            if docx is None:
                return "python-docx not installed. Install with: pip install python-docx"
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)[:2000]
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
            return "\n".join(result)[:2000]
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
def find_duplicates(directory, progress_callback=None):
    directory = os.path.normpath(directory)
    try:
        all_files = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                filepath = os.path.join(root, file)
                if os.path.isfile(filepath):
                    all_files.append(filepath)
        total = len(all_files)
        if total == 0:
            return "No files found."

        hash_map = {}
        duplicates = []
        skipped = 0
        for i, filepath in enumerate(all_files):
            if progress_callback:
                progress_callback(i + 1, total, filepath)
            try:
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
            except (OSError, PermissionError, IOError) as e:
                print(f"[WARN] Skipping {filepath}: {e}")
                skipped += 1
                continue
            if file_hash in hash_map:
                duplicates.append((filepath, hash_map[file_hash]))
            else:
                hash_map[file_hash] = filepath

        if skipped > 0:
            print(f"[INFO] Skipped {skipped} inaccessible file(s).")

        if duplicates:
            result = "Duplicate pairs:\n"
            for dup, orig in duplicates:
                result += f"  {dup}  (duplicate of {orig})\n"
            return result
        else:
            return "No duplicate files found."
    except Exception as e:
        return f"Error: {e}"

def cleanup_empty_folders(directory, progress_callback=None):
    directory = os.path.normpath(directory)
    try:
        all_dirs = []
        for root, dirs, files in os.walk(directory):
            for dir_name in dirs:
                all_dirs.append(os.path.join(root, dir_name))
        total = len(all_dirs)
        count = 0
        for i, dir_path in enumerate(all_dirs):
            if progress_callback:
                progress_callback(i + 1, total, dir_path)
            try:
                if not os.listdir(dir_path):
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
    directory = os.path.normpath(directory)
    size_bytes = size_mb * 1024 * 1024
    all_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            all_files.append(os.path.join(root, file))
    total = len(all_files)
    large_files = []
    skipped = 0
    for i, filepath in enumerate(all_files):
        if progress_callback:
            progress_callback(i + 1, total, filepath)
        try:
            if os.path.getsize(filepath) > size_bytes:
                large_files.append((filepath, os.path.getsize(filepath)))
        except (OSError, PermissionError):
            skipped += 1
            continue
    if skipped > 0:
        print(f"[INFO] Skipped {skipped} inaccessible file(s) in find_large_files")
    large_files.sort(key=lambda x: x[1], reverse=True)
    if not large_files:
        return f"No files larger than {size_mb} MB found."
    result = f"Files larger than {size_mb} MB:\n"
    for path, size in large_files[:50]:
        result += f"  {path} ({size//(1024*1024)} MB)\n"
    if len(large_files) > 50:
        result += f"  ... and {len(large_files)-50} more\n"
    return result

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

def suggest_deletions(directory, size_mb_threshold=100, age_days_threshold=30, use_ai=True):
    """
    Suggest files for deletion based on size, age, duplicates (heuristics) and optionally AI.
    Returns a report with recommendations.
    """
    import time
    from datetime import datetime, timedelta
    directory = os.path.normpath(directory)
    now = time.time()
    age_cutoff = now - (age_days_threshold * 86400)
    size_bytes = size_mb_threshold * 1024 * 1024
    candidates = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            filepath = os.path.join(root, file)
            try:
                stat = os.stat(filepath)
                size = stat.st_size
                mtime = stat.st_mtime
                if size > size_bytes or mtime < age_cutoff:
                    candidates.append((filepath, size, mtime))
            except (OSError, PermissionError):
                continue
    candidates.sort(key=lambda x: x[1], reverse=True)
    candidates = candidates[:50]  # limit to avoid overwhelming
    if not candidates:
        return "No files found for deletion suggestions."

    # Build report with heuristics
    from datetime import datetime
    report = f"Deletion suggestions for '{directory}':\nHeuristics: files >{size_mb_threshold} MB or older than {age_days_threshold} days.\n"
    report += "Top candidates (by size):\n"
    for path, size, mtime in candidates[:20]:
        size_mb = size // (1024*1024)
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        report += f"  {path} ({size_mb} MB, modified {mtime_str})\n"

    if use_ai:
        # Use AI to recommend deletions via LiteLLM
        try:
            from core.litellm_client import LiteLLMClient
            client = LiteLLMClient()
            prompt = "Here are files with large size or old age. Suggest which ones to delete, with reasons. List files by full path.\n\n"
            for path, size, mtime in candidates:
                size_mb = size // (1024*1024)
                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                prompt += f"- {path} (Size: {size_mb} MB, Modified: {mtime_str})\n"
            prompt += "\nReply with a bullet list of files to delete and a short reason for each. Only recommend deletion if it's safe (e.g., duplicates, old large files, temporary files)."
            response = client.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )
            ai_suggestions = response["choices"][0]["message"]["content"]
            report += f"\n--- AI Recommendations ---\n{ai_suggestions}\n"
        except Exception as e:
            report += f"\n--- AI Failed ---\nError: {e}\n"
    else:
        report += "\nNo AI used. Consider manual deletion of large/old files."
    return report

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