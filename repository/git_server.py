import os
import re
import subprocess
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pathlib import Path

router = APIRouter(prefix="/git")

# Define base storage root path for multi-tenant users
REPOS_ROOT = Path("/var/www/amosclaud/repositories")

_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SAFE_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_REPO_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

def validate_path_segment(value: str, field_name: str) -> str:
    if not value or value in {".", ".."} or not _SAFE_PATH_SEGMENT_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}.")
    return value

def validate_username(username: str) -> str:
    candidate = validate_path_segment(username, "username")
    if not _SAFE_USERNAME_RE.fullmatch(candidate):
        raise HTTPException(status_code=400, detail="Invalid username.")
    return candidate

def validate_repo_name(repo_name: str) -> str:
    if not repo_name:
        raise HTTPException(status_code=400, detail="Invalid repository name.")

    base_name = repo_name[:-4] if repo_name.endswith(".git") else repo_name
    if not _SAFE_REPO_BASENAME_RE.fullmatch(base_name):
        raise HTTPException(status_code=400, detail="Invalid repository name.")

    return f"{base_name}.git"

def get_repo_absolute_path(username: str, repo_name: str) -> Path:
    """Helper to cleanly extract the bare repository file track path."""
    safe_username = validate_username(username)
    safe_repo_name = validate_repo_name(repo_name)

    base_root = REPOS_ROOT.resolve(strict=False)
    candidate_path = (base_root / safe_username / safe_repo_name).resolve(strict=False)

    base_root_str = str(base_root)
    candidate_path_str = str(candidate_path)
    if os.path.commonpath([base_root_str, candidate_path_str]) != base_root_str:
        raise HTTPException(status_code=400, detail="Invalid repository path.")

    return candidate_path

@router.get("/{username}/{repo_name}/info/refs")
async def git_info_refs(username: str, repo_name: str, service: str, request: Request):
    """
    Handles the initial Git handshake step. Maps to:
    git clone/push http://localhost:8100/git/{user}/{repo}/info/refs?service=git-upload-pack
    """
    if service not in ["git-upload-pack", "git-receive-pack"]:
        raise HTTPException(status_code=400, detail="Unsupported git service invocation token.")

    repo_path = get_repo_absolute_path(username, repo_name)
    
    # Auto-initialize a real bare repo if the user workspace hasn't provisioned it yet
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare"], cwd=repo_path, check=True)

    # Invoke Git backend service binary stream to scan references
    # Use validated repo_path as cwd and a constant repo argument to avoid passing user-derived paths in argv.
    cmd = ["git", service, "--stateless-rpc", "--advertise-refs", "."]
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, check=True)

    # Construct strict smart-http standard protocol headers
    service_banner = f"# service={service}\n".encode('utf-8')
    packet_prefix = f"{len(service_banner) + 4:04x}".encode('utf-8')
    flush_packet = b"0000"
    
    response_payload = packet_prefix + service_banner + flush_packet + result.stdout
    content_type = f"application/x-{service}-advertisement"

    return Response(content=response_payload, media_type=content_type)

@router.post("/{username}/{repo_name}/{service}")
async def git_service_rpc(username: str, repo_name: str, service: str, request: Request):
    """
    Handles data transmission payloads during real pushes, pulls, or clones.
    Maps directly to server-side git binary packfile unpacking pipelines.
    """
    if service not in ["git-upload-pack", "git-receive-pack"]:
        raise HTTPException(status_code=400, detail="Malformed RPC path instruction.")

    repo_path = get_repo_absolute_path(username, repo_name)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Target repository storage track not found.")

    # Read incoming binary payload from git client push/pull execution stream
    body_payload = await request.body()

    # Create a server-side subprocess connection directly to git data processors
    # Use validated repo_path as cwd and a constant repo argument to avoid passing user-derived paths in argv.
    process = subprocess.Popen(
        ["git", service, "--stateless-rpc", "."],
        cwd=repo_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    stdout_data, stderr_data = process.communicate(input=body_payload)

    if process.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Internal Git execution failure: {stderr_data.decode()}")

    content_type = f"application/x-{service}-result"
    return Response(content=stdout_data, media_type=content_type)

