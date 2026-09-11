# Hospital Appointment Booking — Full Stack Demo

A complete implementation of the booking flow:

```
Patient details -> Branch -> Department -> Doctor -> Date -> Time slot
  -> availability re-check -> (conflict -> suggest alternatives)
  -> book directly -> appointment code -> mock SMS/WhatsApp notification
```

**Payment is intentionally skipped** — the app books the slot as soon as it's
confirmed available, no payment step or gateway involved.

```
hospital-appointment/
├── backend/            FastAPI + SQLite
│   ├── main.py          API endpoints & booking logic
│   ├── database.py      schema + seed data + migrations
│   ├── auth.py           admin HTTP Basic Auth guard
│   ├── notifications.py  Twilio SMS + email sending, message templates
│   └── requirements.txt
└── frontend/           Plain HTML / CSS / JS (no build step)
    ├── index.html        patient booking wizard
    ├── style.css
    ├── app.js
    ├── manage.html       patient self-service cancel/reschedule
    ├── manage.js
    ├── admin.html        staff-only bookings dashboard
    ├── admin.css
    └── admin.js
```

## 1. Run the backend

```bash
cd backend
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

On first run it creates `backend/appointments.db` (SQLite) and seeds it with:

- 5 hospital branches
- 5 departments (Cardiology, Neurology, Orthopedics, Dermatology, General Medicine)
- 2 doctors per branch/department (50 doctors total, a couple marked `INACTIVE`
  on purpose so you can see the "active doctors only" filter working)
- Working hours Mon–Sat, 09:00–13:00 and 14:00–17:00, 30-minute slots

If you already have an `appointments.db` from an earlier version of this
project (before the `email` column existed), it's migrated automatically on
the next startup — no need to delete it.

Check it's up: open http://localhost:8000/api/health or the interactive docs
at http://localhost:8000/docs.

## 2. Run the frontend

No build tooling needed — just serve the static files so `fetch()` works
correctly (opening `index.html` directly via `file://` will hit CORS issues
in some browsers, so use a tiny local server):

```bash
cd frontend
python -m http.server 5500
```

Then open http://localhost:5500 in your browser.

If your backend runs somewhere other than `http://localhost:8000`, change
the `API_BASE` constant at the top of `app.js`, `admin.js`, **and** `manage.js`.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/branches` | List hospital branches |
| GET | `/api/departments?branch_id=` | Departments with active doctors at a branch |
| GET | `/api/departments/all` | Every department, unscoped (used by admin filters) |
| GET | `/api/doctors?branch_id=&department_id=` | Active doctors matching branch + department |
| GET | `/api/doctors/{id}/dates?days=14` | Upcoming dates with free/full status |
| GET | `/api/doctors/{id}/slots?date=YYYY-MM-DD` | Time slots for a date, AVAILABLE/BOOKED |
| POST | `/api/appointments/book` | Book a slot directly (see body below) |
| GET | `/api/appointments/{code}` | Look up a booked appointment (no ownership check) |
| GET | `/api/appointments/{code}/lookup?mobile=` | Self-service lookup, requires matching mobile |
| POST | `/api/appointments/{code}/cancel` | Patient cancel — body `{"mobile": "..."}` must match |
| POST | `/api/appointments/{code}/reschedule` | Patient reschedule — see body below |

`POST /api/appointments/book` body:

```json
{
  "patient_name": "Kavya Subramanian",
  "mobile": "9876543210",
  "email": "kavya@example.com",
  "address": "12 Lake View Road, Chennai",
  "reason": "Follow-up",
  "branch_id": 1,
  "department_id": 1,
  "doctor_id": 3,
  "appointment_date": "2026-08-10",
  "time_slot": "10:00"
}
```

`email` is optional — leave it out (or `null`) for SMS-only confirmations.

Response is either:

```json
{ "status": "BOOKED", "appointment_code": "APT2608100234", "summary": { ... },
  "notification_sent_to": "9876543210", "notification_preview": "..." }
```

or, if someone else just took the slot:

```json
{ "status": "CONFLICT", "message": "...",
  "alternatives": {
    "next_available_time": "10:30",
    "previous_available_time": "09:30",
    "next_available_date": "2026-08-11",
    "next_available_date_slots": ["09:00", "09:30"]
  } }
