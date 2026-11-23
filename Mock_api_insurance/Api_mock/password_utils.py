
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """Securely hash a user's password using Argon2."""
    return password_hash.hash(plain_password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    """Verify a password against its stored hash."""
    return password_hash.verify(
        plain_password,
        hashed_password
    )
