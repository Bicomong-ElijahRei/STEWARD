import os
import shutil
import send2trash
import ollama
import json
from datetime import datetime

# ----- Tool implementations -----
def move_file(source, destination):
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.move(source, destination)
        return f"Moved '{source}' → '{destination}'"
    except Exception as e:
        return f"Error: {e}"

def delete_file(path):
    try:
        send2trash.send2trash(path)
        return f"Deleted '{path}' (recycle bin)"
    except Exception as e:
        return f"Error: {e}"

def rename_file(old_path, new_name):
    try:
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        os.rename(old_path, new_path)
        return f"Renamed '{old_path}' → '{new_path}'"
    except Exception as e:
        return f"Error: {e}"

def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Created folder '{path}'"
    except Exception as e:
        return f"Error: {e}"

def list_directory(directory):
    try:
        items = os.listdir(directory)
        files = [f for f in items if os.path.isfile(os.path.join(directory, f))]
        dirs = [d + "/" for d in items if os.path.isdir(os.path.join(directory, d))]
        result = "Directories:\n" + "\n".join(dirs) + "\n\nFiles:\n" + "\n".join(files)
        return result if result.strip() else "Empty"
    except Exception as e:
        return f"Error: {e}"

def read_file_content(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(2000)
        elif ext == '.pdf':
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = ''
                for page in reader.pages[:3]:
                    text += page.extract_text() or ''
                return text[:2000]
        else:
            return "[Content extraction not supported]"
    except Exception as e:
        return f"Error: {e}"

def get_file_info(file_path):
    try:
        stat = os.stat(file_path)
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        return f"Size: {size} bytes, Modified: {mtime}"
    except Exception as e:
        return f"Error: {e}"

def undo_last():
    # Stub – implement later if needed (could read a log file)
    return "Undo operation called. (Full implementation to be added)"

# ----- Tool schemas -----
tools = [
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move a file from source to destination",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"}
                },
                "required": ["source", "destination"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file (send to recycle bin)",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": "Rename a file within the same directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string"},
                    "new_name": {"type": "string"}
                },
                "required": ["old_path", "new_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Create a new folder (and parent directories)",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories (non‑recursive)",
            "parameters": {
                "type": "object",
                "properties": {"directory": {"type": "string"}},
                "required": ["directory"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_content",
            "description": "Read content of a text or PDF file (first 2000 chars)",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "Get file size and modification time",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last",
            "description": "Undo the most recent file operation",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

tool_functions = {
    "move_file": move_file,
    "delete_file": delete_file,
    "rename_file": rename_file,
    "create_folder": create_folder,
    "list_directory": list_directory,
    "read_file_content": read_file_content,
    "get_file_info": get_file_info,
    "undo_last": undo_last,
}

def run_agent():
    print("STEWARD Agent (type 'exit' to quit)\n")
    messages = []
    cwd = os.getcwd()
    system_prompt = f"""
You are STEWARD, an AI file manager for the project at: {cwd}

Workspace:
- Incoming: {cwd}\\Incoming
- Sorted:   {cwd}\\Sorted

When asked to organise a file:
1. Use `read_file_content` to understand content.
2. Decide a category (e.g., "Finance", "School", "Other").
3. Create a subfolder inside `{cwd}\\Sorted` with that name.
4. Move the file there.

Always ask for confirmation before destructive actions.
Never create folders outside `{cwd}\\Sorted` unless the user gives an absolute path.
To discover what exists, use `list_directory`.
"""
    messages.append({"role": "system", "content": system_prompt})

    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})

        response = ollama.chat(model="qwen2.5:7b", messages=messages, tools=tools, stream=False)
        assistant_msg = response['message']
        messages.append(assistant_msg)

        if 'tool_calls' in assistant_msg and assistant_msg['tool_calls']:
            for tool_call in assistant_msg['tool_calls']:
                func_name = tool_call['function']['name']
                args = tool_call['function']['arguments']
                print(f"\n[Tool Call] {func_name}({args})")
                print("Preview: The AI wants to execute the above operation.")
                confirm = input("Confirm? (yes/no): ").strip().lower()
                if confirm not in ("yes", "y"):
                    print("Action cancelled.")
                    messages.append({
                        "role": "tool",
                        "content": f"User cancelled '{func_name}'.",
                        "tool_call_id": tool_call.get('id', 'unknown')
                    })
                    continue

                if func_name in tool_functions:
                    result = tool_functions[func_name](**args)
                else:
                    result = f"Unknown tool '{func_name}'"
                print(f"Result: {result}")
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tool_call.get('id', 'unknown')
                })

            final = ollama.chat(model="qwen2.5:7b", messages=messages, stream=False)
            final_msg = final['message']['content']
            print(f"\nSTEWARD: {final_msg}")
            messages.append(final['message'])
        else:
            print(f"\nSTEWARD: {assistant_msg['content']}")

if __name__ == "__main__":
    run_agent()