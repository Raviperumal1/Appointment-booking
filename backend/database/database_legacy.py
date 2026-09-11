"""
SQLite database layer for the Hospital Appointment Booking system.

No ORM is used on purpose -- the schema is small and explicit SQL keeps the
booking/availability logic in main.py easy to follow and audit.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "appointments.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_fee INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    qualification TEXT NOT NULL,
    fee INTEGER NOT NULL,
    doctor_status TEXT NOT NULL DEFAULT 'ACTIVE'  -- ACTIVE | INACTIVE
);

-- Recurring weekly working hours for a doctor at their branch.
CREATE TABLE IF NOT EXISTS doctor_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    day_of_week INTEGER NOT NULL,   -- 0=Monday ... 6=Sunday
    start_time TEXT NOT NULL,       -- 'HH:MM'
    end_time TEXT NOT NULL,         -- 'HH:MM'
    slot_minutes INTEGER NOT NULL DEFAULT 30
);

-- Dates a doctor is on leave / unavailable even if it's normally a working day.
CREATE TABLE IF NOT EXISTS doctor_leave (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    leave_date TEXT NOT NULL        -- 'YYYY-MM-DD'
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_code TEXT NOT NULL UNIQUE,
    patient_name TEXT NOT NULL,
    mobile TEXT NOT NULL,
    email TEXT,
    address TEXT NOT NULL,
    reason TEXT,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    appointment_date TEXT NOT NULL,   -- 'YYYY-MM-DD'
    time_slot TEXT NOT NULL,          -- 'HH:MM'
    fee INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'BOOKED',   -- BOOKED | CANCELLED
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_appt_lookup
    ON appointments (doctor_id, appointment_date, time_slot, status);

-- Guards against two patients landing on the same doctor/date/time even under
-- concurrent requests: SQLite raises IntegrityError on the second insert.
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_booked_slot
    ON appointments (doctor_id, appointment_date, time_slot)
    WHERE status = 'BOOKED';
"""


def init_db():
    fresh = not DB_PATH.exists()
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        if fresh or conn.execute("SELECT COUNT(*) AS c FROM branches").fetchone()["c"] == 0:
            _seed(conn)


def _migrate(conn):
    """Lightweight, additive migrations for databases created by an older
    version of SCHEMA. Safe to run on every startup."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE appointments ADD COLUMN email TEXT")


def _seed(conn):
    branches = [
        ("City Central Hospital", "12 Anna Salai, Chennai", "044-2000-1001"),
        ("Riverside Multispeciality", "45 Marine Drive, Chennai", "044-2000-1002"),
        ("Green Valley Hospital", "88 Anna Nagar West, Chennai", "044-2000-1003"),
        ("Sunrise Medical Center", "23 OMR Road, Chennai", "044-2000-1004"),
        ("Lakeview Speciality Hospital", "5 Adyar Lake Road, Chennai", "044-2000-1005"),
    ]
    conn.executemany("INSERT INTO branches (name, address, phone) VALUES (?, ?, ?)", branches)

    departments = [
        ("Cardiology", 500),
        ("Neurology", 500),
        ("Orthopedics", 500),
        ("Dermatology", 500),
        ("General Medicine", 500),
    ]
    conn.executemany("INSERT INTO departments (name, base_fee) VALUES (?, ?)", departments)

    first_names = ["Arjun", "Priya", "Karthik", "Divya", "Rahul", "Sneha", "Vikram",
                   "Anjali", "Suresh", "Meena", "Ravi", "Lakshmi", "Ganesh", "Kavya"]
    last_names = ["Iyer", "Nair", "Menon", "Reddy", "Rao", "Sharma", "Pillai",
                  "Krishnan", "Subramanian", "Varma"]
    quals = {
        "Cardiology": "MD, DM Cardiology",
        "Neurology": "MD, DM Neurology",
        "Orthopedics": "MS Orthopedics",
        "Dermatology": "MD Dermatology",
        "General Medicine": "MD General Medicine",
    }

    name_i = 0
    doctor_id = 1
    schedules = []
    doctors_rows = []
    for branch_id in range(1, len(branches) + 1):
        for dept_id, (dept_name, base_fee) in enumerate(departments, start=1):
            doctors_per_dept = 2
            for _ in range(doctors_per_dept):
                fname = first_names[name_i % len(first_names)]
                lname = last_names[name_i % len(last_names)]
                name_i += 1
                fee = base_fee + (doctor_id % 3) * 100
                status = "ACTIVE" if doctor_id % 17 != 0 else "INACTIVE"  # a couple inactive
                doctors_rows.append(
                    (f"Dr. {fname} {lname}", branch_id, dept_id, quals[dept_name], fee, status)
                )

                # Working days: Mon-Sat (0-5), two sessions, 30 min slots.
                schedules.append((doctor_id, "0,1,2,3,4,5", "09:00", "13:00", 30))
                schedules.append((doctor_id, "0,1,2,3,4,5", "14:00", "17:00", 30))

                doctor_id += 1

    conn.executemany(
        "INSERT INTO doctors (name, branch_id, department_id, qualification, fee, doctor_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        doctors_rows,
    )

    # Expand the "days" shorthand above into individual day_of_week rows.
    expanded = []
    for doc_id, days_csv, start, end, slot_min in schedules:
        for d in days_csv.split(","):
            expanded.append((doc_id, int(d), start, end, slot_min))
    conn.executemany(
        "INSERT INTO doctor_schedule (doctor_id, day_of_week, start_time, end_time, slot_minutes) "
        "VALUES (?, ?, ?, ?, ?)",
        expanded,
    )
