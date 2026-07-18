with open('src/amoscloud_ai/main.py', 'r') as f:
    content = f.read()

# We just take the top part before FastAPI stuff
idx = content.find('Amoscloud AI – FastAPI web application entry point.')
if idx != -1:
    content = content[:idx].strip() + '\n'

with open('src/amoscloud_ai/main.py', 'w') as f:
    f.write(content)
