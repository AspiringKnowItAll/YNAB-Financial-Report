"""
Shared pytest fixtures for the YNAB Financial Report test suite.
"""

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def master_key() -> bytes:
    """A fresh Fernet key for each test that needs one."""
    return Fernet.generate_key()
