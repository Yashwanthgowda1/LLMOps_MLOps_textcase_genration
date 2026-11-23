"""Generate repeatable, synthetic end-to-end insurance data for local testing."""

import argparse
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Api_mock.password_utils import hash_password


HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"
DEFAULT_DB_PATH = HERE / "insurance.db"

FIRST_NAMES = (
    "Aarav", "Asha", "Dev", "Ira", "Kabir", "Meera", "Neel", "Riya",
    "Sam", "Tara", "Vihaan", "Zoya",
)
LAST_NAMES = (
    "Demo", "Sample", "Test", "Example", "Mock", "Fixture", "Synthetic",
)
LOCATIONS = (
    ("Bengaluru", "Karnataka", "560001"),
    ("Mumbai", "Maharashtra", "400001"),
    ("Pune", "Maharashtra", "411001"),
    ("Hyderabad", "Telangana", "500001"),
    ("Chennai", "Tamil Nadu", "600001"),
    ("Kochi", "Kerala", "682001"),
    ("Delhi", "Delhi", "110001"),
    ("Jaipur", "Rajasthan", "302001"),
)
PRODUCTS = (
    ("Demo Term Life", "DEMO-LIFE-TERM", "Life", 12000, 10000000, 20),
    ("Demo Family Health", "DEMO-HEALTH-FAMILY", "Health", 9000, 2500000, 1),
    ("Demo Motor Comprehensive", "DEMO-AUTO-COMP", "Auto", 6000, 2000000, 1),
    ("Demo Home Protect", "DEMO-PROPERTY-HOME", "Property", 5000, 5000000, 1),
    ("Demo Travel Plus", "DEMO-TRAVEL-PLUS", "Travel", 1500, 1000000, 1),
)
FREQUENCIES = ("Monthly", "Quarterly", "Half-Yearly", "Annual")
FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-Yearly": 6, "Annual": 12}
PAYMENT_MODES = ("UPI", "Card", "NEFT", "NetBanking", "Cheque")


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day)
    return date(year, month, day)


