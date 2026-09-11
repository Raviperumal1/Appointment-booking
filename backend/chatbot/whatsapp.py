import os
import sys
from pathlib import Path

import requests
from fastapi import APIRouter, Request, Response

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from . import chat_session, booking_flow, conversation_log
from backend.utils.mobile import normalize_mobile_number


router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
GRAPH_API_VERSION = "v25.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


# ---------------------------------------------------------------------------
# 1) Webhook verification handshake (Meta calls this once when you configure
#    the webhook URL in the App Dashboard)
# ---------------------------------------------------------------------------

@router.get("")
def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


# ---------------------------------------------------------------------------
# 2) Incoming messages
# ---------------------------------------------------------------------------

@router.post("")
async def receive_message(request: Request):
    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            # Delivery/read status callbacks land here too — nothing to do.
            return {"status": "ignored"}

        message = messages[0]
        sender = message["from"]  # wa_id, e.g. "919876543210"

        text = None
        option_id = None
        option_label = None  # human-readable version of a button/list tap, for the conversation log

        if message["type"] == "text":
            text = message["text"]["body"]
        elif message["type"] == "interactive":
            interactive = message["interactive"]
            if interactive["type"] == "button_reply":
                option_id = interactive["button_reply"]["id"]
                option_label = interactive["button_reply"].get("title")
            elif interactive["type"] == "list_reply":
                option_id = interactive["list_reply"]["id"]
                option_label = interactive["list_reply"].get("title")
        else:
            _send_text(sender, "Sorry, I can only understand text messages and menu taps right now.")
            return {"status": "ok"}

        normalized_phone = normalize_mobile_number(sender)
        session = chat_session.get_session("WHATSAPP", sender)
        reply = booking_flow.handle_message(session, text=text, option_id=option_id, contact_phone=normalized_phone)
        chat_session.save_session("WHATSAPP", sender, session)

        conversation_log.log_turn(
            source="WHATSAPP",
            external_id=sender,
            user_text=text or option_label or option_id,
            bot_text=reply.get("text"),
            mobile=normalized_phone,  # WhatsApp always gives us the real phone number
            name=session.get("patient_name"),
        )

        _send_reply(sender, reply)
        return {"status": "ok"}

    except Exception as exc:  # noqa: BLE001 — webhook must always 200 so Meta doesn't retry-storm
        print(f"[whatsapp webhook] error: {exc}")
        return {"status": "error", "detail": str(exc)}


# ---------------------------------------------------------------------------
# 3) Sending messages back via the Graph API
# ---------------------------------------------------------------------------

def _headers():
    return {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}


def _send_reply(to: str, reply: dict):
    options = reply.get("options") or []
    text = reply["text"]

    if not options:
        _send_text(to, text)
    elif len(options) <= 3:
        _send_buttons(to, text, options)
    else:
        _send_list(to, text, options)


def _send_text(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    _post(payload)


def _send_buttons(to: str, body: str, options: list):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": o["id"], "title": o["title"][:20]}}
                    for o in options
                ]
            },
        },
    }
    _post(payload)


def _send_list(to: str, body: str, options: list):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": "Choose an option",
                "sections": [
                    {
                        "title": "Options",
                        "rows": [
                            {
                                "id": o["id"],
                                "title": o["title"][:24],
                                "description": o.get("description", "")[:72],
                            }
                            for o in options[:10]
                        ],
                    }
                ],
            },
        },
    }
    _post(payload)


def _post(payload: dict):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[whatsapp] WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set — message not sent:", payload)
        return
    resp = requests.post(GRAPH_URL, headers=_headers(), json=payload, timeout=15)
    if resp.status_code >= 400:
        print(f"[whatsapp] send failed ({resp.status_code}): {resp.text}")


def send_appointment_notification(to: str, body: str) -> dict:
    """Best-effort outbound WhatsApp notification for a confirmed booking.
    Credentials are read from environment configuration; delivery failures are
    returned to the caller so they can be audited without failing the booking.
    """
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"channel": "whatsapp", "mode": "error", "to": to, "error": "WhatsApp is not configured"}
    try:
        response = requests.post(GRAPH_URL, headers=_headers(), json={
            "messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body},
        }, timeout=15)
        response.raise_for_status()
        return {"channel": "whatsapp", "mode": "meta", "to": to}
    except Exception as exc:  # external delivery must never break booking
        print(f"[whatsapp] appointment notification failed: {exc}")
        return {"channel": "whatsapp", "mode": "error", "to": to, "error": str(exc)}
