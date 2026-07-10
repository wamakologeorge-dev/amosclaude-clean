import os

class CLIConfig:
    API_URL = os.getenv("AMOSCLAUD_API_URL", "http://localhost:3000")
    AGENT_ID = os.getenv("AMOSCLAUD_AGENT_ID", "amos-agent-001")
    TIMEOUT = int(os.getenv("AMOSCLAUD_TIMEOUT", "10"))
    CMOOD_DIR = os.getenv("CMOOD_SYNC_DIR", "./cmood")