```

The frontend renders `alternatives` as clickable chips so the patient can
pick one without starting over. The same `CONFLICT` shape comes back from
`/reschedule` if the new slot gets taken in the meantime.

## Cancel & reschedule (patient self-service)

**`frontend/manage.html`** — linked from the booking wizard's footer — lets
a patient look up their booking with just the **appointment code + the
mobile number they booked with**, then cancel it or move it to a new
date/time with the same doctor. Both actions are also verified server-side
(`_get_owned_appointment` in `main.py` checks the mobile matches before
allowing anything), so a code alone isn't enough to touch someone else's
booking.

`POST /api/appointments/{code}/reschedule` body:

```json
{ "mobile": "9876543210", "appointment_date": "2026-08-12", "time_slot": "11:00" }
```

Rescheduling reuses the exact same conflict-detection and alternative-slot
logic as a fresh booking, including the race-safe unique index — if two
people try to grab the same new slot at once, the loser gets a `CONFLICT`
response with alternatives instead of corrupting the schedule.

Staff can still cancel any booking (no mobile match required) from the
admin dashboard, since that's already behind login.

## SMS & email notifications (Twilio + SMTP)

`backend/notifications.py` sends a booking confirmation, cancellation, or
reschedule notice on every relevant action. Each channel is optional and
**falls back to a harmless console `[MOCK ...]` print** if it isn't
configured, so the app works out of the box without any credentials.

To send real SMS via Twilio, set:

```bash
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=your_auth_token
export TWILIO_FROM_NUMBER=+15551234567     # your Twilio number
```

Mobile numbers without a leading `+` are assumed to be Indian (`+91`) —
adjust `send_sms()` in `notifications.py` if you're serving a different
country.

To send real confirmation emails (only sent when the patient provided an
email address), set:

```bash
export SMTP_HOST=smtp.yourprovider.com
export SMTP_PORT=587
export SMTP_USERNAME=your_smtp_username
export SMTP_PASSWORD=your_smtp_password
export SMTP_FROM="Varuvi <noreply@yourdomain.com>"
```

Message wording for all three notification types (booked / cancelled /
rescheduled) lives in the `*_messages()` functions near the bottom of
`notifications.py` — edit those to change what patients actually see.

## Admin dashboard

A separate, staff-only page at **`frontend/admin.html`** shows booking stats
and lets staff search/filter/cancel bookings. It's a different HTML file
from the patient wizard on purpose — it's not linked from `index.html`, so
patients browsing the booking flow never see it.

Open it directly: http://localhost:5500/admin.html (adjust the port to
whatever you used for `python -m http.server`).

**Login** uses HTTP Basic Auth, checked by `backend/auth.py`. Set real
credentials via environment variables before running the backend:

```bash
export ADMIN_USERNAME=your_admin_name
export ADMIN_PASSWORD=a_strong_password
uvicorn main:app --reload --port 8000
```

If you don't set these, it falls back to `admin` / `admin123` for local
testing only — **do not leave the defaults in place anywhere but your own
machine.**

The dashboard shows:

- Stat cards: active bookings, today's bookings, cancelled count, all-time total
- Breakdowns: bookings by branch, by department, and the busiest doctors
- A filterable, paginated table of every booking (search by name / mobile /
  appointment code, or filter by status, branch, department, date range)
- A **Cancel** button on any active booking, which frees that slot for
  other patients immediately

Admin-only endpoints (all require the `Authorization: Basic ...` header):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/me` | Verifies credentials (used by the login form) |
| GET | `/api/admin/stats` | Counts + breakdowns for the stat cards |
| GET | `/api/admin/appointments?...` | Filtered, paginated booking list |
| POST | `/api/admin/appointments/{code}/cancel` | Staff-initiated cancellation (no mobile check) |

Credentials are kept in `sessionStorage` in the browser (cleared when the
tab closes) and sent only to your own backend — never written to
`localStorage` or any third party.

> HTTP Basic Auth over plain HTTP sends credentials base64-encoded, which is
> **not encrypted** — fine for local development, but put the real deployment
> behind HTTPS before staff log in from anywhere but localhost.

## Concurrency safety

Two patients hitting the same doctor/date/time at once — whether both are
booking fresh or one is rescheduling into a slot someone else just took —
is handled by a **partial unique index** in SQLite:

```sql
CREATE UNIQUE INDEX idx_unique_booked_slot
    ON appointments (doctor_id, appointment_date, time_slot)
    WHERE status = 'BOOKED';
```

The app checks availability, then inserts/updates; if a race means someone
else's write lands first, SQLite raises `IntegrityError` and the API
returns the same `CONFLICT` + alternatives response instead of
double-booking.

## Notes / things to swap out for production

- CORS is wide open (`allow_origins=["*"]`) — restrict this to your real
  frontend origin.
- SQLite is fine for a demo; swap for Postgres/MySQL for real concurrent load
  (the partial-unique-index trick has an equivalent in both).
- Patient self-service (`manage.html`) only checks that the mobile number
  matches — fine for a demo, but a production system handling real patient
  data would want OTP verification (e.g. via the same Twilio account) before
  allowing a cancel/reschedule.
- No staff accounts beyond the single shared admin login exist — every
  admin action is attributed to "admin", not an individual staff member.
