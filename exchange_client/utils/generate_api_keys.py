import secrets
# scripts/generate_api_keys.py
"""
Script to generate secure API keys

Usage:
    python scripts/generate_api_keys.py
"""

def generate_api_key(length: int = 32) -> str:
    """Generate a secure random API key"""
    return secrets.token_urlsafe(length)


if __name__ == "__main__":
    print("Generated API Keys:")
    print(f"API_MASTER_KEY={generate_api_key()}")
    print(f"API_READONLY_KEY={generate_api_key()}")
    print(f"API_TRADING_KEY={generate_api_key()}")
    print(f"WEBHOOK_SECRET={generate_api_key(24)}")
    print("\nAdd these to your .env file and Render environment variables")