import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional
from dotenv import load_dotenv


load_dotenv()

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

# SMTP
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv(
    "SMTP_FROM",
    SMTP_USERNAME or "noreply@varuvi.example"
)

_twilio_client = None


def _get_twilio_client():
    """Lazily construct the Twilio client so the `twilio` package is only
    required if you actually configure credentials."""
    global _twilio_client
    if _twilio_client is not None:
        return _twilio_client
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return None
    from twilio.rest import Client  # imported here so a missing package
    _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _twilio_client


def send_sms(to_mobile: str, message: str) -> dict:
    """Sends via Twilio if configured, otherwise mocks with a console print.
    Returns a small status dict so callers can surface it if useful."""
    client = _get_twilio_client()
    if client is None:
        print(f"[MOCK SMS -> {to_mobile}] {message}")
        return {"channel": "sms", "mode": "mock", "to": to_mobile}

    to_number = to_mobile if to_mobile.startswith("+") else f"+91{to_mobile}"  # assumes India by default
    try:
        msg = client.messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=to_number)
        return {"channel": "sms", "mode": "twilio", "to": to_number, "sid": msg.sid}
    except Exception as exc:  # noqa: BLE001 - notification failures shouldn't break booking
        print(f"[TWILIO SEND FAILED -> {to_number}] {exc}")
        return {"channel": "sms", "mode": "error", "to": to_number, "error": str(exc)}


def send_email(to_email: Optional[str], subject: str, body: str) -> Optional[dict]:
    """Sends via SMTP if configured and an address was given; otherwise mocks
    (or does nothing if there's no email on file at all)."""
    if not to_email:
        return None
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
        print(f"[MOCK EMAIL -> {to_email}] Subject: {subject}\n{body}")
        return {"channel": "email", "mode": "mock", "to": to_email}

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        return {"channel": "email", "mode": "smtp", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        print(f"[EMAIL SEND FAILED -> {to_email}] {exc}")
        return {"channel": "email", "mode": "error", "to": to_email, "error": str(exc)}


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def booking_confirmed_messages(details: dict) -> dict:
    sms = (
        f"Varuvi: Appointment confirmed! Code {details['code']}. "
        f"{details['doctor']} ({details['branch']}) on {details['date']} at {details['time']}. "
        f"Please arrive 10 min early."
    )
    subject = f"Appointment Confirmed — {details['code']}"
    body = (
        f"Hi {details['patient_name']},\n\n"
        f"Your appointment is confirmed.\n\n"
        f"Appointment code : {details['code']}\n"
        f"Doctor           : {details['doctor']} ({details['department']})\n"
        f"Branch           : {details['branch']}\n"
        f"Date & time      : {details['date']} at {details['time']}\n"

        f"Please arrive 10 minutes early with any previous prescriptions or reports.\n"
        f"To cancel or reschedule, use your appointment code and mobile number on the "
        f"'Manage your booking' page.\n\n"
        f"— Varuvi"
    )
    return {"sms": sms, "subject": subject, "body": body}


def booking_cancelled_messages(details: dict) -> dict:
    sms = (
        f"Varuvi: Appointment {details['code']} on {details['date']} at {details['time']} "
        f"with {details['doctor']} has been cancelled. Book again anytime."
    )
    subject = f"Appointment Cancelled — {details['code']}"
    body = (
        f"Hi {details['patient_name']},\n\n"
        f"Your appointment has been cancelled as requested.\n\n"
        f"Appointment code : {details['code']}\n"
        f"Doctor           : {details['doctor']} ({details['department']})\n"
        f"Branch           : {details['branch']}\n"
        f"Was scheduled for: {details['date']} at {details['time']}\n\n"
        f"If this wasn't you, please contact the branch directly.\n\n"
        f"— Varuvi"
    )
    return {"sms": sms, "subject": subject, "body": body}


def booking_rescheduled_messages(details: dict) -> dict:
    sms = (
        f"Varuvi: Appointment {details['code']} moved from {details['old_date']} "
        f"{details['old_time']} to {details['date']} {details['time']} with {details['doctor']}."
    )
    subject = f"Appointment Rescheduled — {details['code']}"
    body = (
        f"Hi {details['patient_name']},\n\n"
        f"Your appointment has been rescheduled.\n\n"
        f"Appointment code : {details['code']}\n"
        f"Doctor           : {details['doctor']} ({details['department']})\n"
        f"Branch           : {details['branch']}\n"
        f"Previous slot    : {details['old_date']} at {details['old_time']}\n"
        f"New slot         : {details['date']} at {details['time']}\n"

        f"— Varuvi"
    )
    return {"sms": sms, "subject": subject, "body": body}


def reload_config():
    global TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    global SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM
    global _twilio_client

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else 587
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "noreply@varuvi.example")

    _twilio_client = None

def notify(event: str, details: dict, mobile: str, email: Optional[str] = None) -> dict:
    """event: 'booked' | 'cancelled' | 'rescheduled'"""
    builder = {
        "booked": booking_confirmed_messages,
        "cancelled": booking_cancelled_messages,
        "rescheduled": booking_rescheduled_messages,
    }[event]
    messages = builder(details)
    sms_result = send_sms(mobile, messages["sms"])
    email_result = send_email(email, messages["subject"], messages["body"])
    return {"sms": sms_result, "email": email_result, "preview": messages["sms"]}