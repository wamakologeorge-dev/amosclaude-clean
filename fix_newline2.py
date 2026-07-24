with open('src/amoscloud_ai/api/chat_api.py', 'r') as f:
    lines = f.readlines()

with open('src/amoscloud_ai/api/chat_api.py', 'w') as f:
    for line in lines:
        if 'run["logs"] += logs +' in line:
            f.write('                    run["logs"] += logs + "\\n"\n')
        else:
            f.write(line)
