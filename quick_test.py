
import sys
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test_secret_key_32_chars_for_tests"
os.environ["DEBUG"] = "true"
os.environ["APP_ENV"] = "test"

# Quickly try importing
from api.main import app
print("SUCCESS: App loaded")