def ensure_staff_user(cursor, email, name, role, demo_password_hash):
    row = cursor.execute("SELECT user_id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row[0]
    cursor.execute(
        "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
        (email, name, demo_password_hash, role),
    )
    return cursor.lastrowid


def seed_reference_data(cursor, today, demo_password_hash):
    regions = (
        ("Demo Bengaluru Branch", "South", "Bengaluru"),
        ("Demo Mumbai Branch", "West", "Mumbai"),
        ("Demo Delhi Branch", "North", "Delhi"),
        ("Demo Hyderabad Branch", "Central", "Hyderabad"),
        ("Demo Chennai Branch", "South", "Chennai"),
    )
    branch_ids = []
    for name, region, city in regions:
        cursor.execute(
            """INSERT INTO branches (branch_name, region, address, contact_phone, contact_email)
               SELECT ?, ?, ?, ?, ?
               WHERE NOT EXISTS (SELECT 1 FROM branches WHERE branch_name = ?)""",
            (name, region, f"100 Test Avenue, {city}", "0000000000",
             f"{name.lower().replace(' ', '.')}@example.test", name),
        )
        branch_ids.append(cursor.execute(
            "SELECT branch_id FROM branches WHERE branch_name = ?", (name,)
        ).fetchone()[0])

    product_ids = {}
    for name, code, insurance_type, premium, max_assured, term in PRODUCTS:
        cursor.execute(
            """INSERT OR IGNORE INTO insurance_products
               (product_name, product_code, insurance_type, description,
                min_premium, max_sum_assured, policy_term_years)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, code, insurance_type, "Synthetic product for local API testing.",
             premium, max_assured, term),
        )
        product_ids[code] = cursor.execute(
            "SELECT product_id FROM insurance_products WHERE product_code = ?", (code,)
        ).fetchone()[0]

    admin_id = ensure_staff_user(
        cursor, "demo.admin@example.test", "Demo Admin", "Admin",
        demo_password_hash,
    )
    underwriter_id = ensure_staff_user(
        cursor, "demo.underwriter@example.test", "Demo Underwriter", "Underwriter",
        demo_password_hash,
    )
    assessor_id = ensure_staff_user(
        cursor, "demo.assessor@example.test", "Demo Assessor", "Assessor",
        demo_password_hash,
    )

    agent_ids = []
    for number in range(1, 11):
        email = f"demo.agent.{number:03d}@example.test"
        user_id = ensure_staff_user(
            cursor, email, f"Demo Agent User {number:03d}", "Agent",
            demo_password_hash,
        )
        license_no = f"TEST-LIC-{number:06d}"
        cursor.execute(
            """INSERT OR IGNORE INTO agents
               (user_id, first_name, last_name, email, phone, license_no,
                branch_id, commission_rate, status, joined_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, f"Agent{number:03d}", "Test", email, "0000000000",
             license_no, branch_ids[(number - 1) % len(branch_ids)],
             5.0 + (number % 4) * 0.25, "Active",
             (today - timedelta(days=365 + number * 13)).isoformat()),
        )
        agent_ids.append(cursor.execute(
            "SELECT agent_id FROM agents WHERE email = ?", (email,)
        ).fetchone()[0])

    return branch_ids, product_ids, agent_ids, admin_id, underwriter_id, assessor_id


def add_customer(cursor, index, rng, today, demo_password_hash):
    email = f"fake.customer.{index:06d}@example.test"
    row = cursor.execute(
        "SELECT customer_id FROM customers WHERE email = ?", (email,)
    ).fetchone()
    if row:
        return row[0], False

    user_email = email
    user = cursor.execute(
        "SELECT user_id FROM users WHERE email = ?", (user_email,)
    ).fetchone()
    if user:
        user_id = user[0]
    else:
        cursor.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
            (
                user_email,
                f"Demo Customer {index:06d}",
                demo_password_hash,
                "Customer",
            ),
        )
        user_id = cursor.lastrowid

    first_name = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
    last_name = LAST_NAMES[((index - 1) // len(FIRST_NAMES)) % len(LAST_NAMES)]
    city, state, pincode = LOCATIONS[(index - 1) % len(LOCATIONS)]
    birth_date = today - timedelta(days=rng.randint(21 * 365, 75 * 365))
    cursor.execute(
        """INSERT INTO customers
           (user_id, first_name, last_name, dob, gender, email, phone, address,
            city, state, pincode, pan_number, aadhar_number, kyc_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, first_name, last_name, birth_date.isoformat(),
         rng.choice(("Male", "Female", "Other")), email,
         f"00000{index % 100000:05d}", f"{index} Synthetic Road",
         city, state, pincode, f"TESTPAN{index:06d}",
         f"{index:012d}", rng.choices(
             ("Verified", "Pending", "Rejected"), weights=(75, 20, 5), k=1
         )[0]),
    )
    return cursor.lastrowid, True


def add_policy(cursor, index, customer_id, product_ids, agent_ids, today, seed,
               underwriter_id, assessor_id, admin_id):
    policy_number = f"DEMO-POL-{index:06d}"
    if cursor.execute(
        "SELECT 1 FROM po   licies WHERE policy_number = ?", (policy_number,)
    ).fetchone():
        return False

    rng = random.Random(seed + index * 7919)
    product = PRODUCTS[(index - 1) % len(PRODUCTS)]
    _, product_code, insurance_type, minimum_premium, max_assured, term = product
    product_id = product_ids[product_code]
    if insurance_type == "Life":
        term = 20
    start_date = today - timedelta(days=rng.randint(0, 5 * 365))
    end_date = add_years(start_date, term)
    frequency = rng.choice(FREQUENCIES)
    annual_premium = round(minimum_premium * rng.uniform(1.0, 3.5), 2)
    sum_assured = round(max_assured * rng.uniform(0.1, 0.8), 2)
    if end_date < today:
        status = "Expired"
    else:
        status = rng.choices(
            ("Active", "Lapsed", "Cancelled", "Surrendered"),
            weights=(88, 6, 4, 2), k=1,
        )[0]

    cursor.execute(
        """INSERT INTO policies
           (policy_number, customer_id, product_id, agent_id, start_date, end_date,
            sum_assured, annual_premium, payment_frequency, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (policy_number, customer_id, product_id, agent_ids[(index - 1) % len(agent_ids)],
         start_date.isoformat(), end_date.isoformat(), sum_assured, annual_premium,
         frequency, status),
    )
    policy_id = cursor.lastrowid

    cursor.execute(
        """INSERT INTO underwriting_decisions
           (policy_id, underwriter_id, decision, premium_loading, remarks, decided_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (policy_id, underwriter_id, "Approved", 0,
         "Synthetic auto-approved demo application.", start_date.isoformat()),
    )
    cursor.execute(
        """INSERT INTO policy_coverage
           (policy_id, coverage_type, coverage_limit, deductible, exclusions)
           VALUES (?, ?, ?, ?, ?)""",
        (policy_id, insurance_type, sum_assured, 5000,
         "Pre-existing or intentional loss excluded in demo fixture."),
    )
    if index % 3 == 0:
        cursor.execute(
            """INSERT INTO policy_riders
               (policy_id, rider_type, coverage_amount, additional_premium)
               VALUES (?, ?, ?, ?)""",
            (policy_id, rng.choice(("Accidental Benefit", "Critical Illness", "Roadside Assistance")),
             round(sum_assured * 0.1, 2), round(annual_premium * 0.08, 2)),
        )
    cursor.execute(
        """INSERT INTO beneficiaries
           (policy_id, full_name, relationship, dob, percentage_share, contact_phone)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (policy_id, f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {LAST_NAMES[index % len(LAST_NAMES)]}",
         rng.choice(("Spouse", "Parent", "Child", "Sibling")),
         (today - timedelta(days=rng.randint(18 * 365, 70 * 365))).isoformat(),
         100, "0000000000"),
    )

    interval = FREQUENCY_MONTHS[frequency]
    installment_amount = round(annual_premium * interval / 12, 2)
    premium_ids = []
    installment_count = min(max(1, term * 12 // interval), 4)
    for installment in range(installment_count):
        due_date = add_months(start_date, installment * interval)
        if due_date > today:
            premium_status = "Due"
        elif due_date < today - timedelta(days=45) and index % 11 == 0 and installment == 3:
            premium_status = "Overdue"
        elif due_date <= today and index % 17 == 0 and installment == 3:
            premium_status = "Waived"
        else:
            premium_status = "Paid"
        cursor.execute(
            """INSERT INTO premiums
               (policy_id, due_date, amount, frequency, status, grace_period_end)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (policy_id, due_date.isoformat(), installment_amount, frequency,
             premium_status, (due_date + timedelta(days=30)).isoformat()),
        )
        premium_id = cursor.lastrowid
        premium_ids.append(premium_id)
        if premium_status == "Paid":
            payment_status = rng.choices(
                ("Success", "Failed", "Pending", "Refunded"),
                weights=(93, 3, 3, 1), k=1,
            )[0]
            cursor.execute(
                """INSERT INTO payments
                   (policy_id, premium_id, amount_paid, payment_date, payment_mode,
                    transaction_ref, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (policy_id, premium_id, installment_amount,
                 min(due_date + timedelta(days=rng.randint(0, 5)), today).isoformat()
                 + " 10:00:00",
                 rng.choice(PAYMENT_MODES), f"DEMO-PAY-{index:06d}-{installment + 1}",
                 payment_status),
            )
            payment_id = cursor.lastrowid
            if payment_status == "Success":
                cursor.execute(
                    """INSERT INTO payment_receipts
                       (payment_id, receipt_number, issued_date, pdf_path)
                       VALUES (?, ?, ?, ?)""",
                    (payment_id, f"DEMO-REC-{index:06d}-{installment + 1}",
                     due_date.isoformat(),
                     f"test-receipts/DEMO-REC-{index:06d}-{installment + 1}.pdf"),
                )

    risk_category = rng.choices(
        ("Low", "Medium", "High", "Very High"), weights=(45, 35, 16, 4), k=1
    )[0]
    risk_score = {"Low": 20, "Medium": 48, "High": 72, "Very High": 91}[risk_category]
    cursor.execute(
        """INSERT INTO risk_profiles
           (customer_id, risk_score, risk_category, assessment_notes, assessed_on, assessed_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (customer_id, risk_score, risk_category,
         "Synthetic risk assessment for test data.", today.isoformat(), underwriter_id),
    )
    cursor.execute(
        """INSERT INTO documents
           (entity_type, entity_id, doc_type, file_name, file_path, uploaded_by)
           VALUES ('Policy', ?, 'Policy Schedule', ?, ?, ?)""",
        (policy_id, f"{policy_number}-schedule.pdf",
         f"test-documents/{policy_number}-schedule.pdf", admin_id),
    )
    cursor.execute(
        """INSERT INTO notifications
           (customer_id, notification_type, subject, message, sent_at, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (customer_id, rng.choice(("Email", "SMS", "Push", "WhatsApp")),
         "Demo policy issued", f"Policy {policy_number} was issued for testing.",
         datetime.now().isoformat(timespec="seconds"),
         rng.choice(("Sent", "Delivered", "Pending"))),
    )

    if insurance_type == "Auto":
        cursor.execute(
            """INSERT INTO vehicles
               (policy_id, make, model, manufacture_year, registration_no, chassis_no,
                engine_no, fuel_type, vehicle_type, idv_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (policy_id, "Demo Motors", rng.choice(("Comet", "Orbit", "Pioneer")),
             rng.randint(2017, today.year), f"TEST-REG-{index:06d}",
             f"TEST-CHASSIS-{index:06d}", f"TEST-ENGINE-{index:06d}",
             rng.choice(("Petrol", "Diesel", "CNG", "Electric", "Hybrid")),
             rng.choice(("2-Wheeler", "4-Wheeler", "Commercial", "Heavy Vehicle")),
             sum_assured),
        )
    elif insurance_type == "Property":
        city, state, pincode = LOCATIONS[(index - 1) % len(LOCATIONS)]
        cursor.execute(
            """INSERT INTO properties
               (policy_id, property_type, address, city, state, pincode,
                construction_type, built_year, sq_ft, market_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (policy_id, rng.choice(("Residential", "Commercial", "Industrial", "Land")),
             f"{index} Synthetic Property Road", city, state, pincode,
             rng.choice(("Concrete", "Brick", "Steel", "Mixed")),
             rng.randint(1990, today.year), rng.randint(500, 5000), sum_assured),
        )
    elif insurance_type == "Health":
        for member_number, relation in enumerate(("Self", "Spouse"), start=1):
            cursor.execute(
                """INSERT INTO health_members
                   (policy_id, full_name, relationship, dob, gender, sum_insured,
                    pre_existing_conditions)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (policy_id, f"Demo Member {index:06d}-{member_number}", relation,
                 (today - timedelta(days=(30 + member_number * 5) * 365)).isoformat(),
                 rng.choice(("Male", "Female", "Other")), sum_assured,
                 "None reported" if index % 5 else "Synthetic test condition"),
            )
    elif insurance_type == "Life":
        cursor.execute(
            """INSERT INTO life_insured
               (policy_id, full_name, dob, occupation, annual_income, smoker, medical_history)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (policy_id, f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {LAST_NAMES[index % len(LAST_NAMES)]}",
             (today - timedelta(days=rng.randint(25 * 365, 60 * 365))).isoformat(),
             rng.choice(("Engineer", "Teacher", "Designer", "Consultant")),
             rng.randint(400000, 2500000), int(index % 7 == 0),
             "Synthetic test history" if index % 13 == 0 else "None reported"),
        )

    if insurance_type != "Travel" and index % 4 == 0:
        coverage_end = min(end_date, today)
        available_days = (coverage_end - start_date).days
        if available_days >= 30:
            incident_date = start_date + timedelta(days=rng.randint(0, available_days))
            claim_date = min(incident_date + timedelta(days=rng.randint(1, 30)), today)
            claim_number = f"DEMO-CLM-{index:06d}"
            claim_amount = round(sum_assured * rng.uniform(0.01, 0.25), 2)
            claim_status = rng.choices(
                ("Submitted", "Under Review", "Approved", "Rejected", "Settled", "Withdrawn"),
                weights=(15, 25, 15, 10, 30, 5), k=1,
            )[0]
            cursor.execute(
                """INSERT INTO claims
                   (claim_number, policy_id, customer_id, incident_date, claim_date,
                    claim_type, claim_amount, description, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (claim_number, policy_id, customer_id, incident_date.isoformat(),
                 claim_date.isoformat(), insurance_type, claim_amount,
                 "Synthetic incident record created for API and workflow testing.",
                 claim_status),
            )
            claim_id = cursor.lastrowid
            cursor.execute(
                """INSERT INTO claim_documents
                   (claim_id, doc_type, file_name, file_path, uploaded_by, is_verified)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (claim_id, "Claim Form", f"{claim_number}-form.pdf",
                 f"test-documents/{claim_number}-form.pdf", admin_id, 1),
            )
            cursor.execute(
                """INSERT INTO documents
                   (entity_type, entity_id, doc_type, file_name, file_path, uploaded_by)
                   VALUES ('Claim', ?, 'Supporting Evidence', ?, ?, ?)""",
                (claim_id, f"{claim_number}-evidence.pdf",
                 f"test-documents/{claim_number}-evidence.pdf", admin_id),
            )
            if claim_status != "Submitted":
                recommendation = {
                    "Approved": "Approve", "Settled": "Approve",
                    "Rejected": "Reject", "Under Review": "Escalate",
                    "Withdrawn": "Reject",
                }[claim_status]
                assessed_amount = round(claim_amount * rng.uniform(0.7, 1.0), 2)
                cursor.execute(
                    """INSERT INTO claim_assessments
                       (claim_id, assessor_id, assessment_date, assessed_amount,
                        remarks, recommendation)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (claim_id, assessor_id,
                     min(claim_date + timedelta(days=5), today).isoformat(),
                     assessed_amount, "Synthetic assessor notes.", recommendation),
                )
                if claim_status == "Settled":
                    cursor.execute(
                        """INSERT INTO claim_settlements
                           (claim_id, settled_amount, settled_date, payment_mode,
                            bank_account, bank_ifsc, transaction_ref, settled_by)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (claim_id, assessed_amount,
                         min(claim_date + timedelta(days=10), today).isoformat(),
                         rng.choice(("NEFT", "RTGS", "UPI")),
                         f"000000{index:06d}", "TEST0000001",
                         f"DEMO-SET-{index:06d}", admin_id),
                    )

    cursor.execute(
        """INSERT INTO audit_logs
           (table_name, record_id, action, changed_by, new_value)
           VALUES ('policies', ?, 'INSERT', ?, ?)""",
        (policy_id, admin_id, f'{{"policy_number":"{policy_number}","status":"{status}"}}'),
    )
    return True


def seed(database_path, customer_count, seed):
    if customer_count < 1:
        raise ValueError("--customers must be at least 1")
    database_path = Path(database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        today = date.today()
        demo_password_hash = hash_password("demo123")
        cursor = connection.cursor()
        cursor.execute("BEGIN")
        _, product_ids, agent_ids, admin_id, underwriter_id, assessor_id = (
            seed_reference_data(cursor, today, demo_password_hash)
        )
        new_customers = 0
        new_policies = 0
        for index in range(1, customer_count + 1):
            rng = random.Random(seed + index * 104729)
            customer_id, created = add_customer(
                cursor, index, rng, today, demo_password_hash
            )
            new_customers += int(created)
            new_policies += int(add_policy(
                cursor, index, customer_id, product_ids, agent_ids, today, seed,
                underwriter_id, assessor_id, admin_id,
            ))
        connection.commit()
        summary = {
            "customers": cursor.execute(
                "SELECT COUNT(*) FROM customers WHERE email LIKE 'fake.customer.%@example.test'"
            ).fetchone()[0],
            "policies": cursor.execute(
                "SELECT COUNT(*) FROM policies WHERE policy_number LIKE 'DEMO-POL-%'"
            ).fetchone()[0],
            "claims": cursor.execute(
                "SELECT COUNT(*) FROM claims WHERE claim_number LIKE 'DEMO-CLM-%'"
            ).fetchone()[0],
            "new_customers": new_customers,
            "new_policies": new_policies,
        }
        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Seed repeatable synthetic insurance workflows into SQLite."
    )
    parser.add_argument(
        "--customers", type=int, default=1000,
        help="Target number of demo customers and policies (default: 1000).",
    )
    parser.add_argument(
        "--seed", type=int, default=20261109,
        help="Random seed for repeatable test data (default: 20261109).",
    )
    parser.add_argument(
        "--database", type=Path, default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH}).",
    )
    args = parser.parse_args()
    summary = seed(args.database, args.customers, args.seed)
    print(f"Seeded database: {args.database.resolve()}")
    print(
        f"Demo customers: {summary['customers']} "
        f"(added {summary['new_customers']}); "
        f"policies: {summary['policies']} "
        f"(added {summary['new_policies']}); "
        f"claims: {summary['claims']}"
    )
    print("Demo customer login: fake.customer.000001@example.test / demo123")
    print("Demo admin login: demo.admin@example.test / demo123")


if __name__ == "__main__":
    main()
