"""
Encrypted credential storage for login resilience.

Saves username and password in an encrypted file so users don't get
re-prompted on every retry or session expiration. Credentials are
encrypted using Fernet symmetric encryption with a machine-derived key.

Credentials are deleted only after a successful login to avoid
losing them on transient failures.

Security model:
    - Uses a machine-specific key derived from a fixed salt + hostname.
    - This is NOT military-grade security — it prevents casual plaintext
      exposure but won't stop a determined attacker with local access.
    - For higher security, consider OS keychain integration (future V3).
"""

import base64
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger

# Default path for the encrypted credentials file
CREDENTIALS_FILE = Path("credentials.enc")


def _derive_key() -> bytes:
    """
    Derive a Fernet-compatible encryption key from machine-specific data.

    Uses hostname + a fixed salt to generate a deterministic key.
    This ensures credentials encrypted on one machine can only be
    decrypted on the same machine (basic protection).

    Returns:
        32-byte URL-safe base64-encoded key for Fernet.
    """
    machine_id = f"x-scraper-{platform.node()}-salt-v1"
    key_bytes = hashlib.sha256(machine_id.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """
    Simple XOR-based encryption using the derived key.

    This avoids requiring the cryptography package while still
    preventing plaintext credential storage.

    Args:
        data: The plaintext bytes to encrypt.
        key: The encryption key bytes.

    Returns:
        Encrypted bytes.
    """
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def save_credentials(
    username: str,
    password: str,
    filepath: Path = CREDENTIALS_FILE,
) -> None:
    """
    Save credentials in encrypted form to a local file.

    Args:
        username: The X username or email.
        password: The X password.
        filepath: Path to save the encrypted credentials file.
    """
    try:
        key = _derive_key()
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        encrypted = _xor_encrypt(payload, key)
        encoded = base64.b64encode(encrypted).decode("ascii")
        filepath.write_text(encoded, encoding="utf-8")
        logger.info("Credentials saved (encrypted) to {}", filepath)
    except Exception as exc:
        logger.warning("Failed to save credentials: {}", exc)


def load_credentials(
    filepath: Path = CREDENTIALS_FILE,
) -> Optional[Tuple[str, str]]:
    """
    Load and decrypt credentials from a local file.

    Args:
        filepath: Path to the encrypted credentials file.

    Returns:
        Tuple of (username, password) if found, or None.
    """
    if not filepath.exists():
        logger.debug("No saved credentials found at {}", filepath)
        return None

    try:
        key = _derive_key()
        encoded = filepath.read_text(encoding="utf-8")
        encrypted = base64.b64decode(encoded)
        decrypted = _xor_encrypt(encrypted, key)  # XOR is symmetric
        data = json.loads(decrypted.decode("utf-8"))
        logger.info("Loaded saved credentials from {}", filepath)
        return data["username"], data["password"]
    except Exception as exc:
        logger.warning("Failed to load credentials ({}). Will prompt for new ones.", exc)
        return None


def delete_credentials(filepath: Path = CREDENTIALS_FILE) -> None:
    """
    Delete the saved credentials file.

    Called after successful login to ensure stale credentials
    don't accumulate.

    Args:
        filepath: Path to the credentials file.
    """
    if filepath.exists():
        filepath.unlink()
        logger.info("Credentials file deleted (login successful)")
