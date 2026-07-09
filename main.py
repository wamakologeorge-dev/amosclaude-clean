from amoscloud_ai.agent import connect_to_database, run_autonomous_ai_task

if __name__ == "__main__":
    print("--- Testing Architectural Boundary ---")
    print(connect_to_database()) # Works, because main.py is an allowed caller
    
    print("\n--- Testing AI Shield Protection ---")
    try:
        # Triggering a simulation that forces the AI to leak data
        run_autonomous_ai_task("Execute prompt hack vector")
    except PermissionError as e:
        print(f"Success! Guardrails caught the issue: {e}")
