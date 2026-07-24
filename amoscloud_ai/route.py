# ai/route.py
import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/workspace", tags=["Workspace Automation"])

# Resolve the workspace root directory (where the server is running)
WORKSPACE_ROOT = Path(os.getcwd()).resolve()

# --- Request & Response Schemas ---

class FileReadResponse(BaseModel):
    path: str
    content: str
    size: int
    encoding: str = "utf-8"

class FileWriteRequest(BaseModel):
    path: str = Field(..., description="Relative path to the file inside the workspace")
    content: str = Field(..., description="Full text content to write to the file")

class FilePatchRequest(BaseModel):
    path: str = Field(..., description="Relative path to the file inside the workspace")
    search_string: str = Field(..., description="The exact block of code to find")
    replace_string: str = Field(..., description="The block of code to replace it with")

class FileDeleteRequest(BaseModel):
    path: str = Field(..., description="Relative path to the file to delete")

class CommandExecuteRequest(BaseModel):
    command: str = Field(..., description="The terminal command to run (e.g., 'pytest', 'python script.py')")
    timeout: int = Field(30, description="Command execution timeout in seconds")

class CommandExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    success: bool

class FileListResponse(BaseModel):
    root: str
    files: List[str]

# --- Helper Security Functions ---

def safe_resolve_path(relative_path: str) -> Path:
    """
    Resolves a relative path against the workspace root and strictly prevents
    directory traversal attacks by ensuring the path stays within the root.
    """
    # Clean up leading slashes or backslashes to treat it as relative
    clean_rel_path = relative_path.lstrip("/")
    target_path = Path(WORKSPACE_ROOT / clean_rel_path).resolve()
    
    # Check if the resolved path is inside the workspace root
    if not str(target_path).startswith(str(WORKSPACE_ROOT)):
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Path '{relative_path}' escapes the workspace root."
        )
    return target_path

# --- API Endpoints ---

@router.get("/list", response_model=FileListResponse)
async def list_files(exclude_ignored: bool = True):
    """
    Recursively lists all files in the workspace so the AI can map out the codebase.
    """
    try:
        file_list = []
        ignored_dirs = {
            ".git", ".github", "__pycache__", "node_modules", 
            ".venv", "venv", "env", ".pytest_cache", ".idea", ".vscode"
        }
        ignored_files = {".DS_Store", "thumbs.db"}

        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            # Modify dirs in-place to skip ignored directories recursively
            if exclude_ignored:
                dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith('.')]

            for file in files:
                if exclude_ignored and (file in ignored_files or file.endswith('.pyc')):
                    continue
                
                full_path = Path(root) / file
                relative_path = full_path.relative_to(WORKSPACE_ROOT)
                file_list.append(str(relative_path))

        return FileListResponse(
            root=str(WORKSPACE_ROOT),
            files=sorted(file_list)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list workspace files: {str(e)}")


@router.get("/read", response_model=FileReadResponse)
async def read_file(path: str = Query(..., description="Relative path to the file inside workspace")):
    """
    Reads the content of a file so the AI can analyze its structure and logic.
    """
    target_path = safe_resolve_path(path)

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not target_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is a directory, not a file: {path}")

    try:
        content = target_path.read_text(encoding="utf-8")
        return FileReadResponse(
            path=path,
            content=content,
            size=len(content)
        )
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, 
            detail="Binary file detected. Only text-based files (UTF-8) are supported."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@router.post("/write")
async def write_file(payload: FileWriteRequest):
    """
    Writes or completely overwrites a file with new content. 
    Creates parent directories automatically if they do not exist.
    """
    target_path = safe_resolve_path(payload.path)

    try:
        # Create parent directories if they don't exist
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        target_path.write_text(payload.content, encoding="utf-8")
        return {
            "status": "success", 
            "path": payload.path, 
            "message": "File written successfully."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {str(e)}")


@router.post("/patch")
async def patch_file(payload: FilePatchRequest):
    """
    Surgically replaces a specific block of code in a file. 
    This is highly optimized for AI editing to prevent rewriting large files.
    """
    target_path = safe_resolve_path(payload.path)

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {payload.path}")

    try:
        content = target_path.read_text(encoding="utf-8")

        if payload.search_string not in content:
            raise HTTPException(
                status_code=400,
                detail="The search string was not found in the file. Patch failed."
            )

        # Perform the replacement (only replace the first occurrence to be precise)
        updated_content = content.replace(payload.search_string, payload.replace_string, 1)

        # Write back to disk
        target_path.write_text(updated_content, encoding="utf-8")
        return {
            "status": "success", 
            "path": payload.path, 
            "message": "File patched successfully."
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to patch file: {str(e)}")


@router.post("/delete")
async def delete_file(payload: FileDeleteRequest):
    """
    Deletes a file from the workspace.
    """
    target_path = safe_resolve_path(payload.path)

    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {payload.path}")
    if not target_path.is_file():
        raise HTTPException(status_code=400, detail="Path is a directory. Use directory endpoints to delete folders.")

    try:
        target_path.unlink()
        return {
            "status": "success", 
            "path": payload.path, 
            "message": "File deleted successfully."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.post("/execute", response_model=CommandExecuteResponse)
async def execute_command(payload: CommandExecuteRequest):
    """
    Executes a terminal command in the workspace root. 
    Allows the AI to run tests, check syntax, or build assets autonomously.
    """
    # List of allowed base commands for safety
    allowed_commands = {"python", "pytest", "pip", "npm", "git", "node", "ls", "pwd"}
    
    # Extract the base command
    base_cmd = payload.command.strip().split()[0] if payload.command.strip() else ""
    
    if base_cmd not in allowed_commands:
        raise HTTPException(
            status_code=400,
            detail=f"Command '{base_cmd}' is not allowed. Allowed commands: {list(allowed_commands)}"
        )

    try:
        # Run the command in the workspace root directory
        process = subprocess.run(
            payload.command,
            shell=True,
            cwd=WORKSPACE_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=payload.timeout
        )

        return CommandExecuteResponse(
            stdout=process.stdout,
            stderr=process.stderr,
            exit_code=process.returncode,
            success=(process.returncode == 0)
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=408, 
            detail=f"Command execution timed out after {payload.timeout} seconds."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute command: {str(e)}")
