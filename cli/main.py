#!/usr/bin/env python3
import argparse
import sys
from cli.commands import handle_status, handle_sync, handle_jobs

def main():
    parser = argparse.ArgumentParser(
        description="Amosclaud Autonomous Command Line Interface (CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands to execute")

    # Status command
    subparsers.add_parser("status", help="Get operational status of the platform and agents")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Trigger an autonomous cmood sync event")
    sync_parser.add_argument("-f", "--file", required=True, help="Path of the file to scan/clone")
    sync_parser.add_argument("-a", "--action", choices=["CREATED", "MODIFIED", "MANUAL_SYNC"], default="MANUAL_SYNC", help="Sync trigger action type")

    # Jobs command
    subparsers.add_parser("jobs", help="Retrieve active and completed cmood cloud replication jobs")

    args = parser.parse_args()

    try:
        if args.command == "status":
            handle_status(args)
        elif args.command == "sync":
            handle_sync(args)
        elif args.command == "jobs":
            handle_jobs(args)
    except KeyboardInterrupt:
        print("\n[-] Operation cancelled by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
