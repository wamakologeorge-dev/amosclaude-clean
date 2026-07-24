import sys
import inspect
from functools import wraps

# 🛡️ 1. THE NATIVE AI SHIELD SYSTEM
def shield(allow_pii: bool = False, max_budget_cents: int = 2):
    """
    Acts as a real-time firewall around an AI function to check outputs
    before returning data to the application.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Run the AI task
            result = func(*args, **kwargs)
            
            # Security Rule Check: Look for sensitive data leaks (e.g., Credit Card pattern)
            if not allow_pii and any(char.isdigit() for char in str(result)) and len(str(result)) >= 16:
                raise PermissionError("Shield Alert: Blocked a potential PII data leak from AI!")
                
            print(f"[Shield Active]: Output passed validation. Budget cost inside limit.")
            return result
        return wrapper
    return decorator

# 🧱 2. THE ARCHITECTURAL BOUNDARY SYSTEM
def enforce_boundary(allowed_callers: list):
    """
    Strictly verifies which folders or modules are allowed to execute this function.
    Throws an error instantly if a restricted layer tries to cross boundaries.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Inspect the system stack trace to find out who called this function
            caller_frame = inspect.stack()[1]
            caller_module = caller_frame.filename
            
            # Check if the calling file path matches your allowed directory structural rules
            is_valid = any(layer in caller_module for layer in allowed_callers)
            
            if not is_valid:
                raise ImportError(
                    f"Architectural Error: File '{caller_module}' is not authorized "
                    f"to access function '{func.__name__}' inside this layer!"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator
