# Python Deployment Rules for amosclaud.com

Whenever you finish a task, prepare the project for deployment:

1. **Environment Setup**: Ensure dependencies are installed via `pip install -r requirements.txt`.
2. **Authentication**: Use Python's `os.environ.get('AMOSCLOUD_API_TOKEN')` to securely pull the API key.
3. **Execution**: Run the local python deployment script via `python deploy.py`. 
4. **Verification**: Confirm that the script returns a `200 OK` response from amosclaud.com.
