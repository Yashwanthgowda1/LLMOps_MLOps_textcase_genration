
Key	Purpose
PRIMARY KEY	uniquely identifies each row, NOT NULL + UNIQUE
FOREIGN KEY	links to PRIMARY KEY of another table
UNIQUE KEY	no duplicates allowed, can be NULL
COMPOSITE KEY	primary key using 2+ columns
CANDIDATE KEY	any column that could be primary key
SURROGATE KEY	system-generated id (auto increment)
uvicorn app:app --reload --host 0.0.0.0 --port 8081

## Synthetic end-to-end test data

From the repository root, run:

```powershell
python "New folder\Mock_api_insurance\Sqllite\seed_demo_data.py"
uvicorn Api_mock.Mock_api:app --reload --host 127.0.0.1 --port 8082
```

The script creates the SQLite schema if needed and seeds 1,000 synthetic
customers and policies by default, plus products, branches, agents, premiums,
payments and receipts, policy coverage, risk and underwriting records,
documents, notifications, and a representative set of claims, assessments,
and settlements. It also adds vehicle, property, health, and life details for
the corresponding policy types.

Use `--customers 2000` to set the target size, `--seed 42` to change the
repeatable random data, or `--database "path\to\test.db"` to use a separate
database. The operation is additive and safe to rerun: generated records use
stable demo identifiers and existing unrelated records are preserved. Demo
customer logins use `fake.customer.000001@example.test` / `demo123`; the demo
administrator uses `demo.admin@example.test` / `demo123`. These credentials
are for local testing only. All generated names and contact/identity fields
are synthetic placeholders.

Passwords are stored as PBKDF2 hashes. To upgrade plaintext passwords in an
existing SQLite database, run `python Sqllite\migrate_passwords.py` from the
`Mock_api_insurance` directory before starting the API.