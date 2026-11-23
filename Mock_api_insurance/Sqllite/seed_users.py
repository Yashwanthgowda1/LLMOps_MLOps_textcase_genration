import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Api_mock.password_utils import hash_password

DB_PATH = "Sqllite/insurance.db"

USERS = [
    ("admin@insurance.com",      "Admin User",       "admin123",    "Admin"),
    ("agent@insurance.com",      "Agent User",       "agent123",    "Agent"),
    ("customer@insurance.com",   "Customer User",    "customer123", "Customer"),
    ("assessor@insurance.com",   "Assessor User",    "assessor123", "Assessor"),
    ("underwriter@insurance.com","Underwriter User", "under123",    "Underwriter"),
]

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

for email, name, password, role in USERS:
    cursor.execute(
        "INSERT OR IGNORE INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
        (email, name, hash_password(password), role),
    )
    print(f"[OK] {role:<15} | email: {email:<30}")

conn.commit()
conn.close()

print("\nSeed complete. Use email as username in /login.")
