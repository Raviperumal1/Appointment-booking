import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from . import chat_session, booking_flow, conversation_log

router = APIRouter(prefix="/chat/webchat", tags=["webchat"])


class WebchatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Stable per-browser-tab identifier from the frontend")
    message: Optional[str] = None      # free text typed by the user
    option_id: Optional[str] = None    # id of the button/chip the user tapped


class WebchatReply(BaseModel):
    text: str
    options: list
    done: bool


@router.post("", response_model=WebchatReply)
def webchat_message(req: WebchatRequest):
    session = chat_session.get_session("WEB", req.session_id)

    if session.get("state", "START") == "START":
        conversation_log.reset_channel("WEB", req.session_id)

    # Resolve a button/list tap to the text it actually showed
    option_label = None

    if req.option_id and not req.message:
        option_label = next(
            (
                o["title"]
                for o in session.get("_last_options", [])
                if o["id"] == req.option_id
            ),
            None,
        )

    # ---------------------------------------------------------
    # IMPORTANT WEBCHAT FIX
    # ---------------------------------------------------------

    option_id = req.option_id

    # If user typed something, it is free-text input.
    # Ignore any stale option_id sent by the frontend.
    if req.message and req.message.strip():
        option_id = None

    reply = booking_flow.handle_message(
        session,
        text=req.message,
        option_id=option_id,
        contact_phone=None,
    )

    chat_session.save_session(
        "WEB",
        req.session_id,
        session
    )

    conversation_log.log_turn(
        source="WEB",
        external_id=req.session_id,
        user_text=req.message or option_label or (f"[selected: {req.option_id}]" if req.option_id else None),
        bot_text=reply.get("text"),
        mobile=session.get("mobile"),  # becomes known partway through the booking flow — auto-merges once it does
        name=session.get("patient_name"),
    )

    return reply


@router.post("/reset", response_model=WebchatReply)
def webchat_reset(req: WebchatRequest):
    # Explicitly starting a new conversation on this channel — same reason
    # as above: don't let it inherit whoever this session_id belonged to
    # before.
    conversation_log.reset_channel("WEB", req.session_id)

    session = chat_session.reset_session("WEB", req.session_id)
    reply = booking_flow.handle_message(session, text="hi", option_id=None, contact_phone=None)
    chat_session.save_session("WEB", req.session_id, session)

    conversation_log.log_turn(
        source="WEB",
        external_id=req.session_id,
        user_text="hi",
        bot_text=reply.get("text"),
    )

    return reply