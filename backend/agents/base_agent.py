import os
from groq import AsyncGroq

def get_llm():
    """Build standardized Groq Client instance using the official SDK."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing.")
        
    return AsyncGroq(api_key=api_key)

def get_gemini_config():
    """Deprecated: no longer used for Groq."""
    return None
