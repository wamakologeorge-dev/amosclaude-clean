import sys
import json
from cli.client import AmosClient
from cli.config import CLIConfig

client = AmosClient()

def handle_status(args):
    """Retrieve and display the current status of the Amosclaud platform and agents."""
    print(f"Connecting to Amosclaud API at: {CLIConfig.API_URL}")
    response = client.get_status()
    if response.get("error"):
        print(f"[-] Error: {response.get('message')}")
        sys.exit(1)
    
    print("\n[+] AMOSCLAUD SYSTEM STATUS")
    print("=" * 40)
    for key, value in response.items():
        print(f"{key.upper():<15}: {value}")
    print("=" * 40)

def handle_sync(args):
    """Trigger an autonomous cmood synchronization event."""
    print(f"[+] Triggering cmood sync for file: {args.file} [Action: {args.action}]")
    response = client.trigger_cmood_sync(args.file, args.action)
    if response.get("error"):
        print(f"[-] Sync failed: {response.get('message')}")
        sys.exit(1)
        
    print("[+] Sync initiated successfully.")
    print(json.dumps(response, indent=2))

def handle_jobs(args):
    """Fetch and display active and completed cmood cloud jobs."""
    print("[+] Fetching cmood cloud jobs...")
    response = client.get_jobs()
    if response.get("error"):
        print(f"[-] Failed to fetch jobs: {response.get('message')}")
        sys.exit(1)
        
    jobs = response.get("jobs", [])
    if not jobs:
        print("[*] No active or pending jobs found.")
        return

    print("\n[+] ACTIVE CMOOD CLOUD JOBS")
    print("=" * 80)
    print(f"{'JOB ID':<15} | {'FILE PATH':<25} | {'ACTION':<10} | {'STATUS':<10}")
    print("-" * 80)
    for job in jobs:
        print(f"{job.get('job_id', 'N/A'):<15} | {job.get('file_path', 'N/A')[:25]:<25} | {job.get('action', 'N/A'):<10} | {job.get('status', 'N/A'):<10}")
    print("=" * 80)
