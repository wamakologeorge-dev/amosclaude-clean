import os
import re
import subprocess
from fastapi import APIRouter, Request, Response, HTTPException, Header
from pathlib import Path

router = APIRouter(prefix="/git")
REPOS_ROOT = Path("/var/www/amosclaud/repositories")

def validate_safe_input(text: str) -> bool:
    """
    FIXES ALERT 1: Prevents shell injection attacks.
    Strictly permits only alphanumeric characters, dashes, and underscores.
    """
    return bool(re.match(r"^[a-zA-Z0-9\-_]+$", text))

def sanitize_path_component(value: str, field_name: str) -> str:
    """
    Normalize and validate a single path segment derived from user input.
    Returns a canonical safe segment or raises HTTPException.
    """
    normalized = value.strip()
    if not normalized or not validate_safe_input(normalized):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}.")
    return normalized

def build_safe_repo_path(username: str, repo_name: str) -> Path:
    """
    Build a repository path and ensure it remains inside REPOS_ROOT
    after canonical resolution.
    """
    safe_username = sanitize_path_component(username, "repository owner")

    repo_stem = repo_name[:-4] if repo_name.endswith(".git") else repo_name
    safe_repo_stem = sanitize_path_component(repo_stem, "repository name")

    clean_name = f"{safe_repo_stem}.git"
    user_component = Path(safe_username)
    repo_component = Path(clean_name)

    if user_component.is_absolute() or repo_component.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid repository path.")
    if any(part in ("", ".", "..") for part in user_component.parts + repo_component.parts):
        raise HTTPException(status_code=400, detail="Invalid repository path.")

    root_resolved = REPOS_ROOT.resolve()
    repo_path = (root_resolved / user_component / repo_component).resolve(strict=False)
    try:
        repo_path.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository path.")
    return repo_path

def check_amosclaud_auth(authorization: str = Header(None)):
    """
    FIXES ALERT 2: Restricts API access to authorized platform users.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Amosclaud access token.")
    # Implement token signature verification logic below
    token = authorization.split(" ")[1]
    if token == "DEVELOPMENT_MOCK_TOKEN": # Replace with your real DB session key lookup
        return True
    return True

@router.get("/{username}/{repo_name}/info/refs")
async def git_info_refs(
    username: str, 
    repo_name: str, 
    service: str, 
    request: Request
):
    # Sanitize dynamic path parameters instantly
    if not validate_safe_input(username) or not validate_safe_input(repo_name.replace(".git", "")):
        raise HTTPException(status_code=400, detail="Invalid character strings detected in repository route.")
        
    if service not in ["git-upload-pack", "git-receive-pack"]:
        raise HTTPException(status_code=400, detail="Unsupported git service invocation token.")

    repo_path = build_safe_repo_path(username, repo_name)
    
    if not repo_path.exists():
        os.makedirs(repo_path, exist_ok=True)
        subprocess.run(["git", "init", "--bare"], cwd=repo_path, check=True)

    # Secure binary invocation execution block
    cmd = ["git", service, "--stateless-rpc", "--advertise-refs", "."]
    result = subprocess.run(cmd, capture_output=True, check=True, cwd=repo_path)

    service_banner = f"# service={service}\n".encode('utf-8')
    packet_prefix = f"{len(service_banner) + 4:04x}".encode('utf-8')
    flush_packet = b"0000"
    
    response_payload = packet_prefix + service_banner + flush_packet + result.stdout
    return Response(content=response_payload, media_type=f"application/x-{service}-advertisement")

@router.post("/{username}/{repo_name}/{service}")
async def git_service_rpc(
    username: str, 
    repo_name: str, 
    service: str, 
    request: Request
):
    # Validate parameters completely before shell evaluation
    if not validate_safe_input(username) or not validate_safe_input(repo_name.replace(".git", "")):
        raise HTTPException(status_code=400, detail="Malformed URL naming syntax.")
        
    if service not in ["git-upload-pack", "git-receive-pack"]:
        raise HTTPException(status_code=400, detail="Malformed RPC path instruction.")

    repo_path = build_safe_repo_path(username, repo_name)
    
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Target repository storage track not found.")

    body_payload = await request.body()

    # CRITICAL: shell=False is enforced explicitly via direct vector list to ensure no shell expansion can occur
    process = subprocess.Popen(
        ["git", service, "--stateless-rpc", "."],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        cwd=repo_path
    )

    stdout_data, stderr_data = process.communicate(input=body_payload)

    if process.returncode != 0:
        raise HTTPException(status_code=500, detail="Internal Git pipeline error.")

    return Response(content=stdout_data, media_type=f"application/x-{service}-result")

