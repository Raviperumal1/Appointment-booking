from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from backend.database.models import ConversationMetadata, ConversationState, ConversationStatus, ConversationMessage
from typing import Optional, Dict, Any, List
import datetime

def deep_update(d: Dict, u: Dict) -> Dict:
    for k, v in u.items():
        if isinstance(v, dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def get_active_conversation(db: Session, chat_user_id: int) -> Optional[ConversationMetadata]:
    # We look for ACTIVE status inside the context JSON
    # For SQLite JSON compatibility across different engines, we filter in memory or simply fetch latest
    # A robust production solution with PostgreSQL would use `context->'conversation'->>'status' == 'ACTIVE'`
    metas = db.query(ConversationMetadata).filter(
        ConversationMetadata.chat_user_id == chat_user_id
    ).order_by(ConversationMetadata.id.desc()).all()
    
    for meta in metas:
        status = meta.context.get("conversation", {}).get("status")
        if status == ConversationStatus.ACTIVE.value:
            return meta
    return None

def create_conversation(db: Session, chat_user_id: int, language: str = "en") -> ConversationMetadata:
    default_context = {
        "conversation": {
            "conversation_id": f"conv_{int(datetime.datetime.now().timestamp())}_{chat_user_id}",
            "language": language,
            "status": ConversationStatus.ACTIVE.value,
            "current_state": ConversationState.START.value,
            "previous_state": None,
            "turn_number": 0,
            "expected_input": None
        },
        "booking": {},
        "patient": {},
        "symptoms": {},
        "messages": {
            "last_user_message_id": None,
            "last_bot_message_id": None
        },
        "flags": {},
        "options": {}
    }
    
    meta = ConversationMetadata(
        chat_user_id=chat_user_id,
        context=default_context
    )
    db.add(meta)
    db.flush()
    return meta

def update_conversation_context(db: Session, meta: ConversationMetadata, updates: Dict[str, Any]):
    meta.context = deep_update(meta.context, updates)
    flag_modified(meta, "context")

def save_message(db: Session, chat_user_id: int, source: str, sender: str, text: str) -> ConversationMessage:
    msg = ConversationMessage(
        chat_user_id=chat_user_id,
        source=source,
        sender=sender,
        text=text,
        timestamp=datetime.datetime.now().isoformat()
    )
    db.add(msg)
    db.flush()
    return msg

def get_conversation_history(db: Session, metadata: ConversationMetadata) -> List[Dict[str, Any]]:
    # Simple bounds: from created_at
    messages = db.query(ConversationMessage).filter(
        ConversationMessage.chat_user_id == metadata.chat_user_id,
        ConversationMessage.timestamp >= metadata.created_at.isoformat()
    ).order_by(ConversationMessage.id.asc()).all()

    print(f"messages: {messages}")

    history = []
    current_turn = {"user": None, "bot": None}
    turn_num = 1
    
    for msg in messages:
        if msg.sender == "USER":
            if current_turn["user"] is not None:
                history.append({"turn": turn_num, "user": current_turn["user"], "bot": current_turn["bot"]})
                turn_num += 1
                current_turn = {"user": msg.text, "bot": None}
            else:
                current_turn["user"] = msg.text
        elif msg.sender == "BOT":
            if current_turn["bot"] is not None:
                current_turn["bot"] += "\n" + msg.text
            else:
                current_turn["bot"] = msg.text
                
    if current_turn["user"] is not None:
        history.append({"turn": turn_num, "user": current_turn["user"], "bot": current_turn["bot"]})
        
    return history

def process_message(db: Session, chat_user_id: int, source: str, text: str) -> Dict[str, Any]:
    # 1. Save user message
    user_msg = save_message(db, chat_user_id, source, "USER", text)
    
    # 2. Find/create active conversation
    meta = get_active_conversation(db, chat_user_id)
    if not meta:
        meta = create_conversation(db, chat_user_id)
        
    # 3. Read current context
    ctx = meta.context
    conv_ctx = ctx.get("conversation", {})
    current_state = conv_ctx.get("current_state")
    
    # Process State (Mock Example)
    bot_response_text = ""
    next_expected_input = None
    next_state = current_state
    
    updates = {
        "conversation": {
            "previous_state": current_state
        },
        "messages": {
            "last_user_message_id": user_msg.id
        }
    }
    
    if current_state == ConversationState.START.value:
        bot_response_text = "Hi! Welcome to our hospital. How can I help you today?"
        next_state = ConversationState.SELECT_BRANCH.value
        next_expected_input = "branch"
        
    elif current_state == ConversationState.SELECT_BRANCH.value:
        bot_response_text = "Sure! Which branch would you like to visit?"
        next_state = ConversationState.ANALYZE_SYMPTOMS.value
        next_expected_input = "symptoms"
        updates["booking"] = {"branch_id": 1, "branch_name": "City Central Hospital"} # mock mapping
        
    elif current_state == ConversationState.ANALYZE_SYMPTOMS.value:
        bot_response_text = "Based on your symptoms, Cardiology may be suitable. What is your full name?"
        next_state = ConversationState.ASK_NAME.value
        next_expected_input = "patient_name"
        updates["booking"] = {"department_id": 2, "department_name": "Cardiology"} # mock
        updates["symptoms"] = {
            "text": text,
            "analysis": {"method": "keyword", "department_id": 2, "department_name": "Cardiology"}
        }
        
    elif current_state == ConversationState.ASK_NAME.value:
        bot_response_text = "Thank you. Booking completed (mock)."
        next_state = ConversationState.BOOKING_COMPLETED.value
        updates["patient"] = {"name": text}
        meta.patient_name = text # Sync normal column
        updates["conversation"]["status"] = ConversationStatus.COMPLETED.value
        
    else:
        bot_response_text = "Conversation has ended or state unknown."

    # Generate and save bot message
    bot_msg = save_message(db, chat_user_id, source, "BOT", bot_response_text)
    
    updates["conversation"]["current_state"] = next_state
    updates["conversation"]["expected_input"] = next_expected_input
    updates["conversation"]["turn_number"] = conv_ctx.get("turn_number", 0) + 1
    updates["messages"]["last_bot_message_id"] = bot_msg.id
    
    # 4. Update JSON context
    update_conversation_context(db, meta, updates)
    db.commit()
    db.refresh(meta)
    
    return {
        "conversation_id": meta.id,
        "turn_number": meta.context["conversation"]["turn_number"],
        "user_message": {"id": user_msg.id, "text": user_msg.text},
        "bot_message": {"id": bot_msg.id, "text": bot_msg.text},
        "state": {
            "previous": meta.context["conversation"]["previous_state"],
            "current": meta.context["conversation"]["current_state"]
        },
        "booking": meta.context.get("booking", {}),
        "language": meta.context["conversation"].get("language", "en"),
        "next_expected_input": next_expected_input
    }

def reset_conversation(db: Session, chat_user_id: int):
    meta = get_active_conversation(db, chat_user_id)
    if meta:
        update_conversation_context(db, meta, {
            "conversation": {
                "status": ConversationStatus.CANCELLED.value,
                "current_state": ConversationState.CANCELLED.value
            }
        })
        db.commit()
