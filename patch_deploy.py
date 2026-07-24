with open('.github/workflows/deploy.yml', 'r') as f:
    content = f.read()

content = content.replace("jobs:\n  deploy:", "permissions:\n  contents: read\n\njobs:\n  deploy:")

with open('.github/workflows/deploy.yml', 'w') as f:
    f.write(content)
