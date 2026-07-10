# main.py
from agent import Agent
from route import app

def main():
    base_url = "http://localhost:3000"
    agent = Agent(base_url)

    # Run the Flask app
    if __name__ == "__main__":
        app.run(debug=True)

    # Use the agent to run commands, call API endpoints, etc.
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

if __name__ == "__main__":
    main()
