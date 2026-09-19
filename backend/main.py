import os
import random
import re
import string
import sys
import csv
import io
import zipfile
import xml.etree.ElementTree as ET
import uuid
import json
import queue
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict
from pydantic import BaseModel

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from backend.utils.mobile import normalize_mobile_number
from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from backend.database.models import (
    SymptomAnalysisRequest, BookRequest, CancelRequest, RescheduleRequest,
    BranchCreateRequest, BranchUpdateRequest, BranchStatusRequest,
    DepartmentCreateRequest, DepartmentUpdateRequest,
    DoctorCreateRequest, DoctorUpdateRequest, DoctorStatusRequest,
    DoctorScheduleRequest, SpecialAvailabilityRequest,
    PatientRegisterRequest, PatientLoginRequest, GoogleAuthRequest,
    PatientProfileUpdate,
    PatientImportCommitRequest,
    CreatePrescriptionRequest, CreateMedicalReportRequest, CompleteAppointmentRequest,

    RolePermissionsUpdate, RoleCreateRequest,
    NotificationConfig, WhatsAppConfig, AIProviderConfig,
    UserListResponse, UserCreateRequest, UserUpdateRequest, UserPasswordUpdateRequest
)

from backend import notifications
from backend.database.db import init_db, get_db
from backend.auth.patient_auth import hash_password, verify_password, password_needs_upgrade, create_access_token, \
    decode_access_token, \
    get_current_patient_id
from backend.services.authorization import Principal, require_permission, assert_report_access, audit, \
    clear_permission_cache
from backend.services.branch_service import (
    create_branch,
    update_branch,
    update_branch_status,
    delete_branch,
)
from backend.services.doctor_service import (
    classify_slots,
    create_doctor,
    delete_doctor,
    doctor_exists_active,
    find_alternatives,
    get_available_departments,
    list_doctors_with_availability,
    list_doctors_for_branch_department,
    slots_for_date,
    update_doctor,
    update_doctor_status,
)
from backend.utils.time_utils import now_iso


try:
    from google import genai
except ImportError:  # optional dependency for AI-powered triage helpers
    genai = None

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
except ImportError:  # optional dependency for Google Sign-In
    id_token = None
    google_requests = None

import ollama

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

import traceback
import logging

from backend.core.logging_config import setup_logging
from backend.core.middleware import RequestLoggingMiddleware

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Hospital Appointment Booking API", version="1.0.0")
app.add_middleware(RequestLoggingMiddleware)

from backend.chatbot.webchat import router as webchat_router
from backend.chatbot import whatsapp as whatsapp_module, conversation_log
from backend.chatbot.whatsapp import router as whatsapp_router

