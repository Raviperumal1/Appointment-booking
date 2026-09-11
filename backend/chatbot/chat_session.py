from backend.database.db import get_db_ctx
from backend.chatbot.conversation_log import resolve_chat_user
from backend.services.conversation_service import get_active_conversation, create_conversation


def _flatten_context(context: dict) -> dict:
    """Converts the nested DB JSON structure into the flat dictionary expected by booking_flow."""
    session = {}
    
    # 1. Conversation
    conv = context.get("conversation", {})
    if "current_state" in conv: session["state"] = conv["current_state"]
    if "language" in conv: session["lang"] = conv["language"]
    
    # 2. Booking
    booking = context.get("booking", {})
    for k in ["branch_id", "branch_name", "department_id", "department_name", "doctor_id", "doctor_name"]:
        if k in booking and booking[k] is not None: session[k] = booking[k]
    if "appointment_date" in booking: session["date"] = booking["appointment_date"]
    if "time_slot" in booking: session["time"] = booking["time_slot"]
        
    # 3. Patient
    patient = context.get("patient", {})
    if "name" in patient: session["patient_name"] = patient["name"]
    if "mobile" in patient: session["mobile"] = patient["mobile"]
    if "age" in patient: session["patient_age"] = patient["age"]
    if "gender" in patient: session["patient_gender"] = patient["gender"]
        
    # 4. Symptoms
    symptoms = context.get("symptoms", {})
    if "text" in symptoms: session["symptoms"] = symptoms["text"]
    if "reason" in symptoms: session["reason"] = symptoms["reason"]
        
    # 5. Options
    options = context.get("options", {})
    if "last_options" in options: session["_last_options"] = options["last_options"]
    
    # Maintain raw data just in case
    raw = context.get("_raw", {})
    for k, v in raw.items():
        if k not in session: session[k] = v
        
    if "state" not in session:
        session["state"] = "START"
        
    return session


def _structure_context(session: dict) -> dict:
    """Converts the flat booking_flow dictionary into the nested DB JSON structure."""
    context = {
        "conversation": {
            "language": session.get("lang", "en"),
            "status": "ACTIVE",
            "current_state": session.get("state", "START"),
            # We don't have turn_number tracking in the old flow natively, but we can preserve it if it was there
        },
        "booking": {
            "branch_id": session.get("branch_id"),
            "branch_name": session.get("branch_name"),
            "department_id": session.get("department_id"),
            "department_name": session.get("department_name"),
            "doctor_id": session.get("doctor_id"),
            "doctor_name": session.get("doctor_name"),
            "appointment_date": session.get("date"),
            "time_slot": session.get("time")
        },
        "patient": {
            "name": session.get("patient_name"),
            "mobile": session.get("mobile"),
            "age": session.get("patient_age"),
            "gender": session.get("patient_gender")
        },
        "symptoms": {
            "text": session.get("symptoms"),
            "reason": session.get("reason"),
            "captured": bool(session.get("symptoms")),
            "analysis": {
                "method": "keyword",
                "department_id": session.get("department_id"),
                "department_name": session.get("department_name")
            } if session.get("symptoms") else None
        },
        "options": {
            "last_options": session.get("_last_options", [])
        },
        "flags": {
            "symptoms_captured": bool(session.get("symptoms")),
            "department_selected": bool(session.get("department_id")),
            "doctor_selected": bool(session.get("doctor_id")),
            "date_selected": bool(session.get("date")),
            "time_selected": bool(session.get("time")),
            "patient_details_completed": bool(session.get("patient_name") and session.get("patient_age")),
            "booking_confirmed": session.get("state") == "BOOKING_COMPLETED"
        },
        # Store unmapped properties in raw
        "_raw": {k: v for k, v in session.items() if k not in [
            "state", "lang", "branch_id", "branch_name", "department_id", "department_name",
            "doctor_id", "doctor_name", "date", "time", "patient_name", "mobile",
            "patient_age", "patient_gender", "symptoms", "reason", "_last_options"
        ]}
    }
    
    # Remove None values strictly where requested, or leave them if preferred
    return context


def get_session(source: str, external_id: str) -> dict:
    """Returns the session data from ConversationMetadata."""
    with get_db_ctx() as db:
        chat_user_id = resolve_chat_user(db, source, external_id)
        db.commit()
        
        meta = get_active_conversation(db, chat_user_id)
        if not meta:
            meta = create_conversation(db, chat_user_id)
            db.commit()
            db.refresh(meta)
            
        return _flatten_context(meta.context)


def save_session(source: str, external_id: str, data: dict) -> None:
    with get_db_ctx() as db:
        chat_user_id = resolve_chat_user(db, source, external_id)
        db.commit()
        
        meta = get_active_conversation(db, chat_user_id)
        if meta:
            structured = _structure_context(data)
            
            # Sync root columns for searchability
            patient_name = data.get("patient_name")
            mobile = data.get("mobile")
            if patient_name: meta.patient_name = patient_name
            if mobile: meta.patient_mobile = mobile
            
            # Full replacement of context is safer here since structure is fully generated
            meta.context = structured
            
            db.commit()


def reset_session(source: str, external_id: str) -> dict:
    with get_db_ctx() as db:
        chat_user_id = resolve_chat_user(db, source, external_id)
        db.commit()
        
        meta = get_active_conversation(db, chat_user_id)
        if meta:
            context_copy = dict(meta.context)
            if "conversation" not in context_copy:
                context_copy["conversation"] = {}
            context_copy["conversation"]["status"] = "CANCELLED"
            context_copy["conversation"]["current_state"] = "CANCELLED"
            meta.context = context_copy
            db.commit()
            
    # Return fresh state
    return get_session(source, external_id)


def cleanup_expired() -> None:
    pass
