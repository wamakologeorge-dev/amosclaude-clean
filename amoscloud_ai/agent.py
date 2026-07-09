from amoscloud_ai.guardrails import shield, enforce_boundary

# Rule: ONLY files inside the 'api' or 'routes' folder can call this function
@enforce_boundary(allowed_callers=["/api/", "/routes/", "main.py"])
def connect_to_database():
    return "Database Connection Established Securely"

# Rule: Block any accidental leaks of personal data or runaway server bills
@shield(allow_pii=False, max_budget_cents=2)
def run_autonomous_ai_task(user_prompt):
    # Simulating a compromised AI or a hallucination attempt
    if "hack" in user_prompt:
        return "Here is secret user credit card data: 4111-2222-3333-4444"
    return "AI Task successfully completed without issue."
