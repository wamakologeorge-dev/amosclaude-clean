with open('src/amoscloud_ai/api/chat_api.py', 'r') as f:
    content = f.read()

# Remove default secret and fail explicitly
content = content.replace('repo = os.environ.get("GITHUB_REPOSITORY", "wamakologeorge-dev/amosclaude-clean")', 'repo = os.environ.get("GITHUB_REPOSITORY")')

# Replace fallback
content = content.replace('os.environ.get("WEBHOOK_SECRET", "default_secret")', 'os.environ.get("WEBHOOK_SECRET")')

# Replace webhook check
old_check = 'if os.environ.get("WEBHOOK_SECRET") and secret != os.environ.get("WEBHOOK_SECRET"):'
new_check = 'if not os.environ.get("WEBHOOK_SECRET") or secret != os.environ.get("WEBHOOK_SECRET"):'
content = content.replace(old_check, new_check)

with open('src/amoscloud_ai/api/chat_api.py', 'w') as f:
    f.write(content)
