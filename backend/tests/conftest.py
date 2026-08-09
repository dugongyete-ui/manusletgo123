"""
Pytest configuration and fixtures
"""
import sys
import os
import pytest
import tempfile
from pathlib import Path

# Add the parent directory to Python path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import uuid

# Base URL for API testing
BASE_URL = "http://localhost:8000/api/v1"

@pytest.fixture
def client():
    """Create requests session"""
    session = requests.Session()
    # Don't set default Content-Type to allow multipart/form-data for file uploads
    return session


@pytest.fixture
def authenticated_headers(client):
    """Create a disposable user and return headers for protected API tests."""
    user_data = {
        "fullname": "File Test User",
        "password": "password123",
        "email": f"file_test_{uuid.uuid4().hex[:10]}@example.com",
    }
    response = client.post(f"{BASE_URL}/auth/register", json=user_data)
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
