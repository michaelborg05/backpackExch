# utils/secrets.py
"""
Encryption-at-rest for sensitive DB columns (API keys, exchange secrets).

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
The encryption key lives ONLY in the DB_ENCRYPTION_KEY environment variable —
never in the database itself. If the DB is dumped without that env var,
the ciphertext is useless.

─── Setup ────────────────────────────────────────────────────────────────────

1. Install:
       pip install cryptography

2. Generate your key (run ONCE, store the output in Render as DB_ENCRYPTION_KEY):
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

3. Add to Render environment variables:
       DB_ENCRYPTION_KEY = <the key you just generated>

   Treat this like a root password — if you lose it, you cannot decrypt
   the stored secrets. Keep a secure backup (e.g. in a password manager).

─── Column convention ────────────────────────────────────────────────────────

Encrypted values are stored with an "enc:" prefix:
    enc:gAAAAABh...

This lets resolve_secret() detect the encoding automatically, and lets
you have a mix of encrypted and legacy plain values in the same column
during a migration without breaking anything.

─── Usage ────────────────────────────────────────────────────────────────────

    from utils.secrets import encrypt_secret, resolve_secret

    # Writing (e.g. when creating/updating a trading profile):
    profile.api_key = encrypt_secret("my-raw-api-key")
    profile.secret  = encrypt_secret("my-raw-secret")

    # Reading (use this everywhere — handles enc: and plain transparently):
    raw_key    = resolve_secret(profile.api_key)
    raw_secret = resolve_secret(profile.secret)

─── Key rotation ─────────────────────────────────────────────────────────────

    1. Set DB_ENCRYPTION_KEY_OLD = current key
       Set DB_ENCRYPTION_KEY     = new key
    2. python -m utils.secrets rotate
    3. Verify everything still works
    4. Unset DB_ENCRYPTION_KEY_OLD
"""

import os
import sys
from typing import Optional

ENC_PREFIX = "enc:"


def _get_fernet(env_var: str = "DB_ENCRYPTION_KEY"):
    """Load and return a Fernet instance from the named environment variable."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError(
            "The 'cryptography' package is required. "
            "Install it with: pip install cryptography"
        )

    key = os.environ.get(env_var)
    if not key:
        raise EnvironmentError(
            f"Environment variable '{env_var}' is not set. "
            "Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.strip().encode())
    except Exception:
        raise ValueError(
            f"'{env_var}' is not a valid Fernet key. "
            "It must be a URL-safe base64-encoded 32-byte key. Re-generate it."
        )


def encrypt_secret(plain_value: str) -> str:
    """
    Encrypt a plaintext secret and return a prefixed ciphertext string
    safe to store in a database column.

    Returns: "enc:<fernet-token>"
    Raises:  ValueError if plain_value is empty.
             EnvironmentError if DB_ENCRYPTION_KEY is not set.
    """
    if not plain_value:
        raise ValueError("Cannot encrypt an empty secret")
    token = _get_fernet().encrypt(plain_value.encode()).decode()
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(stored_value: str) -> str:
    """
    Decrypt a value previously produced by encrypt_secret().

    Expects the "enc:" prefix. Use resolve_secret() if the value might
    be plain (e.g. during a migration).

    Raises: ValueError on bad input or wrong key.
    """
    try:
        from cryptography.fernet import InvalidToken
    except ImportError:
        raise ImportError("pip install cryptography")

    if not stored_value or not stored_value.startswith(ENC_PREFIX):
        raise ValueError(
            f"Value does not have the '{ENC_PREFIX}' prefix — "
            "it may not be encrypted. Use resolve_secret() for mixed columns."
        )

    token = stored_value[len(ENC_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Decryption failed. The token is corrupt or DB_ENCRYPTION_KEY "
            "does not match the key used to encrypt this value."
        )


def resolve_secret(stored_value: Optional[str]) -> Optional[str]:
    """
    Transparently resolve a DB column value to its plaintext secret.

    Handles all three states a column might be in:
      None / ""         → returns None  (unset)
      "enc:<token>"     → decrypts and returns plaintext
      anything else     → returns as-is (plain legacy value)

    This is the function to use in all read paths.
    """
    if not stored_value:
        return None
    if stored_value.startswith(ENC_PREFIX):
        return decrypt_secret(stored_value)
    # Plain value — safe to return as-is (handles legacy or unencrypted rows)
    return stored_value


def is_encrypted(value: Optional[str]) -> bool:
    """Return True if the value was encrypted by this module."""
    return bool(value and value.startswith(ENC_PREFIX))


# ─── Key rotation ──────────────────────────────────────────────────────────────

def _reencrypt(stored_value: str, old_key_env: str) -> str:
    """Decrypt with old key, re-encrypt with current DB_ENCRYPTION_KEY."""
    try:
        from cryptography.fernet import InvalidToken
    except ImportError:
        raise ImportError("pip install cryptography")

    if not stored_value.startswith(ENC_PREFIX):
        # Not yet encrypted — just encrypt with new key
        return encrypt_secret(stored_value)

    token = stored_value[len(ENC_PREFIX):]
    try:
        plain = _get_fernet(old_key_env).decrypt(token.encode()).decode()
    except InvalidToken:
        raise ValueError(
            f"Could not decrypt with key from '{old_key_env}'. "
            "Make sure that env var holds the PREVIOUS key."
        )
    return encrypt_secret(plain)


def rotate_all_profile_secrets(old_key_env: str = "DB_ENCRYPTION_KEY_OLD"):
    """
    Re-encrypt all TradingProfileDB secrets from the old key to the new key.

    Run after updating DB_ENCRYPTION_KEY and setting DB_ENCRYPTION_KEY_OLD
    to the previous value:

        DB_ENCRYPTION_KEY_OLD=<old-key> DB_ENCRYPTION_KEY=<new-key> \\
            python -m utils.secrets rotate
    """
    from db.session import SessionLocal
    from db.models import TradingProfileDB

    db = SessionLocal()
    try:
        profiles = db.query(TradingProfileDB).all()
        rotated = skipped = errors = 0

        for p in profiles:
            changed = False
            for field in ("api_key", "secret"):
                val = getattr(p, field)
                if not val:
                    continue
                try:
                    setattr(p, field, _reencrypt(val, old_key_env))
                    changed = True
                except Exception as e:
                    print(f"  ERROR [{p.profile_name}] {field}: {e}", file=sys.stderr)
                    errors += 1

            if changed:
                db.add(p)
                rotated += 1
            else:
                skipped += 1

        db.commit()
        print(f"Rotation complete — rotated: {rotated}, skipped: {skipped}, errors: {errors}")
        if errors:
            print("Some profiles failed — check output above. DB NOT partially committed.", file=sys.stderr)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rotate":
        rotate_all_profile_secrets()
    else:
        print("Usage: python -m utils.secrets rotate")
        print(__doc__)
