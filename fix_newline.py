with open('src/amoscloud_ai/api/chat_api.py', 'r') as f:
    content = f.read()

content = content.replace('run["logs"] += logs + "\n                break"', 'run["logs"] += logs + "\\n"\n                break')

with open('src/amoscloud_ai/api/chat_api.py', 'w') as f:
    f.write(content)