app.include_router(whatsapp_router)
app.include_router(webchat_router)
# ---------------------------------------------------------------------------
# Advanced Conversation Metadata Endpoints
# ---------------------------------------------------------------------------
from backend.database.models import (
    ConversationMessageRequest,
    ConversationTurnResponse,
    ConversationHistoryItem
)
from backend.services.conversation_service import (
    process_message,
    get_active_conversation,
    get_conversation_history,
    reset_conversation
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import os
    env = os.getenv("ENVIRONMENT", "production")
    if env == "development":
        detail = f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
    else:
        detail = "An unexpected internal server error occurred. Please try again later."
    
    # Log the full error on the server side
    logger.exception(f"Unhandled Exception: {exc}")
    
    return JSONResponse(
        status_code=500,
        content={"detail": detail}
    )

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

from backend.auth.auth import router as auth_router

app.include_router(auth_router)

DATE_LOOKAHEAD_DAYS = 5

# A patient can't book a slot that's already started, or one starting so soon
# there's no realistic time to arrive/prepare. This is the minimum lead time
# (in minutes) between "now" and a bookable slot's start time, for TODAY only
# — future dates are unaffected.
MIN_LEAD_MINUTES = 10
PATIENT_IMPORT_PREVIEWS = {}
MEDICAL_UPLOAD_DIR = Path(os.getenv("MEDICAL_UPLOAD_DIR", str(Path(__file__).parent / "private_uploads"))).resolve()
MAX_MEDICAL_FILE_BYTES = 10 * 1024 * 1024


def check_gpu_availability():
    try:
        import torch
        if torch.cuda.is_available():
            logger.info(f"GPU DETECTED: {torch.cuda.get_device_name(0)}")
            logger.info("Server AI models will utilize the GPU.")
        else:
            logger.info("NO GPU DETECTED.")
            logger.info("Server AI models will fall back to running on CPU.")
    except ImportError:
        logger.info("PyTorch is not installed. Skipping Python-level GPU check.")
        logger.info("(Note: Ollama still automatically checks for GPUs on its own!)")


@app.on_event("startup")
def on_startup():
    logger.info("Application starting")
    check_gpu_availability()
    init_db()
    conversation_log.ensure_tables()
    logger.info("Application startup completed")

@app.on_event("shutdown")
def on_shutdown():
    logger.info("Application shutdown started")
    # Cleanups would go here
    logger.info("Application shutdown completed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_sync_sse_clients = set()

@app.get("/events")
def sse_events(request: Request):
    q = queue.Queue()
    _sync_sse_clients.add(q)
    def event_generator():
        try:
            while True:
                try:
                    data = q.get(timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            _sync_sse_clients.discard(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

def broadcast_event_sync(event_type: str, payload: dict):
    data = {"event": event_type, "payload": payload}
    for q in list(_sync_sse_clients):
        q.put(data)

def gen_appointment_code() -> str:
    stamp = datetime.now().strftime("%y%m%d")
    suffix = "".join(random.choices(string.digits, k=4))
    return f"APT{stamp}{suffix}"


def _upsert_booking_patient(db: Session, req: BookRequest) -> int:
    """Reuse the existing patient record by mobile for web/chat bookings."""
    from backend.database.models import Patient
    req.mobile = normalize_mobile_number(req.mobile)
    patient = db.query(Patient).filter(Patient.mobile == req.mobile).first()
    if patient:
        patient.full_name = req.patient_name
        patient.age = req.age
        patient.branch_id = req.branch_id
        patient.department_id = req.department_id
        patient.symptoms = req.reason
        if req.email:
            patient.email = req.email
        db.commit()
        return patient.id
    suffix = "".join(random.choices(string.digits, k=8))
    new_patient = Patient(
        patient_id=f"PAT{suffix}",
        username=f"booking_{suffix}",
        password_hash="!BOOKING_ONLY!",
        full_name=req.patient_name,
        dob="",
        gender=req.gender or "UNSPECIFIED",
        mobile=req.mobile,
        email=req.email,
        address=req.address or "Not provided",
        age=req.age,
        branch_id=req.branch_id,
        department_id=req.department_id,
        symptoms=req.reason
    )
    db.add(new_patient)
    db.flush()
    return new_patient.id


def _record_notification(db: Session, appointment_id: int, recipient_type: str, recipient: str, result: Optional[dict]):
    if result is None:
        return
    status = "FAILED" if result.get("mode") == "error" else "SENT"
    from backend.database.models import NotificationLog
    log = NotificationLog(
        appointment_id=appointment_id,
        recipient_type=recipient_type,
        channel=result.get("channel", "unknown"),
        recipient=recipient,
        status=status,
        error_message=result.get("error")
    )
    db.add(log)
    db.commit()


PATIENT_EXPORT_COLUMNS = ["Patient ID", "Name", "Age", "Mobile", "Branch", "Department", "Symptoms",
                          "Registration Date", "Status", "Email"]


def _xlsx_bytes(headers: list, rows: list) -> bytes:
    """Small dependency-free XLSX writer using inline strings."""

    def cell(col, row, value):
        ref = f"{chr(65 + col)}{row}"
        value = "" if value is None else str(value)
        escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    sheet_rows = []
    for row_number, values in enumerate([headers, *rows], 1):
        sheet_rows.append(
            f'<row r="{row_number}">' + "".join(cell(i, row_number, v) for i, v in enumerate(values)) + "</row>")
    sheet = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(
        sheet_rows) + "</sheetData></worksheet>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml",
                         '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Patients" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
                         '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


def _read_import_rows(raw: bytes, filename: str) -> list:
    if filename.lower().endswith(".csv"):
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Upload a CSV or XLSX file")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            parsed = [["".join(cell.itertext()) for cell in row.findall("x:c", ns)] for row in
                      root.findall(".//x:row", ns)]
        if not parsed:
            return []
        return [dict(zip(parsed[0], values)) for values in parsed[1:]]
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid XLSX file: {exc}")


def _validate_patient_import(conn, rows: list) -> tuple:
    required = {"Name", "Age", "Mobile", "Branch", "Department", "Symptoms"}
    if not rows:
        raise HTTPException(status_code=400, detail="The import file has no data rows")
    missing = required - set(rows[0])
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(sorted(missing))}")
    branch_names = {r["name"].casefold(): r["id"] for r in conn.execute("SELECT id, name FROM branches").fetchall()}
    department_names = {r["name"].casefold(): r["id"] for r in
                        conn.execute("SELECT id, name FROM departments").fetchall()}
    seen_mobiles, valid, errors = set(), [], []
    for index, row in enumerate(rows, 2):
        mobile = (row.get("Mobile") or "").strip()
        try:
            age = int((row.get("Age") or "").strip())
        except ValueError:
            age = 0
        if not (row.get("Name") or "").strip() or not mobile or not (row.get("Symptoms") or "").strip():
            errors.append({"row": index, "error": "Name, mobile, and symptoms are required"});
            continue
        if not re.fullmatch(r"\+?\d{7,15}", mobile):
            errors.append({"row": index, "error": "Invalid mobile number"});
            continue
        if not 0 < age < 120:
            errors.append({"row": index, "error": "Age must be between 1 and 119"});
            continue
        if mobile in seen_mobiles:
            errors.append({"row": index, "error": "Duplicate mobile number in file"});
            continue
        seen_mobiles.add(mobile)
        branch_id = branch_names.get((row.get("Branch") or "").strip().casefold())
        department_id = department_names.get((row.get("Department") or "").strip().casefold())
        if not branch_id or not department_id:
            errors.append({"row": index, "error": "Invalid branch or department"});
            continue
        email = (row.get("Email") or "").strip() or None
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors.append({"row": index, "error": "Invalid email"});
            continue
        valid.append({"name": row["Name"].strip(), "age": age, "mobile": mobile, "branch_id": branch_id,
                      "department_id": department_id, "symptoms": row["Symptoms"].strip(), "email": email,
                      "patient_code": (row.get("Patient ID") or "").strip() or None})
    return valid, errors


def _validate_medical_upload(filename: str, payload: bytes):
    suffix = Path(filename).suffix.lower()
    signatures = {".pdf": (b"%PDF-", "application/pdf"), ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
                  ".jpeg": (b"\xff\xd8\xff", "image/jpeg"), ".png": (b"\x89PNG\r\n\x1a\n", "image/png")}
    if suffix not in signatures or not payload.startswith(signatures[suffix][0]):
        raise HTTPException(status_code=422, detail="Only valid PDF, JPG/JPEG, and PNG medical files are allowed")
    if not payload or len(payload) > MAX_MEDICAL_FILE_BYTES:
        raise HTTPException(status_code=422, detail="Medical files must be between 1 byte and 10 MB")
    return suffix, signatures[suffix][1]


DEPARTMENT_KNOWLEDGE = {
    "Cardiology": (
        "Cardiology evaluates chest pain, palpitations, shortness of breath, heart rhythm problems, "
        "high blood pressure, swelling in the legs, and other cardiac or circulatory symptoms."
    ),
    "Neurology": (
        "Neurology handles headaches, seizures, dizziness, numbness, weakness, stroke-like symptoms, "
        "memory changes, and other brain, nerve, or spinal cord concerns."
    ),
    "Orthopedics": (
        "Orthopedics treats joint pain, bone or muscle injuries, fractures, back pain, knee pain, "
        "sports injuries, and other musculoskeletal conditions."
    ),
    "Dermatology": (
        "Dermatology manages rashes, itching, acne, skin infections, dermatitis, mole checks, "
        "hair and nail concerns, and other skin-related problems."
    ),
    "General Medicine": (
        "General Medicine is for fever, cold, cough, fatigue, generalized pain, infections, minor illnesses, "
        "and when the exact specialty is not clear."
    ),
}


def _department_keywords() -> Dict[str, List[str]]:
    """
    Department-specific symptom keywords.
    """

    return {
        "Cardiology": [
            # English
            "chest pain",
            "chest discomfort",
            "chest tightness",
            "palpitations",
            "heart pain",
            "heart problem",
            "heart",
            "tachycardia",
            "angina",
            "shortness of breath",
            "breathing difficulty",
            "blood pressure",
            "high blood pressure",
            "cardiac",

            # Tamil
            "நெஞ்சு வலி",
            "மார்பு வலி",
            "நெஞ்சு",
            "மார்பு",
            "இதய வலி",
            "இதயம்",
            "இதய பிரச்சனை",
            "இதயத் துடிப்பு",
            "மூச்சுத்திணறல்",
            "மூச்சு திணறல்",
            "ரத்த அழுத்தம்",
            "இரத்த அழுத்தம்",
        ],

        "Neurology": [
            # English
            "headache",
            "severe headache",
            "migraine",
            "seizure",
            "seizures",
            "fits",
            "numbness",
            "weakness",
            "dizziness",
            "vertigo",
            "stroke",
            "nerve",
            "nerve pain",
            "memory problem",

            # Tamil
            "தலைவலி",
            "கடுமையான தலைவலி",
            "ஒற்றைத்தலைவலி",
            "வலிப்பு",
            "மயக்கம்",
            "தலைச்சுற்றல்",
            "மரத்துப்போதல்",
            "மரத்துப்போன",
            "பலவீனம்",
            "பக்கவாதம்",
            "நரம்பு",
            "நரம்பு வலி",
            "ஞாபக மறதி",
        ],

        "Orthopedics": [
            # English
            "joint pain",
            "bone pain",
            "joint",
            "bone",
            "fracture",
            "sprain",
            "back pain",
            "knee pain",
            "knee",
            "hip pain",
            "hip",
            "muscle pain",
            "muscle",
            "ligament",

            # Tamil
            "எலும்பு வலி",
            "மூட்டு வலி",
            "எலும்பு",
            "மூட்டு",
            "முதுகு வலி",
            "முழங்கால் வலி",
            "முழங்கால்",
            "இடுப்பு வலி",
            "இடுப்பு",
            "தசை வலி",
            "தசை",
        ],

        "Dermatology": [
            # English
            "skin rash",
            "skin allergy",
            "rash",
            "itch",
            "itching",
            "skin",
            "acne",
            "pimples",
            "eczema",
            "psoriasis",
            "lesion",
            "pimple",
            "skin infection",

            # Tamil
            "தோல் பிரச்சனை",
            "தோல் ஒவ்வாமை",
            "தோல்",
            "அரிப்பு",
            "தோல் அரிப்பு",
            "பருக்கள்",
            "முகப்பரு",
            "தோல் தொற்று",
        ],

        "General Medicine": [
            # English
            "fever",
            "cold",
            "cough",
            "infection",
            "fatigue",
            "general",
            "weak",
            "body pain",
            "feeling sick",
            "not feeling well",

            # Tamil
            "காய்ச்சல்",
            "சளி",
            "இருமல்",
            "தொற்று",
            "சோர்வு",
            "பலவீனம்",
            "உடல் வலி",
            "உடம்பு சரியில்லை",
            "உடல் நலம் சரியில்லை",
        ],
    }


def _heuristic_department(
        symptoms: str,
        departments: List[dict],
) -> Optional[dict]:
    """
    Score departments by keyword match. Returns the best-scoring
    department dict, or None if nothing matched at all.

    (Returning None instead of defaulting to General Medicine here,
    because the caller needs to know whether this was a *confident*
    match — used for the safety override against Ollama's pick.)
    """

    text = " ".join((symptoms or "").strip().lower().split())

    if not text:
        return None

    keywords = _department_keywords()

    scores = {
        department["name"]: 0
        for department in departments
        if department.get("name")
    }

    matched_keywords = {department_name: [] for department_name in scores}

    for department_name in scores:

        department_keywords = keywords.get(department_name, [])

        for phrase in department_keywords:

            phrase = phrase.strip().lower()

            if not phrase:
                continue

            if phrase in text:

                word_count = len(phrase.split())

                if word_count >= 3:
                    weight = 5
                elif word_count == 2:
                    weight = 4
                else:
                    weight = 1

                scores[department_name] += weight

                matched_keywords[department_name].append(
                    {"keyword": phrase, "weight": weight}
                )

    best_department_name = None
    best_score = 0

    for department_name, score in scores.items():
        if score > best_score:
            best_score = score
            best_department_name = department_name

    logger.debug(f"Keyword Department Analysis | symptoms={symptoms} | scores={scores} | keywords={matched_keywords}")

    if best_score == 0:
        return None

    return next(
        (
            department
            for department in departments
            if department["name"] == best_department_name
        ),
        None,
    )


# A match is "confident" when a specific 2+ word symptom phrase was
# found (e.g. "chest pain", "நெஞ்சு வலி") rather than a single generic
# word. This threshold is what triggers the safety override.
_CONFIDENT_MATCH_THRESHOLD = 4


def _confident_heuristic_department(
        symptoms: str,
        departments: List[dict],
) -> Optional[dict]:
    """
    Same as _heuristic_department, but only returns a result when the
    match is strong (multi-word phrase, not just a generic single
    word). Used to override Ollama when it disagrees with a clear
    symptom match.
    """

    text = " ".join((symptoms or "").strip().lower().split())

    if not text:
        return None

    keywords = _department_keywords()
    best_name = None
    best_score = 0

    for department in departments:

        department_name = department.get("name")

        if not department_name:
            continue

        score = 0

        for phrase in keywords.get(department_name, []):

            phrase = phrase.strip().lower()

            if phrase and phrase in text:
                word_count = len(phrase.split())
                weight = 5 if word_count >= 3 else (4 if word_count == 2 else 1)
                score += weight

        if score > best_score:
            best_score = score
            best_name = department_name

    if best_score < _CONFIDENT_MATCH_THRESHOLD:
        return None

    return next(
        (d for d in departments if d["name"] == best_name),
        None,
    )


# ============================================================================
# OLLAMA — SYMPTOM ANALYSIS / DEPARTMENT IDENTIFICATION
# ============================================================================

def _ollama_identify_department(
        symptoms: str,
        departments: List[dict],
        ordered_names: List[str],
) -> Optional[str]:
    """
    Ask Ollama to analyze the symptoms and identify the single best
    matching department. Returns the department name (must exactly
    match one of `ordered_names`) or None if Ollama is unavailable,
    errors, or returns something that can't be matched to a real
    department.
    """

    if ollama is None:
        return None

    model_name = os.getenv("OLLAMA_MODEL")

    if not model_name:
        return None

    knowledge_snippets = []

    for department in departments:
        name = department["name"].strip()
        knowledge_snippets.append(f"{name}: {DEPARTMENT_KNOWLEDGE.get(name, name)}")

    available_departments = "\n".join(f"- {name}" for name in ordered_names)
    department_knowledge = "\n".join(knowledge_snippets)

    prompt = f"""
You are a hospital triage classifier. Analyze the patient's symptoms
and identify the SINGLE most appropriate department.

RULES:
1. Select EXACTLY ONE department.
2. Select ONLY from the available department list below.
3. NEVER invent a department that isn't in the list.
4. If symptoms are vague, mild, or don't clearly point to a
   specialty, select General Medicine if it is available.
5. Respond with ONLY the department name — nothing else. No
   explanation, no punctuation, no extra words.

AVAILABLE DEPARTMENTS:
{available_departments}

DEPARTMENT KNOWLEDGE:
{department_knowledge}

PATIENT SYMPTOMS:
{symptoms}

Respond with only the department name.
"""

    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a hospital triage classifier. You "
                        "identify exactly one department from the "
                        "given list based on patient symptoms. You "
                        "respond with only the department name."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

        raw_text = response.get("message", {}).get("content", "").strip()

        if not raw_text:
            return None

        logger.debug(f"Ollama Department Identification | symptoms={symptoms} | raw_response={raw_text}")

        for name in ordered_names:
            if re.search(rf"\b{re.escape(name)}\b", raw_text, flags=re.IGNORECASE):
                logger.info(f"Ollama identified department | name={name}")
                return name

        logger.warning("Could not match Ollama response to a valid department.")
        return None

    except Exception as exc:
        logger.error(f"Ollama department identification failed | error={exc}")
        return None


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def recommend_department(
        symptoms: str,
        departments: List[dict],
        language: str = "en",
) -> dict:
    symptoms = (symptoms or "").strip()

    if not symptoms:
        raise ValueError("Symptoms are required.")

    if not departments:
        raise ValueError("No departments are available.")

    language = (language or "en").strip().lower()

    if language not in {"en", "ta"}:
        language = "en"

    ordered_names = [
        department["name"].strip()
        for department in departments
        if department.get("name")
    ]

    if not ordered_names:
        raise ValueError("No valid department names are available.")

    # --------------------------------------------------------------
    # STEP 1 — Ollama identifies the department from the symptoms.
    # --------------------------------------------------------------
    ollama_department_name = _ollama_identify_department(symptoms, departments, ordered_names)

    # --------------------------------------------------------------
    # STEP 2 — Safety override: if there's a CONFIDENT keyword match
    # and it disagrees with Ollama, trust the keyword match instead.
    # --------------------------------------------------------------
    confident_match = _confident_heuristic_department(symptoms, departments)

    if confident_match and confident_match["name"] != ollama_department_name:
        logger.info(f"Overriding Ollama's pick | ollama={ollama_department_name} | keyword_match={confident_match['name']}")
        selected = confident_match

    elif ollama_department_name:
        selected = next(
            (d for d in departments if d["name"] == ollama_department_name),
            None,
        )

    else:
        selected = None

    # --------------------------------------------------------------
    # STEP 3 — Fallback chain if nothing valid was selected yet:
    # any keyword match -> General Medicine -> first department.
    # --------------------------------------------------------------
    if selected is None:
        selected = _heuristic_department(symptoms, departments)

    if selected is None:
        selected = next(
            (
                d for d in departments
                if d["name"].strip().lower() == "general medicine"
            ),
            departments[0],
        )

    return {
        "department_id": selected["id"],
        "department_name": selected["name"],
        "language": language,
    }


def get_available_departments(db: Session, branch_id: Optional[int] = None):
    from backend.database.models import Department, Doctor, Branch
    if branch_id is not None:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        departments = (
            db.query(Department)
            .join(Doctor, Doctor.department_id == Department.id)
            .filter(Doctor.branch_id == branch_id, Doctor.doctor_status == 'ACTIVE')
            .order_by(Department.name)
            .distinct()
            .all()
        )
    else:
        departments = db.query(Department).order_by(Department.name).all()

    return [{"id": d.id, "name": d.name} for d in departments]


# ============================================================
# GET ALL OPEN BRANCHES
# ============================================================

@app.get("/branches")
def list_branches(db: Session = Depends(get_db)):
    """
    Return all OPEN hospital branches.
    """

    from backend.database.models import Branch

    branches = (
        db.query(Branch)
        .filter(Branch.branch_status == "OPEN")
        .order_by(Branch.name)
        .all()
    )

    return [
        {
            "id": branch.id,
            "name": branch.name,
            "address": branch.address,
            "phone": branch.phone,
            "branch_status": branch.branch_status,
        }
        for branch in branches
    ]


# ============================================================
# GET ALL DEPARTMENTS
# ============================================================

@app.get("/departments/all")
def list_all_departments(db: Session = Depends(get_db)):
    """
    Return all departments.

    Used by the admin filter dropdown.
    """

    from backend.database.models import Department

    departments = (
        db.query(Department)
        .order_by(Department.name)
        .all()
    )

    return [
        {
            "id": department.id,
            "name": department.name,

        }
        for department in departments
    ]


# ============================================================
# GET DEPARTMENTS FOR A BRANCH
# ============================================================

@app.get("/departments")
def list_departments(
        branch_id: int = Query(...),
        db: Session = Depends(get_db),
):
    """
    Return departments that have at least one ACTIVE doctor
    at the selected OPEN branch.
    """

    from backend.database.models import Branch, Department, Doctor

    # --------------------------------------------------------
    # Check branch
    # --------------------------------------------------------

    branch = (
        db.query(Branch)
        .filter(
            Branch.id == branch_id,
            Branch.branch_status == "OPEN",
        )
        .first()
    )

    if branch is None:
        raise HTTPException(
            status_code=404,
            detail="Branch not found",
        )

    # --------------------------------------------------------
    # Find departments with ACTIVE doctors
    # --------------------------------------------------------

    departments = (
        db.query(Department)
        .join(
            Doctor,
            Doctor.department_id == Department.id,
        )
        .filter(
            Doctor.branch_id == branch_id,
            Doctor.doctor_status == "ACTIVE",
        )
        .distinct()
        .order_by(Department.name)
        .all()
    )

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return [
        {
            "id": department.id,
            "name": department.name,

        }
        for department in departments
    ]


@app.post("/symptoms/analyze")
def analyze_symptoms(
        request: SymptomAnalysisRequest,
        db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # Validate symptoms
    # --------------------------------------------------------

    symptoms = (request.symptoms or "").strip()

    if len(symptoms) < 2:
        raise HTTPException(
            status_code=400,
            detail="Please provide valid symptoms.",
        )

    # --------------------------------------------------------
    # Validate language
    # --------------------------------------------------------

    language = (request.language or "en").strip().lower()

    if language not in {"en", "ta"}:
        language = "en"

    # --------------------------------------------------------
    # Get departments available for selected branch
    # --------------------------------------------------------

    departments = get_available_departments(
        db,
        request.branch_id,
    )

    if not departments:
        raise HTTPException(
            status_code=404,
            detail="No departments available for analysis.",
        )

    # --------------------------------------------------------
    # Call recommendation function
    #
    # IMPORTANT:
    # We return recommend_department() directly.
    # --------------------------------------------------------

    try:

        return recommend_department(
            symptoms=symptoms,
            departments=departments,
            language=language,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        logger.error(f"Symptom analysis failed | error={exc}")

        raise HTTPException(
            status_code=500,
            detail="Unable to analyze symptoms.",
        )


@app.get("/doctors")
def list_doctors(branch_id: int = Query(...), department_id: int = Query(...), db: Session = Depends(get_db)):
    return list_doctors_for_branch_department(db, branch_id, department_id)


@app.get("/branches/open")
def list_open_branches(db: Session = Depends(get_db)):
    from backend.database.models import Branch
    branches = db.query(Branch).filter(Branch.branch_status == 'OPEN').order_by(Branch.name).all()
    return [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status} for b
            in branches]


@app.get("/branches/{branch_id}/doctors")
def list_branch_doctors(
        branch_id: int,
        department_id: Optional[int] = Query(None),
        appointment_date: Optional[str] = Query(None, alias="date"),
        db: Session = Depends(get_db)
):
    try:
        the_date = date.fromisoformat(appointment_date) if appointment_date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    from backend.database.models import Branch
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    doctors = list_doctors_with_availability(db, branch_id, department_id, the_date)
    return {
        "branch": {"id": branch.id, "name": branch.name, "address": branch.address, "phone": branch.phone,
                   "branch_status": branch.branch_status},
        "date": the_date.isoformat(),
        "doctors": doctors,
    }


@app.get("/doctors/{doctor_id}/dates")
def available_dates(doctor_id: int, days: int = DATE_LOOKAHEAD_DAYS, db: Session = Depends(get_db)):
    doctor_exists_active(db, doctor_id)
    today = date.today()
    available = []
    for offset in range(days):
        the_date = today + timedelta(days=offset)
        all_slots = slots_for_date(db, doctor_id, the_date)
        if not all_slots:
            continue
        classified = classify_slots(db, doctor_id, the_date)
        free_count = len([s for s, status in classified if status == "AVAILABLE"])
        available.append(
            {
                "date": the_date.isoformat(),
                "weekday": the_date.strftime("%A"),
                "total_slots": len(all_slots),
                "free_slots": free_count,
                "full": free_count == 0,
            }
        )
    return available


@app.get("/doctors/{doctor_id}/slots")
def doctor_slots(doctor_id: int, appointment_date: str = Query(..., alias="date"), db: Session = Depends(get_db)):
    doctor_exists_active(db, doctor_id)
    try:
        the_date = date.fromisoformat(appointment_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    all_slots = slots_for_date(db, doctor_id, the_date)
    if not all_slots:
        return []
    return [{"time": s, "status": status} for s, status in classify_slots(db, doctor_id, the_date)]


# ---------------------------------------------------------------------------
# Booking flow (no payment step)
# ---------------------------------------------------------------------------

@app.post("/appointments/book")
def book_appointment(req: BookRequest, db: Session = Depends(get_db)):
    try:
        the_date = date.fromisoformat(req.appointment_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="appointment_date must be YYYY-MM-DD")
    if the_date < date.today():
        raise HTTPException(status_code=400, detail="appointment_date is in the past")

    from sqlalchemy.exc import IntegrityError
    from backend.database.models import Appointment, Branch, Department

    doctor = doctor_exists_active(db, req.doctor_id)
    if doctor["branch_id"] != req.branch_id or doctor["department_id"] != req.department_id:
        raise HTTPException(
            status_code=400, detail="Doctor does not belong to the selected branch/department"
        )

    valid_slots = slots_for_date(db, req.doctor_id, the_date)
    if req.time_slot not in valid_slots:
        raise HTTPException(status_code=400, detail="That time is outside the doctor's working hours")

    slot_status = dict(classify_slots(db, req.doctor_id, the_date)).get(req.time_slot)
    if slot_status != "AVAILABLE":
        message = (
            "That time has already passed."
            if slot_status == "PAST"
            else "That slot is already booked."
        )
        return {
            "status": "CONFLICT",
            "message": message,
            "alternatives": find_alternatives(db, req.doctor_id, the_date, req.time_slot),
        }

    code = gen_appointment_code()
    patient_id = _upsert_booking_patient(db, req)

    new_appt = Appointment(
        appointment_code=code,
        patient_name=req.patient_name,
        age=req.age,
        gender=req.gender,
        mobile=req.mobile,
        email=req.email,
        address=req.address,
        reason=req.reason,
        branch_id=req.branch_id,
        department_id=req.department_id,
        doctor_id=req.doctor_id,
        appointment_date=req.appointment_date,
        time_slot=req.time_slot,

        status='CONFIRMED',
        patient_id=patient_id,
        symptoms=req.reason
    )

    try:
        db.add(new_appt)
        db.commit()
        logger.info(f"Appointment created | appointment_id={new_appt.id} | appointment_code={code}")
    except IntegrityError:
        db.rollback()
        return {
            "status": "CONFLICT",
            "message": "That slot was just booked by another patient.",
            "alternatives": find_alternatives(db, req.doctor_id, the_date, req.time_slot),
        }

    branch = db.query(Branch).filter(Branch.id == req.branch_id).first()
    department = db.query(Department).filter(Department.id == req.department_id).first()

    notify_result = notifications.notify(
        "booked",
        {
            "code": code,
            "patient_name": req.patient_name,
            "doctor": doctor["name"],
            "department": department.name,
            "branch": branch.name,
            "date": req.appointment_date,
            "time": req.time_slot,

        },
        mobile=req.mobile,
        email=req.email,
    )
    appointment_id = new_appt.id
    audit(db, Principal(None, patient_id, {"PATIENT"}, f"booking:{req.mobile}"), "APPOINTMENT_CREATE", "appointment",
          appointment_id)
    _record_notification(db, appointment_id, "PATIENT", req.mobile, notify_result.get("sms"))
    _record_notification(db, appointment_id, "PATIENT", req.email or "", notify_result.get("email"))
    # patient_whatsapp = whatsapp_module.send_appointment_notification(
    #     req.mobile,
    #     f"Appointment Confirmed\nID: {code}\nDoctor: {doctor['name']}\nDepartment: {department.name}\nBranch: {branch.name}\nDate: {req.appointment_date}\nTime: {req.time_slot}"
    # )
    # _record_notification(db, appointment_id, "PATIENT", req.mobile, patient_whatsapp)
    doctor_message = (
        f"New appointment {code}: {req.patient_name}, age {req.age or 'not provided'}, "
        f"symptoms: {req.reason or 'not provided'}, {req.appointment_date} {req.time_slot}."
    )
    doctor_sms = notifications.send_sms(doctor["mobile"], doctor_message) if doctor.get("mobile") else None
    doctor_email = notifications.send_email(doctor["email"], f"New Appointment — {code}", doctor_message) if doctor.get(
        "email") else None
    doctor_whatsapp = whatsapp_module.send_appointment_notification(doctor["mobile"], doctor_message) if doctor.get(
        "mobile") else None
    _record_notification(db, appointment_id, "DOCTOR", doctor.get("mobile") or "", doctor_sms)
    _record_notification(db, appointment_id, "DOCTOR", doctor.get("email") or "", doctor_email)
    _record_notification(db, appointment_id, "DOCTOR", doctor.get("mobile") or "", doctor_whatsapp)

    return {
        "status": "BOOKED",
        "appointment_code": code,
        "notification_sent_to": req.mobile,
        "notification_preview": notify_result["preview"],
        "summary": {
            "patient_name": req.patient_name,
            "age": req.age,
            "gender": req.gender,
            "mobile": req.mobile,
            "email": req.email,
            "branch": branch.name,
            "department": department.name,
            "doctor": doctor["name"],
            "qualification": doctor["qualification"],
            "date": req.appointment_date,
            "time": req.time_slot,

        },
    }


@app.get("/appointments/{code}")
def get_appointment(code: str, db: Session = Depends(get_db)):
    from backend.database.models import Appointment
    row = db.query(Appointment).filter(Appointment.appointment_code == code).first()
    if not row:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return {
        "id": row.id, "appointment_code": row.appointment_code, "patient_name": row.patient_name,
        "age": row.age, "gender": row.gender, "mobile": row.mobile, "email": row.email,
        "address": row.address, "reason": row.reason, "branch_id": row.branch_id,
        "department_id": row.department_id, "doctor_id": row.doctor_id,
        "appointment_date": row.appointment_date, "time_slot": row.time_slot,
        "status": row.status, "patient_id": row.patient_id, "symptoms": row.symptoms
    }


@app.get("/appointments/{code}/lookup")
def lookup_appointment(code: str, patient_id: int = Depends(get_current_patient_id), db: Session = Depends(get_db), mobile: str = None):
    from backend.database.models import Doctor, Branch, Department
    row = _get_owned_appointment(db, code, patient_id=patient_id, mobile=mobile)
    doctor = db.query(Doctor).filter(Doctor.id == row.doctor_id).first()
    branch = db.query(Branch).filter(Branch.id == row.branch_id).first()
    department = db.query(Department).filter(Department.id == row.department_id).first()
    return {
        "id": row.id, "appointment_code": row.appointment_code, "patient_name": row.patient_name,
        "age": row.age, "gender": row.gender, "mobile": row.mobile, "email": row.email,
        "address": row.address, "reason": row.reason, "branch_id": row.branch_id,
        "department_id": row.department_id, "doctor_id": row.doctor_id,
        "appointment_date": row.appointment_date, "time_slot": row.time_slot,
        "status": row.status, "patient_id": row.patient_id, "symptoms": row.symptoms,
        "doctor_name": doctor.name if doctor else "Unknown",
        "branch_name": branch.name if branch else "Unknown",
        "department_name": department.name if department else "Unknown"
    }




def _get_owned_appointment(db: Session, code: str, patient_id: int = None, mobile: str = None):
    from backend.database.models import Appointment
    row = db.query(Appointment).filter(Appointment.appointment_code == code).first()
    
    if not row:
        raise HTTPException(status_code=404, detail="No appointment found for that code")

    # If patient_id is explicitly provided and is an integer (authenticated web request)
    if isinstance(patient_id, int):
        if row.patient_id != patient_id:
            raise HTTPException(status_code=404, detail="No appointment found for that code and patient")
    # Otherwise check mobile (for WhatsApp chatbot or unauthenticated web reschedule)
    elif mobile:
        if row.mobile != mobile:
            raise HTTPException(status_code=404, detail="No appointment found for that code and mobile")
    else:
        raise HTTPException(status_code=403, detail="Unauthorized: Must provide patient_id or mobile")
    
    return row


def _mark_cancelled(db: Session, appt_row) -> None:
    appt_row.status = 'CANCELLED'
    db.commit()
    logger.info(f"Appointment cancelled | appointment_code={appt_row.appointment_code}")


def _notify_cancelled(db: Session, appt_row):
    from backend.database.models import Doctor, Branch, Department
    doctor = db.query(Doctor).filter(Doctor.id == appt_row.doctor_id).first()
    branch = db.query(Branch).filter(Branch.id == appt_row.branch_id).first()
    department = db.query(Department).filter(Department.id == appt_row.department_id).first()
    return notifications.notify(
        "cancelled",
        {
            "code": appt_row.appointment_code,
            "patient_name": appt_row.patient_name,
            "doctor": doctor.name if doctor else "Unknown",
            "department": department.name if department else "Unknown",
            "branch": branch.name if branch else "Unknown",
            "date": appt_row.appointment_date,
            "time": appt_row.time_slot,
        },
        mobile=appt_row.mobile,
        email=appt_row.email,
    )


@app.post("/appointments/{code}/cancel")
def cancel_appointment(code: str, patient_id: int = Depends(get_current_patient_id), db: Session = Depends(get_db), mobile: str = None):
    """Patient self-service cancel — requires authenticated patient."""
    appt = _get_owned_appointment(db, code, patient_id=patient_id, mobile=mobile)
    if appt.status == "CANCELLED":
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")
    _mark_cancelled(db, appt)
    notify_result = _notify_cancelled(db, appt)
    return {"status": "CANCELLED", "appointment_code": code, "notification_preview": notify_result["preview"]}


@app.post("/appointments/{code}/reschedule")
def reschedule_appointment(code: str, req: RescheduleRequest, patient_id: int = Depends(get_current_patient_id), db: Session = Depends(get_db), mobile: str = None):
    try:
        new_date = date.fromisoformat(req.appointment_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="appointment_date must be YYYY-MM-DD")
    if new_date < date.today():
        raise HTTPException(status_code=400, detail="appointment_date is in the past")

    from sqlalchemy.exc import IntegrityError
    from backend.database.models import Branch, Department

    appt = _get_owned_appointment(db, code, patient_id=patient_id, mobile=mobile or req.mobile)
    if appt.status == "CANCELLED":
        raise HTTPException(status_code=400, detail="This appointment was already cancelled")

    doctor = doctor_exists_active(db, appt.doctor_id)
    valid_slots = slots_for_date(db, appt.doctor_id, new_date)
    if req.time_slot not in valid_slots:
        raise HTTPException(status_code=400, detail="That time is outside the doctor's working hours")

    exclude = appt.time_slot if appt.appointment_date == req.appointment_date else None
    slot_status = dict(classify_slots(db, appt.doctor_id, new_date, exclude_slot=exclude)).get(req.time_slot)
    if slot_status != "AVAILABLE":
        message = (
            "That time has already passed."
            if slot_status == "PAST"
            else "That slot is already booked."
        )
        return {
            "status": "CONFLICT",
            "message": message,
            "alternatives": find_alternatives(db, appt.doctor_id, new_date, req.time_slot),
        }

    old_date, old_time = appt.appointment_date, appt.time_slot

    appt.appointment_date = req.appointment_date
    appt.time_slot = req.time_slot

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {
            "status": "CONFLICT",
            "message": "That slot was just booked by another patient.",
            "alternatives": find_alternatives(db, appt.doctor_id, new_date, req.time_slot),
        }

    branch = db.query(Branch).filter(Branch.id == appt.branch_id).first()
    department = db.query(Department).filter(Department.id == appt.department_id).first()

    notify_result = notifications.notify(
        "rescheduled",
        {
            "code": code,
            "patient_name": appt.patient_name,
            "doctor": doctor["name"],
            "department": department.name,
            "branch": branch.name,
            "old_date": old_date,
            "old_time": old_time,
            "date": req.appointment_date,
            "time": req.time_slot,

        },
        mobile=appt.mobile,
        email=appt.email,
    )

    return {
        "status": "RESCHEDULED",
        "appointment_code": code,
        "notification_preview": notify_result["preview"],
        "summary": {
            "patient_name": appt.patient_name,
            "mobile": appt.mobile,
            "branch": branch.name,
            "department": department.name,
            "doctor": doctor["name"],
            "qualification": doctor["qualification"],
            "date": req.appointment_date,
            "time": req.time_slot,

        },
    }


# ---------------------------------------------------------------------------
# Admin Role Users Management
# ---------------------------------------------------------------------------

@app.get("/admin/users", response_model=List[UserListResponse])
def admin_get_users(principal: Principal = Depends(require_permission('USER_MANAGE')), db: Session = Depends(get_db)):
    from backend.database.models import User, Role, Branch, Department
    query = db.query(User, Role.name.label('role_name'), Branch.name.label('branch_name'), Department.name.label('department_name')) \
              .outerjoin(Role, User.role_id == Role.id) \
              .outerjoin(Branch, User.branch_id == Branch.id) \
              .outerjoin(Department, User.department_id == Department.id)


    
    # Filter by branch if Branch Admin
    if "BRANCH_ADMIN" in principal.roles:
        principal_branch_ids = [s['branch_id'] for s in principal.scopes if s.get('branch_id') is not None]
        if principal_branch_ids:
            query = query.filter(User.branch_id.in_(principal_branch_ids))
    
    # Filter by department if Department Admin
    if "DEPARTMENT_ADMIN" in principal.roles:
        principal_dept_ids = [s['department_id'] for s in principal.scopes if s.get('department_id') is not None]
        if principal_dept_ids:
            query = query.filter(User.department_id.in_(principal_dept_ids))

    results = query.all()
    
    users = []
    for user_obj, r_name, b_name, d_name in results:
        users.append({
            "id": user_obj.id,
            "name": user_obj.name,
            "email": user_obj.email,
            "role_id": user_obj.role_id,
            "role_name": r_name,
            "branch_id": user_obj.branch_id,
            "branch_name": b_name,
            "department_id": user_obj.department_id,
            "department_name": d_name,
            "is_active": user_obj.is_active,
            "created_at": str(user_obj.created_at) if user_obj.created_at else None,
            "updated_at": str(user_obj.updated_at) if user_obj.updated_at else None,
        })

    return users

@app.post("/admin/users", response_model=UserListResponse)
def admin_create_user(req: UserCreateRequest, principal: Principal = Depends(require_permission('USER_MANAGE')), db: Session = Depends(get_db)):
    from backend.database.models import User, Role, Branch, Department
    
    # Validation based on role
    if "BRANCH_ADMIN" in principal.roles:
        principal_branch_ids = [s['branch_id'] for s in principal.scopes if s.get('branch_id') is not None]
        if principal_branch_ids and req.branch_id not in principal_branch_ids:
            raise HTTPException(status_code=403, detail="Branch Admin can only create users in their own branch")
        target_role = db.query(Role).filter(Role.id == req.role_id).first()
        if not target_role or target_role.name == "ADMIN":
            raise HTTPException(status_code=403, detail="Branch Admin cannot create ADMIN users")

    if "DEPARTMENT_ADMIN" in principal.roles and principal.department_id:
        if req.department_id != principal.department_id:
            raise HTTPException(status_code=403, detail="Department Admin can only create users in their own department")
            
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
        
    hashed = hash_password(req.password)
    
    new_user = User(
        name=req.name,
        email=req.email,
        password_hash=hashed,
        role_id=req.role_id,
        branch_id=req.branch_id,
        department_id=req.department_id,
        is_active=1
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    role = db.query(Role).filter(Role.id == new_user.role_id).first()
    branch = db.query(Branch).filter(Branch.id == new_user.branch_id).first() if new_user.branch_id else None
    dept = db.query(Department).filter(Department.id == new_user.department_id).first() if new_user.department_id else None
    
    return {
        "id": new_user.id,
        "name": new_user.name,
        "email": new_user.email,
        "role_id": new_user.role_id,
        "role_name": role.name if role else "",
        "branch_id": new_user.branch_id,
        "branch_name": branch.name if branch else None,
        "department_id": new_user.department_id,
        "department_name": dept.name if dept else None,
        "is_active": new_user.is_active
    }

@app.put("/admin/users/{user_id}", response_model=UserListResponse)
def admin_update_user(user_id: int, req: UserUpdateRequest, principal: Principal = Depends(require_permission('USER_MANAGE')), db: Session = Depends(get_db)):
    from backend.database.models import User, Role, Branch, Department
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check permissions...
    target_role = db.query(Role).filter(Role.id == req.role_id).first()
    if not target_role:
        raise HTTPException(status_code=400, detail="Invalid role")

    if "BRANCH_ADMIN" in principal.roles:
        principal_branch_ids = [s['branch_id'] for s in principal.scopes if s.get('branch_id') is not None]
        if principal_branch_ids and user.branch_id not in principal_branch_ids:
            raise HTTPException(status_code=403, detail="Not authorized to edit this user")
        if req.branch_id not in principal_branch_ids:
            raise HTTPException(status_code=403, detail="Cannot move user to another branch")
        if target_role.name == "ADMIN":
            raise HTTPException(status_code=403, detail="Branch Admin cannot grant ADMIN privileges")
            
    if "DEPARTMENT_ADMIN" in principal.roles and not "ADMIN" in principal.roles and not "BRANCH_ADMIN" in principal.roles:
        principal_dept_ids = [s['department_id'] for s in principal.scopes if s.get('department_id') is not None]
        if principal_dept_ids and user.department_id not in principal_dept_ids:
            raise HTTPException(status_code=403, detail="Not authorized to edit this user")
        if req.department_id not in principal_dept_ids:
            raise HTTPException(status_code=403, detail="Cannot move user to another department")
        if target_role.name in ("ADMIN", "BRANCH_ADMIN", "DEPARTMENT_ADMIN"):
            raise HTTPException(status_code=403, detail="Department Admin cannot grant equal or higher privileges")
            
    if req.email != user.email:
        existing = db.query(User).filter(User.email == req.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered by another user")

    user.name = req.name
    user.email = req.email
    user.role_id = req.role_id
    user.branch_id = req.branch_id
    user.department_id = req.department_id
    user.is_active = req.is_active
    
    db.commit()
    db.refresh(user)
    
    role = db.query(Role).filter(Role.id == user.role_id).first()
    branch = db.query(Branch).filter(Branch.id == user.branch_id).first() if user.branch_id else None
    dept = db.query(Department).filter(Department.id == user.department_id).first() if user.department_id else None
    
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role_id": user.role_id,
        "role_name": role.name if role else "",
        "branch_id": user.branch_id,
        "branch_name": branch.name if branch else None,
        "department_id": user.department_id,
        "department_name": dept.name if dept else None,
        "is_active": user.is_active
    }

@app.put("/admin/users/{user_id}/password")
def admin_change_password(user_id: int, req: UserPasswordUpdateRequest, principal: Principal = Depends(require_permission('USER_MANAGE')), db: Session = Depends(get_db)):
    from backend.database.models import User
    
    if req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check permissions...
    if "BRANCH_ADMIN" in principal.roles:
        principal_branch_ids = [s['branch_id'] for s in principal.scopes if s.get('branch_id') is not None]
        if principal_branch_ids and user.branch_id not in principal_branch_ids:
            raise HTTPException(status_code=403, detail="Not authorized to edit this user")
            
    user.password_hash = hash_password(req.new_password)
    db.commit()
    
    return {"message": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Admin dashboard (HTTP Basic Auth — see auth.py)
# ---------------------------------------------------------------------------

@app.get("/admin/me")
def admin_me(principal: Principal = Depends(require_permission('APPOINTMENT_READ'))):
    """Frontend calls this once at login to verify credentials before showing the dashboard."""
    return {"admin": principal.label, "roles": list(principal.roles)}


@app.get("/admin/stats")
def admin_stats(principal: Principal = Depends(require_permission('APPOINTMENT_READ')), db: Session = Depends(get_db)):
    from sqlalchemy import func, desc
    from backend.database.models import Appointment, Branch, Department, Doctor

    total = db.query(func.count(Appointment.id)).scalar()
    active = db.query(func.count(Appointment.id)).filter(Appointment.status == 'BOOKED').scalar()
    cancelled = db.query(func.count(Appointment.id)).filter(Appointment.status == 'CANCELLED').scalar()
    today_count = db.query(func.count(Appointment.id)).filter(
        Appointment.status == 'BOOKED',
        Appointment.appointment_date == date.today().isoformat()
    ).scalar()

    by_branch = (
        db.query(Branch.name.label('branch'), func.count(Appointment.id).label('count'))
        .join(Appointment, Branch.id == Appointment.branch_id)
        .filter(Appointment.status == 'BOOKED')
        .group_by(Branch.id)
        .order_by(desc('count'))
        .all()
    )

    by_department = (
        db.query(Department.name.label('department'), func.count(Appointment.id).label('count'))
        .join(Appointment, Department.id == Appointment.department_id)
        .filter(Appointment.status == 'BOOKED')
        .group_by(Department.id)
        .order_by(desc('count'))
        .all()
    )

    top_doctors = (
        db.query(Doctor.name.label('doctor'), Branch.name.label('branch'), func.count(Appointment.id).label('count'))
        .join(Appointment, Doctor.id == Appointment.doctor_id)
        .join(Branch, Branch.id == Appointment.branch_id)
        .filter(Appointment.status == 'BOOKED')
        .group_by(Doctor.id, Branch.name)
        .order_by(desc('count'))
        .limit(8)
        .all()
    )

    return {
        "total_appointments": total,
        "active_bookings": active,
        "cancelled_bookings": cancelled,
        "today_bookings": today_count,
        "by_branch": [{"branch": r.branch, "count": r.count} for r in by_branch],
        "by_department": [{"department": r.department, "count": r.count} for r in by_department],
        "top_doctors": [{"doctor": r.doctor, "branch": r.branch, "count": r.count} for r in top_doctors],
    }


@app.get("/admin/appointments")
def admin_list_appointments(
        principal: Principal = Depends(require_permission('APPOINTMENT_READ')),
        status_filter: Optional[str] = Query(None, alias="status"),
        branch_id: Optional[int] = Query(None),
        department_id: Optional[int] = Query(None),
        doctor_id: Optional[int] = Query(None),
        date_from: Optional[str] = Query(None),
        date_to: Optional[str] = Query(None),
        search: Optional[str] = Query(None, description="Matches patient name, mobile, or appointment code"),
        limit: int = Query(50, le=200, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    from sqlalchemy import or_, desc
    from backend.database.models import Appointment, Branch, Department, Doctor

    query = db.query(Appointment, Branch.name.label('branch_name'), Department.name.label('department_name'),
                     Doctor.name.label('doctor_name')). \
        join(Branch, Branch.id == Appointment.branch_id). \
        join(Department, Department.id == Appointment.department_id). \
        join(Doctor, Doctor.id == Appointment.doctor_id)

    if status_filter:
        query = query.filter(Appointment.status == status_filter)
    if branch_id:
        query = query.filter(Appointment.branch_id == branch_id)
    if department_id:
        query = query.filter(Appointment.department_id == department_id)
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    if date_from:
        query = query.filter(Appointment.appointment_date >= date_from)
    if date_to:
        query = query.filter(Appointment.appointment_date <= date_to)
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            Appointment.patient_name.ilike(search_term),
            Appointment.mobile.ilike(search_term),
            Appointment.appointment_code.ilike(search_term)
        ))

    total = query.count()
    rows = query.order_by(desc(Appointment.appointment_date), desc(Appointment.time_slot), desc(Appointment.id)).offset(
        offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "appointments": [
            {
                **{c.name: getattr(r.Appointment, c.name) for c in r.Appointment.__table__.columns},
                "branch_name": r.branch_name,
                "department_name": r.department_name,
                "doctor_name": r.doctor_name
            } for r in rows
        ],
    }


@app.post("/admin/appointments/{code}/cancel")
def admin_cancel_appointment(code: str, principal: Principal = Depends(require_permission('APPOINTMENT_MANAGE')),
                             db: Session = Depends(get_db)):
    """Staff cancel — authenticated via admin login instead of a mobile match."""
    from backend.database.models import Appointment
    appt = db.query(Appointment).filter(Appointment.appointment_code == code).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status == "CANCELLED":
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")
    _mark_cancelled(db, appt)
    notify_result = _notify_cancelled(db, appt)
    return {"status": "CANCELLED", "appointment_code": code, "notification_preview": notify_result["preview"]}

@app.get("/admin/departments")
def admin_list_departments(principal: Principal = Depends(require_permission('DEPARTMENT_READ')),
                           db: Session = Depends(get_db)):
    from backend.database.models import Department
    deps = db.query(Department).order_by(Department.name).all()
    return [{"id": d.id, "name": d.name, "description": d.description, "department_status": d.department_status} for d in deps]


@app.post("/admin/departments")
def admin_create_department(
        request: DepartmentCreateRequest,
        principal: Principal = Depends(require_permission('DEPARTMENT_MANAGE')),
        db: Session = Depends(get_db)
):
    from backend.database.models import Department
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Department name cannot be empty")
    existing = db.query(Department).filter(Department.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists")
    new_dept = Department(
        name=name,
        description=request.description,
        department_status=request.department_status
    )
    db.add(new_dept)
    db.commit()
    db.refresh(new_dept)
    return new_dept


@app.put("/admin/departments/{dept_id}")
def admin_update_department(
        dept_id: int,
        request: DepartmentUpdateRequest,
        principal: Principal = Depends(require_permission('DEPARTMENT_MANAGE')),
        db: Session = Depends(get_db)
):
    from backend.database.models import Department
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    
    if request.name is not None:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Department name cannot be empty")
        existing = db.query(Department).filter(Department.name.ilike(name), Department.id != dept_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Department already exists")
        dept.name = name
    if request.description is not None:
        dept.description = request.description
    if request.department_status is not None:
        dept.department_status = request.department_status
        
    db.commit()
    db.refresh(dept)
    return dept


@app.delete("/admin/departments/{dept_id}")
def admin_delete_department(
        dept_id: int,
        principal: Principal = Depends(require_permission('DEPARTMENT_MANAGE')),
        db: Session = Depends(get_db)
):
    from backend.database.models import Department, Doctor
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    
    docs_using = db.query(Doctor).filter(Doctor.department_id == dept_id).first()
    if docs_using:
        raise HTTPException(status_code=400, detail="Cannot delete department because it is currently assigned to doctors.")
        
    db.delete(dept)
    db.commit()
    return {"status": "deleted"}


@app.get("/admin/branches")
def admin_list_branches(principal: Principal = Depends(require_permission('BRANCH_READ')),
                        db: Session = Depends(get_db)):
    from backend.database.models import Branch
    query = db.query(Branch)
    if not principal.privileged:
        allowed_branch_ids = [s['branch_id'] for s in principal.scopes if s['branch_id'] is not None]
        query = query.filter(Branch.id.in_(allowed_branch_ids))
    branches = query.order_by(Branch.name).all()
    return [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "branch_status": b.branch_status} for b
            in branches]


@app.patch("/admin/branches/{branch_id}/status")
def admin_update_branch_status(
        branch_id: int,
        request: BranchStatusRequest,
        principal: Principal = Depends(require_permission('BRANCH_MANAGE')),
        db: Session = Depends(get_db)
):
    if request.branch_status not in ("OPEN", "CLOSED"):
        raise HTTPException(status_code=400, detail="branch_status must be OPEN or CLOSED")
    updated = update_branch_status(db, branch_id, request.branch_status)
    return updated


@app.post("/admin/branches")
def admin_create_branch(
        request: BranchCreateRequest,
        principal: Principal = Depends(require_permission('BRANCH_MANAGE')),
):
    try:
        with get_db() as conn:
            created = create_branch(conn, request.dict())
            return created
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/admin/branches/{branch_id}")
def admin_update_branch(
        branch_id: int,
        request: BranchUpdateRequest,
        principal: Principal = Depends(require_permission('BRANCH_MANAGE')),
        db: Session = Depends(get_db)
):
    try:
        updated = update_branch(db, branch_id, request.dict(exclude_unset=True))
        return updated
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "Branch not found" else 400
        raise HTTPException(status_code=code, detail=detail)


@app.delete("/admin/branches/{branch_id}")
def admin_delete_branch(
        branch_id: int,
        principal: Principal = Depends(require_permission('BRANCH_MANAGE')),
        db: Session = Depends(get_db)
):
    try:
        deleted = delete_branch(db, branch_id)
        return deleted
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "Branch not found" else 400
        raise HTTPException(status_code=code, detail=detail)


@app.get("/admin/doctors")
def admin_list_doctors(principal: Principal = Depends(require_permission('DOCTOR_READ')),
                       db: Session = Depends(get_db)):
    from backend.database.models import Doctor, Branch, Department
    query = db.query(Doctor, Branch.name.label('branch_name'), Department.name.label('department_name'))
    if not principal.privileged:
        allowed_branch_ids = [s['branch_id'] for s in principal.scopes if s['branch_id'] is not None]
        if allowed_branch_ids:
            query = query.filter(Doctor.branch_id.in_(allowed_branch_ids))
        allowed_dept_ids = [s['department_id'] for s in principal.scopes if s['department_id'] is not None]
        if allowed_dept_ids:
            query = query.filter(Doctor.department_id.in_(allowed_dept_ids))
    doctors = query. \
        join(Branch, Branch.id == Doctor.branch_id). \
        join(Department, Department.id == Doctor.department_id). \
        order_by(Branch.name, Department.name, Doctor.name).all()

    return [
        {
            **{c.name: getattr(r.Doctor, c.name) for c in r.Doctor.__table__.columns},
            "branch_name": r.branch_name,
            "department_name": r.department_name
        } for r in doctors
    ]


@app.post("/admin/doctors")
def admin_create_doctor(
        request: DoctorCreateRequest,
        principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
        db: Session = Depends(get_db)
):
    created = create_doctor(db, request.dict())
    return created


@app.put("/admin/doctors/{doctor_id}")
def admin_update_doctor(
        doctor_id: int,
        request: DoctorUpdateRequest,
        principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
        db: Session = Depends(get_db)
):
    updated = update_doctor(db, doctor_id, request.dict(exclude_unset=True))
    return updated


@app.delete("/admin/doctors/{doctor_id}")
def admin_delete_doctor(
        doctor_id: int,
        principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
        db: Session = Depends(get_db)
):
    deleted = delete_doctor(db, doctor_id)
    return deleted


@app.patch("/admin/doctors/{doctor_id}/status")
def admin_update_doctor_status(
        doctor_id: int,
        request: DoctorStatusRequest,
        principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
        db: Session = Depends(get_db)
):
    updated = update_doctor_status(db, doctor_id, request.doctor_status)
    return updated


@app.get("/doctors/{doctor_id}/availability")
def get_doctor_availability(doctor_id: int, principal: Principal = Depends(require_permission('DOCTOR_READ')),
                            db: Session = Depends(get_db)):
    from backend.database.models import Doctor, DoctorSchedule, DoctorSpecialAvailability
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_id).order_by(
        DoctorSchedule.day_of_week, DoctorSchedule.start_time).all()
    special = db.query(DoctorSpecialAvailability).filter(DoctorSpecialAvailability.doctor_id == doctor_id).order_by(
        DoctorSpecialAvailability.available_date, DoctorSpecialAvailability.start_time).all()

    return {
        "doctor": {c.name: getattr(doctor, c.name) for c in doctor.__table__.columns},
        "schedule": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in schedule],
        "special_availability": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in special]
    }


@app.post("/doctors/{doctor_id}/schedule")
def save_doctor_schedule(doctor_id: int, request: DoctorScheduleRequest,
                         principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
                         db: Session = Depends(get_db)):
    from backend.services.doctor_service import time_to_minutes
    if time_to_minutes(request.start_time) >= time_to_minutes(request.end_time):
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    from backend.database.models import Doctor, DoctorSchedule
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    new_sched = DoctorSchedule(
        doctor_id=doctor_id,
        day_of_week=request.day_of_week,
        start_time=request.start_time,
        end_time=request.end_time,
        slot_minutes=doctor.consultation_duration or 30
    )
    db.add(new_sched)
    db.commit()
    db.refresh(new_sched)
    return {c.name: getattr(new_sched, c.name) for c in new_sched.__table__.columns}


@app.delete("/doctors/{doctor_id}/schedule/{schedule_id}")
def remove_doctor_schedule(doctor_id: int, schedule_id: int,
                           principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
                           db: Session = Depends(get_db)):
    from backend.database.models import DoctorSchedule
    sched = db.query(DoctorSchedule).filter_by(id=schedule_id, doctor_id=doctor_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(sched)
    db.commit()
    return {"status": "deleted"}


@app.post("/doctors/{doctor_id}/special-availability")
def save_special_availability(doctor_id: int, request: SpecialAvailabilityRequest,
                              principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
                              db: Session = Depends(get_db)):
    try:
        date.fromisoformat(request.available_date)
        if not request.is_blocked:
            from backend.services.doctor_service import time_to_minutes
            if time_to_minutes(request.start_time) >= time_to_minutes(request.end_time):
                raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD and a valid start/end time")

    from backend.database.models import Doctor, DoctorSpecialAvailability
    if not db.query(Doctor).filter(Doctor.id == doctor_id).first():
        raise HTTPException(status_code=404, detail="Doctor not found")

    special = db.query(DoctorSpecialAvailability).filter_by(
        doctor_id=doctor_id,
        available_date=request.available_date,
        start_time=request.start_time,
        end_time=request.end_time
    ).first()

    if special:
        special.is_blocked = int(request.is_blocked)
    else:
        special = DoctorSpecialAvailability(
            doctor_id=doctor_id,
            available_date=request.available_date,
            start_time=request.start_time,
            end_time=request.end_time,
            is_blocked=int(request.is_blocked)
        )
        db.add(special)

    db.commit()
    return {"id": special.id, "message": "Special availability saved"}


@app.delete("/doctors/{doctor_id}/special-availability/{availability_id}")
def remove_special_availability(doctor_id: int, availability_id: int,
                                principal: Principal = Depends(require_permission('DOCTOR_MANAGE')),
                                db: Session = Depends(get_db)):
    from backend.database.models import DoctorSpecialAvailability
    special = db.query(DoctorSpecialAvailability).filter_by(id=availability_id, doctor_id=doctor_id).first()
    if not special:
        raise HTTPException(status_code=404, detail="Special availability not found")
    db.delete(special)
    db.commit()
    return {"status": "DELETED"}


@app.get("/admin/config/notifications")
def get_notification_config(principal: Principal = Depends(require_permission('USER_MANAGE'))):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    env_dict = dotenv.dotenv_values(env_file)
    return {
        "twilio_account_sid": env_dict.get("TWILIO_ACCOUNT_SID", ""),
        "twilio_auth_token": env_dict.get("TWILIO_AUTH_TOKEN", ""),
        "twilio_from_number": env_dict.get("TWILIO_FROM_NUMBER", ""),
        "smtp_host": env_dict.get("SMTP_HOST", ""),
        "smtp_port": env_dict.get("SMTP_PORT", ""),
        "smtp_username": env_dict.get("SMTP_USERNAME", ""),
        "smtp_password": env_dict.get("SMTP_PASSWORD", ""),
        "smtp_from": env_dict.get("SMTP_FROM", "")
    }


@app.post("/admin/config/notifications")
def set_notification_config(
        config: NotificationConfig,
        principal: Principal = Depends(require_permission('USER_MANAGE'))
):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_file):
        open(env_file, 'a').close()

    dotenv.set_key(env_file, "TWILIO_ACCOUNT_SID", config.twilio_account_sid, quote_mode="never")
    dotenv.set_key(env_file, "TWILIO_AUTH_TOKEN", config.twilio_auth_token, quote_mode="never")
    dotenv.set_key(env_file, "TWILIO_FROM_NUMBER", config.twilio_from_number, quote_mode="never")
    dotenv.set_key(env_file, "SMTP_HOST", config.smtp_host, quote_mode="never")
    dotenv.set_key(env_file, "SMTP_PORT", config.smtp_port, quote_mode="never")
    dotenv.set_key(env_file, "SMTP_USERNAME", config.smtp_username, quote_mode="never")
    dotenv.set_key(env_file, "SMTP_PASSWORD", config.smtp_password, quote_mode="never")
    dotenv.set_key(env_file, "SMTP_FROM", config.smtp_from, quote_mode="never")

    dotenv.load_dotenv(env_file, override=True)
    notifications.reload_config()

    return {"status": "success"}


@app.get("/admin/config/whatsapp")
def get_whatsapp_config(principal: Principal = Depends(require_permission('USER_MANAGE'))):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    env_dict = dotenv.dotenv_values(env_file)
    return {
        "access_token": env_dict.get("WHATSAPP_ACCESS_TOKEN", ""),
        "phone_number_id": env_dict.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        "business_account_id": env_dict.get("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
        "verify_token": env_dict.get("WHATSAPP_VERIFY_TOKEN", ""),
        "api_version": env_dict.get("WHATSAPP_API_VERSION", ""),
    }


@app.post("/admin/config/whatsapp")
def set_whatsapp_config(
        config: WhatsAppConfig,
        principal: Principal = Depends(require_permission('USER_MANAGE'))
):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_file):
        open(env_file, 'a').close()

    dotenv.set_key(env_file, "WHATSAPP_ACCESS_TOKEN", config.access_token, quote_mode="never")
    dotenv.set_key(env_file, "WHATSAPP_PHONE_NUMBER_ID", config.phone_number_id, quote_mode="never")
    dotenv.set_key(env_file, "WHATSAPP_BUSINESS_ACCOUNT_ID", config.business_account_id, quote_mode="never")
    dotenv.set_key(env_file, "WHATSAPP_VERIFY_TOKEN", config.verify_token, quote_mode="never")
    dotenv.set_key(env_file, "WHATSAPP_API_VERSION", config.api_version, quote_mode="never")

    dotenv.load_dotenv(env_file, override=True)

    # If backend/whatsapp.py exposes a reload_config() (mirroring
    # notifications.reload_config()), call it so the new token/IDs take
    # effect without a server restart. If your backend/whatsapp.py uses
    # different env var names or doesn't have this function yet, the
    # values are still saved to .env — add a reload_config() there (see
    # notifications.reload_config() for the pattern) or restart the server
    # to pick them up.
    reload_fn = getattr(whatsapp_module, "reload_config", None)
    if callable(reload_fn):
        reload_fn()

    return {"status": "success"}


@app.get("/admin/config/ai-providers")
def get_ai_provider_config(principal: Principal = Depends(require_permission('USER_MANAGE'))):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    env_dict = dotenv.dotenv_values(env_file)
    return {
        "active_provider": env_dict.get("AI_ACTIVE_PROVIDER", "gemini"),
        "gemini_api_key": env_dict.get("GEMINI_API_KEY", ""),
        "gemini_model": env_dict.get("GEMINI_MODEL", ""),
        "claude_api_key": env_dict.get("CLAUDE_API_KEY", ""),
        "claude_model": env_dict.get("CLAUDE_MODEL", ""),
        "openai_api_key": env_dict.get("OPENAI_API_KEY", ""),
        "openai_model": env_dict.get("OPENAI_MODEL", ""),
    }


@app.post("/admin/config/ai-providers")
def set_ai_provider_config(
        config: AIProviderConfig,
        principal: Principal = Depends(require_permission('USER_MANAGE'))
):
    import dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_file):
        open(env_file, 'a').close()

    valid_providers = {"gemini", "claude", "openai"}
    active_provider = config.active_provider if config.active_provider in valid_providers else "gemini"

    dotenv.set_key(env_file, "AI_ACTIVE_PROVIDER", active_provider, quote_mode="never")
    dotenv.set_key(env_file, "GEMINI_API_KEY", config.gemini_api_key, quote_mode="never")
    dotenv.set_key(env_file, "GEMINI_MODEL", config.gemini_model, quote_mode="never")
    dotenv.set_key(env_file, "CLAUDE_API_KEY", config.claude_api_key, quote_mode="never")
    dotenv.set_key(env_file, "CLAUDE_MODEL", config.claude_model, quote_mode="never")
    dotenv.set_key(env_file, "OPENAI_API_KEY", config.openai_api_key, quote_mode="never")
    dotenv.set_key(env_file, "OPENAI_MODEL", config.openai_model, quote_mode="never")

    dotenv.load_dotenv(env_file, override=True)

    return {"status": "success"}


# ---------------------------------------------------------------------------
# Patient Auth Endpoints
# ---------------------------------------------------------------------------
def _set_patient_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="varuvi_patient_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=6 * 60 * 60,
        path="/",
    )


def _clear_patient_auth_cookie(response: Response):
    response.delete_cookie(
        key="varuvi_patient_token",
        path="/",
    )


def get_current_patient_id(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("varuvi_patient_token")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_access_token(token)
    patient_id_db = payload.get("sub")
    if patient_id_db is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return int(patient_id_db)

@app.get("/patient/auth/session")
def get_patient_auth_session(patient_id: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=401, detail="Patient session invalid")

    return {
        "patient_id": patient.patient_id,
        "full_name": patient.full_name,
        "authenticated": True,
    }
class OTPRequest(BaseModel):
    mobile: str

class OTPVerifyRequest(BaseModel):
    mobile: str
    otp: str

class PatientActivateRequest(BaseModel):
    mobile: str
    otp: str


DEMO_OTP_STORE = {}
import random
import time

@app.post("/patient/auth/request-otp")
def request_otp(req: OTPRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    req.mobile = normalize_mobile_number(req.mobile)
    patient = db.query(Patient).filter(Patient.mobile == req.mobile).first()
    if not patient:
        raise HTTPException(status_code=404, detail="No patient found with this mobile number")
    
    otp = str(random.randint(100000, 999999))
    expires = time.time() + 300 # 5 minutes
    DEMO_OTP_STORE[req.mobile] = {"otp": otp, "expires": expires, "attempts": 0}
    
    logger.info("OTP generated for mobile")
    
    return {"message": "OTP sent successfully (Demo: check server logs)"}

@app.post("/patient/auth/verify-otp")
def verify_otp(req: OTPVerifyRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    req.mobile = normalize_mobile_number(req.mobile)
    record = DEMO_OTP_STORE.get(req.mobile)
    if not record:
        raise HTTPException(status_code=400, detail="OTP not requested or expired")
    
    if time.time() > record["expires"]:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="OTP expired")
        
    record["attempts"] += 1
    if record["attempts"] > 3:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="Too many failed attempts")
        
    if record["otp"] != req.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
        
    patient = db.query(Patient).filter(Patient.mobile == req.mobile).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    if patient.password_hash == "!BOOKING_ONLY!":
        # Keep the OTP in store so activate_patient can consume it
        return {"status": "otp_valid", "message": "OTP verified. Proceed to activation."}
        
    del DEMO_OTP_STORE[req.mobile]
    token = create_access_token(data={"sub": str(patient.id)})
    response = JSONResponse({"token": token, "patient_id": patient.patient_id})
    _set_patient_auth_cookie(response, token)
    return response


@app.post("/patient/auth/register")
def register_patient(req: PatientRegisterRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    from sqlalchemy import or_
    from sqlalchemy.exc import IntegrityError

    req.mobile = normalize_mobile_number(req.mobile)
    
    username_clash = db.query(Patient).filter(Patient.username == req.username).first()
    if username_clash and username_clash.password_hash != "!BOOKING_ONLY!":
        raise HTTPException(status_code=400, detail="Username already in use. Please choose another username.")

    mobile_clash = db.query(Patient).filter(Patient.mobile == req.mobile).first()

    if mobile_clash:
        if mobile_clash.password_hash == "!BOOKING_ONLY!":
            # Generate OTP and store credentials
            otp = str(random.randint(100000, 999999))
            expires = time.time() + 300
            DEMO_OTP_STORE[req.mobile] = {
                "otp": otp, 
                "expires": expires, 
                "attempts": 0,
                "pending_username": req.username,
                "pending_password": req.password
            }
            logger.info("Activation OTP generated for mobile")
            
            return JSONResponse(
                status_code=400, 
                content={
                    "status": "activation_required", 
                    "message": "We found an existing patient profile from your previous appointment booking. We sent a verification code to ******" + req.mobile[-4:],
                    "mobile": req.mobile
                }
            )
        else:
            raise HTTPException(status_code=400, detail="This mobile number is already registered for the Patient Portal.")

    patient_id = f"UHID-{random.randint(100000, 999999)}"
    hashed_pw = hash_password(req.password)

    new_patient = Patient(
        patient_id=patient_id,
        username=req.username,
        password_hash=hashed_pw,
        full_name=req.full_name,
        dob=req.dob,
        gender=req.gender,
        mobile=req.mobile,
        email=req.email,
        address=req.address,
        emergency_contact=req.emergency_contact,
        blood_group=req.blood_group,
        allergies=req.allergies,
        medical_history=req.medical_history
    )

    try:
        db.add(new_patient)
        db.commit()
        db.refresh(new_patient)

        token = create_access_token(data={"sub": str(new_patient.id)})
        response = JSONResponse({"token": token, "patient_id": patient_id})
        _set_patient_auth_cookie(response, token)
        return response
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Registration failed. Data constraint error.")


@app.post("/patient/auth/activate")
def activate_patient(req: PatientActivateRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    
    req.mobile = normalize_mobile_number(req.mobile)
    record = DEMO_OTP_STORE.get(req.mobile)
    if not record:
        raise HTTPException(status_code=400, detail="OTP not requested or expired")
    
    if time.time() > record["expires"]:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="OTP expired")
        
    record["attempts"] += 1
    if record["attempts"] > 3:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="Too many failed attempts")
        
    if record["otp"] != req.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
        
    pending_username = record.get("pending_username")
    pending_password = record.get("pending_password")
    del DEMO_OTP_STORE[req.mobile]
    
    patient = db.query(Patient).filter(Patient.mobile == req.mobile).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    if patient.password_hash != "!BOOKING_ONLY!":
        raise HTTPException(status_code=400, detail="Account is already activated. Please sign in.")
        
    if pending_username:
        username_clash = db.query(Patient).filter(Patient.username == pending_username).first()
        if username_clash and username_clash.id != patient.id:
            raise HTTPException(status_code=400, detail="Username already in use. Please choose another username.")
        patient.username = pending_username
        
    if pending_password:
        patient.password_hash = hash_password(pending_password)
        
    db.commit()
    
    token = create_access_token(data={"sub": str(patient.id)})
    response = JSONResponse({"token": token, "patient_id": patient.patient_id})
    _set_patient_auth_cookie(response, token)
    return response


@app.post("/patient/auth/activate")
def activate_patient(req: PatientActivateRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    
    req.mobile = normalize_mobile_number(req.mobile)
    record = DEMO_OTP_STORE.get(req.mobile)
    if not record:
        raise HTTPException(status_code=400, detail="OTP not requested or expired")
    
    if time.time() > record["expires"]:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="OTP expired")
        
    record["attempts"] += 1
    if record["attempts"] > 3:
        del DEMO_OTP_STORE[req.mobile]
        raise HTTPException(status_code=400, detail="Too many failed attempts")
        
    if record["otp"] != req.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
        
    del DEMO_OTP_STORE[req.mobile]
    
    patient = db.query(Patient).filter(Patient.mobile == req.mobile).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    if patient.password_hash != "!BOOKING_ONLY!":
        raise HTTPException(status_code=400, detail="Account is already activated. Please sign in.")
        
    username_clash = db.query(Patient).filter(Patient.username == req.username).first()
    if username_clash and username_clash.id != patient.id:
        raise HTTPException(status_code=400, detail="Username already in use. Please choose another username.")
        
    patient.username = req.username
    patient.password_hash = hash_password(req.password)
    db.commit()
    
    token = create_access_token(data={"sub": str(patient.id)})
    response = JSONResponse({"token": token, "patient_id": patient.patient_id})
    _set_patient_auth_cookie(response, token)
    return response


@app.post("/patient/auth/login")
def login_patient(req: PatientLoginRequest, db: Session = Depends(get_db)):
    from backend.database.models import Patient
    from sqlalchemy import or_

    normalized_login = normalize_mobile_number(req.username_or_mobile_or_email)
    patient = db.query(Patient).filter(
        or_(
            Patient.username == req.username_or_mobile_or_email,
            Patient.mobile == req.username_or_mobile_or_email,
            Patient.mobile == normalized_login,
            Patient.email == req.username_or_mobile_or_email
        )
    ).first()

    if not patient:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(req.password, patient.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if password_needs_upgrade(patient.password_hash):
        patient.password_hash = hash_password(req.password)
        db.commit()

    token = create_access_token(data={"sub": str(patient.id)})
    response = JSONResponse({"token": token})
    _set_patient_auth_cookie(response, token)
    return response


@app.post("/patient/auth/logout")
def logout_patient(response: Response):
    response_obj = JSONResponse({"success": True})
    _clear_patient_auth_cookie(response_obj)
    return response_obj


@app.post("/patient/auth/google")
def login_patient_google(req: GoogleAuthRequest, db: Session = Depends(get_db)):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id or client_id == "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com":
        raise HTTPException(status_code=500,
                            detail="Google OAuth is not configured. Please set GOOGLE_CLIENT_ID in the backend environment.")

    try:
        payload = id_token.verify_oauth2_token(req.credential, google_requests.Request(), client_id)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Google verification failed: {str(exc)}")

    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account does not include an email address.")

    full_name = (payload.get("name") or payload.get("given_name") or email.split("@", 1)[0]).strip()
    safe_username = "google_" + re.sub(r"[^a-zA-Z0-9_]", "_", email.split("@", 1)[0])
    if not safe_username:
        safe_username = f"google_user_{random.randint(1000, 9999)}"

    from backend.database.models import Patient
    from sqlalchemy import or_

    patient = db.query(Patient).filter(
        or_(Patient.email == email, Patient.username == safe_username)
    ).first()

    if patient is None:
        patient_id = f"UHID-{random.randint(100000, 999999)}"
        generated_mobile = f"9{random.randint(100000000, 999999999)}"
        while db.query(Patient).filter(Patient.mobile == generated_mobile).first():
            generated_mobile = f"9{random.randint(100000000, 999999999)}"

        username = safe_username
        while db.query(Patient).filter(Patient.username == username).first():
            username = f"{safe_username}_{random.randint(1000, 9999)}"

        patient = Patient(
            patient_id=patient_id,
            username=username,
            password_hash=hash_password(f"google-{random.randint(100000000, 999999999)}"),
            full_name=full_name,
            dob="2000-01-01",
            gender="Other",
            mobile=generated_mobile,
            email=email,
            address="Google verified patient address",
            emergency_contact="",
            blood_group="Not provided",
            allergies="",
            medical_history="Created from Google account"
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

    db_id = patient.id
    token = create_access_token(data={"sub": str(db_id)})
    return {"token": token,
            "patient": {"email": email, "full_name": full_name, "patient_id": patient.patient_id}}


# ---------------------------------------------------------------------------
# Patient Portal Endpoints
# ---------------------------------------------------------------------------
@app.get("/patient/me")
def get_patient_profile(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id_db).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {c.name: getattr(patient, c.name) for c in patient.__table__.columns}


@app.put("/patient/me")
def update_patient_profile(req: PatientProfileUpdate, patient_id_db: int = Depends(get_current_patient_id),
                           db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id_db).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient.full_name = req.full_name
    patient.dob = req.dob
    patient.gender = req.gender
    patient.mobile = req.mobile
    patient.email = req.email
    patient.address = req.address
    patient.emergency_contact = req.emergency_contact
    patient.blood_group = req.blood_group
    patient.allergies = req.allergies
    patient.medical_history = req.medical_history

    db.commit()
    db.refresh(patient)
    return {c.name: getattr(patient, c.name) for c in patient.__table__.columns}


@app.get("/patient/me/appointments")
def get_patient_appointments(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import Patient, Appointment, Doctor, Branch, Department
    patient = db.query(Patient).filter(Patient.id == patient_id_db).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    appointments = db.query(Appointment, Doctor.name.label('doctor_name'), Branch.name.label('branch_name'),
                            Department.name.label('department_name')). \
        join(Doctor, Doctor.id == Appointment.doctor_id). \
        join(Branch, Branch.id == Appointment.branch_id). \
        join(Department, Department.id == Appointment.department_id). \
        filter(Appointment.mobile == patient.mobile). \
        order_by(Appointment.appointment_date.desc(), Appointment.time_slot.desc()).all()

    return [
        {
            **{c.name: getattr(r.Appointment, c.name) for c in r.Appointment.__table__.columns},
            "doctor_name": r.doctor_name,
            "branch_name": r.branch_name,
            "department_name": r.department_name
        } for r in appointments
    ]


@app.post("/admin/appointments/{code}/complete")
def admin_complete_appointment(
        code: str,
        request: CompleteAppointmentRequest,
        principal: Principal = Depends(require_permission('APPOINTMENT_MANAGE')),
        db: Session = Depends(get_db)
):
    """Mark appointment as COMPLETED and create a consultation record."""
    from backend.database.models import Appointment, Patient, Consultation

    appt = db.query(Appointment).filter(Appointment.appointment_code == code).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    patient = db.query(Patient).filter(Patient.mobile == appt.mobile).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Patient not found in system")

    appt.status = 'COMPLETED'

    consultation = Consultation(
        appointment_id=appt.id,
        patient_id=patient.id,
        doctor_id=appt.doctor_id,
        consultation_date=appt.appointment_date,
        consultation_time=appt.time_slot,
        symptoms=request.symptoms,
        diagnosis=request.diagnosis,
        notes=request.notes or "",
        consultation_status='COMPLETED'
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    return {
        "status": "COMPLETED",
        "appointment_code": code,
        "consultation_id": consultation.id,
        "message": "Appointment marked as completed and consultation record created",
    }


@app.post("/admin/prescriptions")
def admin_create_prescription(
        request: CreatePrescriptionRequest,
        principal: Principal = Depends(require_permission('USER_MANAGE')),
        db: Session = Depends(get_db)
):
    """Create a prescription for a completed appointment."""
    import json
    from backend.database.models import Appointment, Patient, Consultation, Prescription, PrescriptionItem

    appt = db.query(Appointment).filter(Appointment.appointment_code == request.appointment_code).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if appt.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Appointment must be completed first")

    consultation = db.query(Consultation).filter(Consultation.appointment_id == appt.id).first()
    if not consultation:
        raise HTTPException(status_code=400, detail="No consultation record found for this appointment")

    patient = db.query(Patient).filter(Patient.mobile == appt.mobile).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Patient not found")

    medicines_json = json.dumps(request.medicines)

    prescription = Prescription(
        consultation_id=consultation.id,
        patient_id=patient.id,
        doctor_id=appt.doctor_id,
        prescription_date=date.today().isoformat(),
        medicines=medicines_json,
        instructions=request.instructions or "",
        validity_days=request.validity_days,
        status='ACTIVE'
    )

    db.add(prescription)
    db.commit()
    db.refresh(prescription)

    # audit(db, Principal(None, None, {"ADMIN"}, str(admin)), "PRESCRIPTION_CREATE", "prescription", prescription.id)

    audit(
        db,
        principal,
        "PRESCRIPTION_CREATE",
        "prescription",
        prescription.id
    )

    for medicine in request.medicines:
        item = PrescriptionItem(
            prescription_id=prescription.id,
            medicine_name=medicine.get("name") or medicine.get("medicine_name", ""),
            dosage=medicine.get("dosage"),
            frequency=medicine.get("frequency"),
            duration=medicine.get("duration"),
            route=medicine.get("route"),
            quantity=medicine.get("quantity"),
            instructions=medicine.get("instructions"),
            notes=medicine.get("notes")
        )
        db.add(item)

    db.commit()

    return {
        "status": "CREATED",
        "prescription_id": prescription.id,
        "appointment_code": request.appointment_code,
        "message": "Prescription created successfully",
    }


@app.post("/medical-reports/upload")
async def upload_medical_report(
        request: Request, filename: str = Query(..., min_length=1), patient_id: int = Query(...),
        consultation_id: int = Query(...), report_type: str = Query(...),
        principal: Principal = Depends(require_permission("MEDICAL_REPORT_UPLOAD")),
        db: Session = Depends(get_db)
):
    payload = await request.body()
    suffix, mime_type = _validate_medical_upload(filename, payload)
    from backend.database.models import Consultation, MedicalReport

    consultation = db.query(Consultation).filter_by(id=consultation_id, patient_id=patient_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found for patient")

    safe_name = f"{uuid.uuid4().hex}{suffix}"
    MEDICAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = (MEDICAL_UPLOAD_DIR / safe_name).resolve()
    if target.parent != MEDICAL_UPLOAD_DIR:
        raise HTTPException(status_code=400, detail="Invalid upload path")
    target.write_bytes(payload)

    report = MedicalReport(
        consultation_id=consultation_id,
        patient_id=patient_id,
        doctor_id=consultation.doctor_id,
        report_name=Path(filename).stem[:200],
        report_type=report_type,
        report_date=date.today().isoformat(),
        file_path=safe_name,
        original_filename=Path(filename).name,
        mime_type=mime_type,
        file_size=len(payload),
        uploaded_by=principal.user_id,
        status='COMPLETED'
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    audit(db, principal, "REPORT_UPLOAD", "medical_report", report.id,
          ip_address=request.client.host if request.client else None)
    return {"id": report.id, "status": "UPLOADED", "mime_type": mime_type}


@app.get("/medical-reports/{report_id}/download")
def download_medical_report(report_id: int, request: Request,
                            principal: Principal = Depends(require_permission("MEDICAL_REPORT_READ")),
                            db: Session = Depends(get_db)):
    from backend.database.models import MedicalReport
    report = db.query(MedicalReport).filter(MedicalReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Medical report not found")

    # We pass dict(report) if assert_report_access expects a dict
    report_dict = {c.name: getattr(report, c.name) for c in report.__table__.columns}
    assert_report_access(db, principal, report_dict)

    if not report.file_path:
        raise HTTPException(status_code=404, detail="This legacy report has no uploaded document")

    target = (MEDICAL_UPLOAD_DIR / Path(report.file_path).name).resolve()
    if target.parent != MEDICAL_UPLOAD_DIR or not target.is_file():
        raise HTTPException(status_code=404, detail="Medical document not found")

    audit(db, principal, "REPORT_DOWNLOAD", "medical_report", report_id,
          ip_address=request.client.host if request.client else None)
    from fastapi.responses import FileResponse
    return FileResponse(target, media_type=report.mime_type or "application/octet-stream",
                        filename=report.original_filename or f"report-{report_id}")

@app.get("/patient/medical-reports/{report_id}/download")
def patient_download_medical_report(report_id: int, patient_id: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import MedicalReport
    report = db.query(MedicalReport).filter(MedicalReport.id == report_id, MedicalReport.patient_id == patient_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Medical report not found")
        
    target = (MEDICAL_UPLOAD_DIR / Path(report.file_path).name).resolve()
    if target.parent != MEDICAL_UPLOAD_DIR or not target.is_file():
        raise HTTPException(status_code=404, detail="Medical document not found")
        
    from fastapi.responses import FileResponse
    return FileResponse(target, media_type=report.mime_type or "application/octet-stream",
                        filename=report.original_filename or f"report-{report_id}")


@app.post("/admin/medical-reports")
def admin_create_medical_report(
        request: CreateMedicalReportRequest,
        principal: Principal = Depends(require_permission('APPOINTMENT_READ')),
        db: Session = Depends(get_db)
):
    """Create a medical report for a completed appointment."""
    from backend.database.models import Appointment, Consultation, Patient, MedicalReport

    appt = db.query(Appointment).filter(Appointment.appointment_code == request.appointment_code).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if appt.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Appointment must be completed first")

    consultation = db.query(Consultation).filter(Consultation.appointment_id == appt.id).first()
    if not consultation:
        raise HTTPException(status_code=400, detail="No consultation record found for this appointment")

    patient = db.query(Patient).filter(Patient.mobile == appt.mobile).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Patient not found")

    report = MedicalReport(
        consultation_id=consultation.id,
        patient_id=patient.id,
        doctor_id=appt.doctor_id,
        report_name=request.report_name,
        report_type=request.report_type,
        report_date=date.today().isoformat(),
        findings=request.findings or "",
        status=request.status
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "status": "CREATED",
        "report_id": report.id,
        "appointment_code": request.appointment_code,
        "message": "Medical report created successfully",
    }


@app.get("/patient/me/consultations")
def get_patient_consultations(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import Consultation, Doctor
    consultations = db.query(Consultation, Doctor.name.label('doctor_name')). \
        join(Doctor, Doctor.id == Consultation.doctor_id). \
        filter(Consultation.patient_id == patient_id_db). \
        order_by(Consultation.consultation_date.desc()).all()

    return [
        {
            **{c.name: getattr(r.Consultation, c.name) for c in r.Consultation.__table__.columns},
            "doctor_name": r.doctor_name
        } for r in consultations
    ]


@app.get("/patient/me/prescriptions")
def get_patient_prescriptions(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    import json
    from backend.database.models import Prescription, Doctor, Department, Consultation

    prescriptions = db.query(Prescription, Doctor.name.label('doctor_name'), Doctor.department_id,
                             Department.name.label('department_name'), Consultation.diagnosis). \
        join(Doctor, Doctor.id == Prescription.doctor_id). \
        join(Department, Department.id == Doctor.department_id). \
        join(Consultation, Consultation.id == Prescription.consultation_id). \
        filter(Prescription.patient_id == patient_id_db). \
        order_by(Prescription.prescription_date.desc()).all()

    result = []
    for r in prescriptions:
        p_dict = {c.name: getattr(r.Prescription, c.name) for c in r.Prescription.__table__.columns}
        p_dict["doctor_name"] = r.doctor_name
        p_dict["department_id"] = r.department_id
        p_dict["department_name"] = r.department_name
        p_dict["diagnosis"] = r.diagnosis
        try:
            p_dict["medicines"] = json.loads(p_dict["medicines"])
        except:
            p_dict["medicines"] = []
        result.append(p_dict)

    return result


@app.get("/patient/me/reports")
def get_patient_reports(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import MedicalReport, Doctor, Department

    reports = db.query(MedicalReport, Doctor.name.label('doctor_name'), Department.name.label('department_name')). \
        join(Doctor, Doctor.id == MedicalReport.doctor_id). \
        join(Department, Department.id == Doctor.department_id). \
        filter(MedicalReport.patient_id == patient_id_db). \
        order_by(MedicalReport.report_date.desc()).all()

    return [
        {
            **{c.name: getattr(r.MedicalReport, c.name) for c in r.MedicalReport.__table__.columns},
            "doctor_name": r.doctor_name,
            "department_name": r.department_name
        } for r in reports
    ]


@app.get("/patient/me/timeline")
def get_patient_timeline(patient_id_db: int = Depends(get_current_patient_id), db: Session = Depends(get_db)):
    from backend.database.models import Patient, Appointment, Doctor, Branch, Department, MedicalReport, Prescription
    from sqlalchemy import or_

    patient = db.query(Patient).filter(Patient.id == patient_id_db).first()
    if not patient:
        return []

    appts = db.query(Appointment, Doctor.name.label('doctor_name'), Branch.name.label('branch_name'),
                     Department.name.label('department_name')). \
        join(Doctor, Doctor.id == Appointment.doctor_id). \
        join(Branch, Branch.id == Appointment.branch_id). \
        join(Department, Department.id == Appointment.department_id). \
        filter(or_(Appointment.mobile == patient.mobile, Appointment.patient_id == patient_id_db)).all()

    timeline = []
    for a in appts:
        appt = a.Appointment
        if appt.status in ("BOOKED", "CONFIRMED"):
            timeline.append({
                "date": appt.appointment_date,
                "time": appt.time_slot,
                "title": f"Appointment {appt.status.capitalize()}",
                "description": f"With Dr. {a.doctor_name} at {a.branch_name}.",
                "type": "APPOINTMENT_BOOKED"
            })
        elif appt.status == "CANCELLED":
            timeline.append({
                "date": appt.appointment_date,
                "time": appt.time_slot,
                "title": f"Appointment Cancelled",
                "description": f"Cancelled appointment with Dr. {a.doctor_name}.",
                "type": "APPOINTMENT_CANCELLED"
            })
        elif appt.status == "COMPLETED":
            timeline.append({
                "date": appt.appointment_date,
                "time": appt.time_slot,
                "title": f"Consultation Completed",
                "description": f"Diagnosis completed by Dr. {a.doctor_name}.",
                "type": "CONSULTATION_COMPLETED"
            })

    # Include Medical Reports
    reports = db.query(MedicalReport).filter(MedicalReport.patient_id == patient_id_db).all()
    for r in reports:
        timeline.append({
            "date": r.report_date,
            "time": "00:00",
            "title": f"Medical Report: {r.report_name}",
            "description": f"Type: {r.report_type}, Status: {r.status}",
            "type": "LAB_REPORT_UPLOADED"
        })

    # Include Prescriptions
    prescriptions = db.query(Prescription).filter(Prescription.patient_id == patient_id_db).all()
    for p in prescriptions:
        timeline.append({
            "date": p.prescription_date,
            "time": "00:00",
            "title": "Prescription Issued",
            "description": "Medicines prescribed.",
            "type": "PRESCRIPTION_CREATED"
        })

    timeline.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return timeline


# ---------------------------------------------------------------------------
# Admin Patient Endpoints
# ---------------------------------------------------------------------------
@app.get("/admin/patients/export")
def export_patients(format: str = Query("csv", pattern="^(csv|xlsx)$"),
                    principal: Principal = Depends(require_permission('PATIENT_READ')), db: Session = Depends(get_db)):
    from backend.database.models import Patient, Branch, Department

    patients = db.query(Patient, Branch.name.label('branch'), Department.name.label('department')). \
        outerjoin(Branch, Branch.id == Patient.branch_id). \
        outerjoin(Department, Department.id == Patient.department_id). \
        order_by(Patient.created_at.desc()).all()

    values = [[r.Patient.patient_id, r.Patient.full_name, r.Patient.age, r.Patient.mobile, r.branch, r.department,
               r.Patient.symptoms, r.Patient.created_at, r.Patient.status, r.Patient.email] for r in patients]

    if format == "xlsx":
        return StreamingResponse(io.BytesIO(_xlsx_bytes(PATIENT_EXPORT_COLUMNS, values)),
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": "attachment; filename=patients.xlsx"})
    output = io.StringIO();
    writer = csv.writer(output);
    writer.writerow(PATIENT_EXPORT_COLUMNS);
    writer.writerows(values)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=patients.csv"})


@app.post("/admin/patients/import/preview")
async def preview_patient_import(request: Request, filename: str = Query(..., min_length=5),
                                 principal: Principal = Depends(require_permission('PATIENT_UPDATE'))):
    raw = await request.body()
    # Keeping raw SQLite for validation until _validate_patient_import is fully refactored, or pass engine
    from backend.database.db import engine
    with engine.connect() as conn:
        valid, errors = _validate_patient_import(conn, _read_import_rows(raw, filename))
    token = uuid.uuid4().hex
    PATIENT_IMPORT_PREVIEWS[token] = valid
    return {"token": token, "total": len(valid) + len(errors), "valid": len(valid), "invalid": len(errors),
            "errors": errors}


@app.post("/admin/patients/import/commit")
def commit_patient_import(request: PatientImportCommitRequest,
                          principal: Principal = Depends(require_permission('PATIENT_UPDATE')),
                          db: Session = Depends(get_db)):
    rows = PATIENT_IMPORT_PREVIEWS.pop(request.token, None)
    if rows is None:
        raise HTTPException(status_code=400, detail="Import preview expired; upload and preview the file again")
    created = updated = 0
    from backend.database.models import Patient

    for row in rows:
        row["mobile"] = normalize_mobile_number(row["mobile"])
        existing = db.query(Patient).filter(Patient.mobile == row["mobile"]).first()
        if existing:
            existing.full_name = row["name"]
            existing.age = row["age"]
            existing.branch_id = row["branch_id"]
            existing.department_id = row["department_id"]
            existing.symptoms = row["symptoms"]
            if row.get("email"):
                existing.email = row["email"]
            updated += 1
        else:
            suffix = "".join(random.choices(string.digits, k=8))
            new_patient = Patient(
                patient_id=row.get("patient_code") or f"PAT{suffix}",
                username=f"import_{suffix}",
                password_hash="!IMPORT_ONLY!",
                full_name=row["name"],
                dob="",
                gender="UNSPECIFIED",
                mobile=row["mobile"],
                email=row.get("email"),
                address="Not provided",
                age=row["age"],
                branch_id=row["branch_id"],
                department_id=row["department_id"],
                symptoms=row["symptoms"]
            )
            db.add(new_patient)
            created += 1

    db.commit()
    return {"status": "IMPORTED", "created": created, "updated": updated, "processed": created + updated}


@app.get("/admin/patients")
def admin_get_patients(principal: Principal = Depends(require_permission('PATIENT_READ')),
                       db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patients = db.query(Patient).order_by(Patient.created_at.desc()).all()
    return [{c.name: getattr(p, c.name) for c in p.__table__.columns} for p in patients]


@app.delete("/admin/patients/{patient_id}")
def admin_delete_patient(patient_id: int, principal: Principal = Depends(require_permission('PATIENT_UPDATE')),
                         db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    db.delete(patient)
    db.commit()
    return {"success": True, "deleted_id": patient_id}


@app.put("/admin/patients/{patient_id}")
def admin_update_patient(patient_id: int, req: PatientProfileUpdate,
                         principal: Principal = Depends(require_permission('PATIENT_UPDATE')),
                         db: Session = Depends(get_db)):
    from backend.database.models import Patient
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient.full_name = req.full_name
    patient.dob = req.dob
    patient.gender = req.gender
    patient.mobile = req.mobile
    patient.email = req.email
    patient.address = req.address
    patient.emergency_contact = req.emergency_contact
    patient.blood_group = req.blood_group
    patient.allergies = req.allergies
    patient.medical_history = req.medical_history

    db.commit()
    db.refresh(patient)
    return {c.name: getattr(patient, c.name) for c in patient.__table__.columns}


@app.get("/admin/patients/{patient_id}/history")
def admin_get_patient_history(patient_id: int, principal: Principal = Depends(require_permission('PATIENT_READ')),
                              db: Session = Depends(get_db)):
    import json
    from sqlalchemy import or_
    from backend.database.models import Patient, Appointment, Consultation, Prescription, MedicalReport, Doctor, Branch, \
        Department

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    mobile = patient.mobile

    appts = db.query(Appointment, Doctor.name.label('doctor_name'), Branch.name.label('branch_name'),
                     Department.name.label('department_name')). \
        join(Doctor, Doctor.id == Appointment.doctor_id). \
        join(Branch, Branch.id == Appointment.branch_id). \
        join(Department, Department.id == Appointment.department_id). \
        filter(or_(Appointment.mobile == mobile, Appointment.patient_id == patient_id)). \
        order_by(Appointment.appointment_date.desc(), Appointment.time_slot.desc()).all()

    appts_list = []
    for a in appts:
        item = {c.name: getattr(a.Appointment, c.name) for c in a.Appointment.__table__.columns}
        item["doctor_name"] = a.doctor_name
        item["branch_name"] = a.branch_name
        item["department_name"] = a.department_name
        appts_list.append(item)

    consultations = db.query(Consultation, Doctor.name.label('doctor_name'), Department.name.label('department_name')). \
        join(Doctor, Doctor.id == Consultation.doctor_id). \
        join(Department, Department.id == Doctor.department_id). \
        filter(Consultation.patient_id == patient_id). \
        order_by(Consultation.consultation_date.desc()).all()

    consultations_list = []
    for c in consultations:
        item = {col.name: getattr(c.Consultation, col.name) for col in c.Consultation.__table__.columns}
        item["doctor_name"] = c.doctor_name
        item["department_name"] = c.department_name
        consultations_list.append(item)

    prescriptions_query = db.query(Prescription, Doctor.name.label('doctor_name'),
                                   Department.name.label('department_name'), Consultation.diagnosis). \
        join(Doctor, Doctor.id == Prescription.doctor_id). \
        join(Department, Department.id == Doctor.department_id). \
        join(Consultation, Consultation.id == Prescription.consultation_id). \
        filter(Prescription.patient_id == patient_id). \
        order_by(Prescription.prescription_date.desc()).all()

    prescriptions_list = []
    for p in prescriptions_query:
        item = {c.name: getattr(p.Prescription, c.name) for c in p.Prescription.__table__.columns}
        item["doctor_name"] = p.doctor_name
        item["department_name"] = p.department_name
        item["diagnosis"] = p.diagnosis
        try:
            item["medicines"] = json.loads(item["medicines"])
        except Exception:
            item["medicines"] = []
        prescriptions_list.append(item)

    reports = db.query(MedicalReport, Doctor.name.label('doctor_name'), Department.name.label('department_name')). \
        join(Doctor, Doctor.id == MedicalReport.doctor_id). \
        join(Department, Department.id == Doctor.department_id). \
        filter(MedicalReport.patient_id == patient_id). \
        order_by(MedicalReport.report_date.desc()).all()

    reports_list = []
    for r in reports:
        item = {c.name: getattr(r.MedicalReport, c.name) for c in r.MedicalReport.__table__.columns}
        item["doctor_name"] = r.doctor_name
        item["department_name"] = r.department_name
        reports_list.append(item)

    timeline = []
    for a in appts_list:
        if a["status"] in ("BOOKED", "CONFIRMED"):
            timeline.append({
                "date": a["appointment_date"],
                "time": a["time_slot"],
                "title": f"Appointment {a['status'].capitalize()}",
                "description": f"With Dr. {a['doctor_name']} at {a['branch_name']}.",
                "type": "APPOINTMENT_BOOKED"
            })
        elif a["status"] == "CANCELLED":
            timeline.append({
                "date": a["appointment_date"],
                "time": a["time_slot"],
                "title": "Appointment Cancelled",
                "description": f"Cancelled appointment with Dr. {a['doctor_name']}.",
                "type": "APPOINTMENT_CANCELLED"
            })
        elif a["status"] == "COMPLETED":
            consult = next((c for c in consultations_list if c["appointment_id"] == a["id"]), None)
            diagnosis = consult["diagnosis"] if consult else "Consultation completed"
            timeline.append({
                "date": a["appointment_date"],
                "time": a["time_slot"],
                "title": "Consultation Completed",
                "description": f"Diagnosis: {diagnosis} by Dr. {a['doctor_name']}",
                "type": "CONSULTATION_COMPLETED"
            })

    timeline.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return {
        "timeline": timeline,
        "appointments": appts_list,
        "consultations": consultations_list,
        "prescriptions": prescriptions_list,
        "reports": reports_list,
    }


# ---------------------------------------------------------------------------
# Admin Conversation Endpoints (WhatsApp bot + website widget + AI chatbot)
#
# One row per PERSON (keyed by mobile number, or an anonymous website
# session until a number is captured) — not one row per channel. A user
# who messaged on WhatsApp and later used the website widget with the
# same number shows up once, with every message from both channels in
# their single thread.
# ---------------------------------------------------------------------------

@app.get("/admin/conversations")
def admin_list_conversations(
        principal: Principal = Depends(require_permission('CONVERSATION_READ')),
        source: Optional[str] = Query(None,
                                      description="Only include users who have at least one message on this channel: WEB | WHATSAPP | CHATBOT"),
        search: Optional[str] = Query(None, description="Matches user name or mobile"),
        limit: int = Query(100, le=500, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    from sqlalchemy import text

    # We can write this query via SQLAlchemy ORM or text
    # Since it's a complex aggregation, we can use `text()` or build it.
    where = ["EXISTS (SELECT 1 FROM conversation_messages m0 WHERE m0.chat_user_id = chat_users.id)"]
    params = {}

    if source:
        where.append(
            "EXISTS (SELECT 1 FROM conversation_messages m1 WHERE m1.chat_user_id = chat_users.id AND m1.source = :source)")
        params["source"] = source
    if search:
        where.append("(COALESCE(patients.full_name, chat_users.name) LIKE :search OR chat_users.mobile LIKE :search)")
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where)
    params["limit"] = limit
    params["offset"] = offset

    query = f"""
        SELECT
            chat_users.id,
            chat_users.mobile,
            COALESCE(patients.full_name, chat_users.name) AS user_name,
            chat_users.patient_id,
            (SELECT text FROM conversation_messages m2 WHERE m2.chat_user_id = chat_users.id ORDER BY m2.id DESC LIMIT 1) AS last_message,
            (SELECT timestamp FROM conversation_messages m2 WHERE m2.chat_user_id = chat_users.id ORDER BY m2.id DESC LIMIT 1) AS last_message_at,
            (SELECT COUNT(*) FROM conversation_messages m2 WHERE m2.chat_user_id = chat_users.id) AS message_count,
            (SELECT GROUP_CONCAT(DISTINCT m2.source) FROM conversation_messages m2 WHERE m2.chat_user_id = chat_users.id) AS sources
        FROM chat_users
        LEFT JOIN patients ON patients.id = chat_users.patient_id
        WHERE {where_sql}
        ORDER BY last_message_at DESC
        LIMIT :limit OFFSET :offset
    """

    rows = db.execute(text(query), params).fetchall()

    results = []
    for r in rows:
        item = {
            "id": r.id,
            "mobile": r.mobile,
            "user_name": r.user_name,
            "patient_id": r.patient_id,
            "last_message": r.last_message,
            "last_message_at": r.last_message_at,
            "message_count": r.message_count,
            "sources": r.sources.split(",") if r.sources else []
        }
        results.append(item)
    return results


@app.get("/admin/conversations/{chat_user_id}/messages")
def admin_get_conversation_messages(chat_user_id: int,
                                    principal: Principal = Depends(require_permission('CONVERSATION_READ')),
                                    db: Session = Depends(get_db)):
    from backend.database.models import ChatUser, ConversationMessage

    user = db.query(ChatUser).filter(ChatUser.id == chat_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(ConversationMessage).filter(ConversationMessage.chat_user_id == chat_user_id).order_by(
        ConversationMessage.id.asc()).all()

    return [
        {
            "source": m.source,
            "sender": m.sender,
            "text": m.text,
            "timestamp": m.timestamp
        } for m in messages
    ]


@app.get("/admin/roles")
def get_roles(principal: Principal = Depends(require_permission("ROLE_MANAGE")), db: Session = Depends(get_db)):
    from backend.database.models import Role
    roles = db.query(Role).order_by(Role.id.asc()).all()
    return [{"id": r.id, "name": r.name,
             "is_system_role": r.name in ["SUPER_ADMIN", "ADMIN", "BRANCH_ADMIN", "DEPARTMENT_ADMIN", "DOCTOR", "LAB",
                                          "XRAY", "RECEPTIONIST", "PATIENT"]} for r in roles]


@app.get("/admin/permissions")
def get_permissions(principal: Principal = Depends(require_permission("ROLE_MANAGE")), db: Session = Depends(get_db)):
    from backend.database.models import Permission
    perms = db.query(Permission).order_by(Permission.module.asc(), Permission.id.asc()).all()
    return [{"id": p.id, "code": p.name, "name": p.description or p.name, "description": p.description or p.name,
             "module": p.module} for p in perms]


@app.get("/admin/roles/{role_id}")
def get_role(role_id: int, principal: Principal = Depends(require_permission("ROLE_MANAGE")),
             db: Session = Depends(get_db)):
    from backend.database.models import Role, RolePermission, Permission
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    perms = db.query(Permission).join(RolePermission, RolePermission.permission_id == Permission.id).filter(
        RolePermission.role_id == role_id).all()
    is_system = role.name in ["SUPER_ADMIN", "ADMIN", "BRANCH_ADMIN", "DEPARTMENT_ADMIN", "DOCTOR", "LAB", "XRAY",
                              "RECEPTIONIST", "PATIENT"]

    return {
        "id": role.id,
        "name": role.name,
        "is_system_role": is_system,
        "permissions": [
            {"id": p.id, "code": p.name, "name": p.description or p.name, "description": p.description or p.name,
             "module": p.module} for p in perms]
    }


@app.put("/admin/roles/{role_id}/permissions")
def update_role_permissions(role_id: int, req: RolePermissionsUpdate,
                            principal: Principal = Depends(require_permission("ROLE_MANAGE")),
                            db: Session = Depends(get_db)):
    from backend.database.models import Role, Permission, RolePermission
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.name == "SUPER_ADMIN":
        raise HTTPException(status_code=400, detail="Cannot modify SUPER_ADMIN role")

    valid_perms_query = db.query(Permission).all()
    valid_perms = {p.name: p.id for p in valid_perms_query}

    for p in req.permissions:
        if p not in valid_perms:
            raise HTTPException(status_code=400, detail=f"Invalid permission code: {p}")

    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()

    for p in req.permissions:
        rp = RolePermission(role_id=role_id, permission_id=valid_perms[p])
        db.add(rp)

    db.commit()
    audit(db, principal, "ROLE_PERMISSION_UPDATE", "Role", role_id, result="SUCCESS")
    clear_permission_cache()

    broadcast_event_sync("role_permissions_changed", {"role_name": role.name})

    return {"message": "Permissions updated successfully"}


@app.post("/admin/roles")
def create_role(req: RoleCreateRequest, principal: Principal = Depends(require_permission("ROLE_MANAGE")),
                db: Session = Depends(get_db)):
    from backend.database.models import Role, Permission, RolePermission
    existing = db.query(Role).filter(Role.name == req.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role name already exists")

    new_role = Role(name=req.name)
    db.add(new_role)
    db.commit()
    db.refresh(new_role)
    role_id = new_role.id

    valid_perms_query = db.query(Permission).all()
    valid_perms = {p.name: p.id for p in valid_perms_query}

    for p in req.permissions:
        if p in valid_perms:
            rp = RolePermission(role_id=role_id, permission_id=valid_perms[p])
            db.add(rp)

    db.commit()
    audit(db, principal, "ROLE_CREATE", "Role", role_id, result="SUCCESS")
    clear_permission_cache()
    return {"id": role_id, "name": req.name}


@app.get("/health")
def health():
    return {"ok": True, "time": now_iso()}





@app.post("/conversation/message", response_model=ConversationTurnResponse)
def handle_conversation_message(req: ConversationMessageRequest, db: Session = Depends(get_db)):
    try:
        result = process_message(db, req.chat_user_id, req.source, req.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversation/{chat_user_id}")
def get_conversation_context(chat_user_id: int, db: Session = Depends(get_db)):
    meta = get_active_conversation(db, chat_user_id)
    if not meta:
        raise HTTPException(status_code=404, detail="No active conversation found")
    return meta


@app.get("/conversation/{chat_user_id}/history", response_model=list[ConversationHistoryItem])
def get_conversation_history_endpoint(chat_user_id: int, db: Session = Depends(get_db)):
    meta = get_active_conversation(db, chat_user_id)
    if not meta:
        raise HTTPException(status_code=404, detail="No active conversation found")
    return get_conversation_history(db, meta)


@app.post("/conversation/{chat_user_id}/reset")
def reset_conversation_endpoint(chat_user_id: int, db: Session = Depends(get_db)):
    reset_conversation(db, chat_user_id)
    return {"message": "Conversation reset successfully"}
