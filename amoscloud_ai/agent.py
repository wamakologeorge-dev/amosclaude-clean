# agent.py
import requests
import subprocess

class Agent:
    def __init__(self, base_url):
        self.base_url = base_url

    def run_command(self, command):
        try:
            output = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return output.stdout, output.stderr
        except Exception as e:
            return None, str(e)

    def call_api(self, endpoint, method="GET", data=None):
        url = f"{self.base_url}{endpoint}"
        if method == "GET":
            response = requests.get(url)
        elif method == "POST":
            response = requests.post(url, json=data)
        else:
            return None
        return response.json()

    def write_file(self, path, content):
        # Use the API to write the file
        endpoint = "/api/workspace/write"
        data = {"path": path, "content": content}
        return self.call_api(endpoint, method="POST", data=data)

    def patch_file(self, path, search_string, replace_string):
        # Use the API to patch the file
        endpoint = "/api/workspace/patch"
        data = {"path": path, "search_string": search_string, "replace_string": replace_string}
        return self.call_api(endpoint, method="POST", data=data)

# Usage
if __name__ == "__main__":
    base_url = "http://localhost:3000"
    agent = Agent(base_url)

    # Run a terminal command
    command = "ls -l"
    output, error = agent.run_command(command)
    print("Output:", output)
    print("Error:", error)

    # Write a file using the API
    path = "example.txt"
    content = "Hello, World!"
    response = agent.write_file(path, content)
    print("Write File Response:", response)

    # Patch a file using the API
    path = "example.txt"
    search_string = "Hello"
    replace_string = "Goodbye"
    response = agent.patch_file(path, search_string, replace_string)
    print("Patch File Response:", response)
