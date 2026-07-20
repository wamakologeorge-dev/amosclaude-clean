import os
import sys

# The agent's container environment will pass the secret here automatically
api_token = os.environ.get("AMOSCLOUD_API_TOKEN")

if not api_token:
    print("Error: AMOSCLOUD_API_TOKEN environment variable is missing!")
    sys.exit(1)

print("Token successfully retrieved securely. Proceeding with deployment...")

