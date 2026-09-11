import re
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from backend.database.db import get_db_ctx
from backend.utils.time_utils import now_iso
from backend.database.models import ChatUser, ChatUserChannel, ConversationMessage, Patient

VALID_SOURCES = {"WEB", "WHATSAPP", "CHATBOT"}


def ensure_tables() -> None:
    # Tables are created by Base.metadata.create_all(bind=engine) in init_db().
    pass


from backend.utils.mobile import normalize_mobile_number


def normalize_mobile(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return normalize_mobile_number(raw)


def _find_patient_by_mobile(db, mobile: str):
    return db.query(Patient).filter(Patient.mobile.like(f"%{mobile}")).first()


def _create_chat_user(db, mobile: Optional[str], name: Optional[str]) -> int:
    patient_id = None
    patient_name = None
    if mobile:
        patient = _find_patient_by_mobile(db, mobile)
        if patient:
            patient_id = patient.id
            patient_name = patient.full_name
            
    cu = ChatUser(
        mobile=mobile,
        name=name or patient_name,
        patient_id=patient_id,
        created_at=now_iso()
    )
    db.add(cu)
    db.flush()
    return cu.id


def _merge_chat_users(db, from_id: int, into_id: int) -> None:
    if from_id == into_id:
        return
    db.query(ConversationMessage).filter(ConversationMessage.chat_user_id == from_id).update({"chat_user_id": into_id})
    db.query(ChatUserChannel).filter(ChatUserChannel.chat_user_id == from_id).update({"chat_user_id": into_id})
    # Import locally or at top to avoid circular imports.
    from backend.database.models import ConversationMetadata
    db.query(ConversationMetadata).filter(ConversationMetadata.chat_user_id == from_id).update({"chat_user_id": into_id})
    db.query(ChatUser).filter(ChatUser.id == from_id).delete()


def link_patient(mobile: Optional[str], patient_id: int, name: Optional[str] = None) -> None:
    mobile = normalize_mobile(mobile)
    if not mobile:
        return
    with get_db_ctx() as db:
        user = db.query(ChatUser).filter(ChatUser.mobile == mobile).first()
        if user:
            user.patient_id = patient_id
            if name and not user.name:
                user.name = name
            db.commit()


def resolve_chat_user(
    db,
    source: str,
    external_id: str,
    mobile: Optional[str] = None,
    name: Optional[str] = None,
) -> int:
    mobile = normalize_mobile(mobile)
    existing_channel = db.query(ChatUserChannel).filter_by(source=source, external_id=external_id).first()

    if not mobile:
        if existing_channel:
            return existing_channel.chat_user_id
        new_id = _create_chat_user(db, mobile=None, name=name)
        db.add(ChatUserChannel(chat_user_id=new_id, source=source, external_id=external_id))
        return new_id

    canonical = db.query(ChatUser).filter_by(mobile=mobile).first()
    if canonical:
        canonical_id = canonical.id
        if name and not canonical.name:
            canonical.name = name
        if not canonical.patient_id:
            patient = _find_patient_by_mobile(db, mobile)
            if patient:
                canonical.patient_id = patient.id
                if not canonical.name:
                    canonical.name = patient.full_name
    else:
        canonical_id = _create_chat_user(db, mobile=mobile, name=name)

    if existing_channel and existing_channel.chat_user_id != canonical_id:
        _merge_chat_users(db, from_id=existing_channel.chat_user_id, into_id=canonical_id)
        existing_channel.chat_user_id = canonical_id
    elif not existing_channel:
        db.add(ChatUserChannel(chat_user_id=canonical_id, source=source, external_id=external_id))

    return canonical_id


def reset_channel(source: str, external_id: str) -> None:
    with get_db_ctx() as db:
        db.query(ChatUserChannel).filter_by(source=source, external_id=external_id).delete()
        db.commit()


def log_message(
    source: str,
    external_id: str,
    sender: str,
    text: str,
    mobile: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    if not text:
        return
    source = source if source in VALID_SOURCES else "WEB"
    sender = "USER" if str(sender).upper() == "USER" else "BOT"

    with get_db_ctx() as db:
        chat_user_id = resolve_chat_user(db, source, external_id, mobile=mobile, name=name)
        db.add(ConversationMessage(
            chat_user_id=chat_user_id,
            source=source,
            sender=sender,
            text=text,
            timestamp=now_iso()
        ))
        db.commit()


def log_turn(
    source: str,
    external_id: str,
    user_text: Optional[str],
    bot_text: Optional[str],
    mobile: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    if user_text:
        log_message(source, external_id, "USER", user_text, mobile=mobile, name=name)
    if bot_text:
        log_message(source, external_id, "BOT", bot_text, mobile=mobile)


def get_history(source: str, external_id: str) -> list[dict]:
    with get_db_ctx() as db:
        channel = db.query(ChatUserChannel).filter_by(source=source, external_id=external_id).first()
        if not channel:
            return []
            
        messages = db.query(ConversationMessage).filter_by(chat_user_id=channel.chat_user_id).order_by(ConversationMessage.id).all()
        return [{"source": m.source, "sender": m.sender, "text": m.text, "timestamp": m.timestamp} for m in messages]