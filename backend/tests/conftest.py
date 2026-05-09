"""Shared pytest configuration for backend tests.

Adds the backend directory to sys.path so tests can import the same modules
the FastAPI app does (`agents.*`, `graph.*`, `scoring.*`, etc.) and stubs the
GROQ_API_KEY so importing modules that touch `get_llm()` doesn't blow up."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("GROQ_API_KEY", "test_key_for_pytest")
