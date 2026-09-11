from typing import Optional

from fastapi import HTTPException

from backend.database.db import get_db_ctx

from .translations import t, ASK_LANGUAGE_TEXT, LANGUAGE_OPTIONS

DATE_LOOKAHEAD_DAYS = 4
MAX_OPTIONS = 10  # WhatsApp interactive lists cap at 10 rows per section


def _resolve_main():
    try:
        from backend import main as backend_main
        return backend_main
    except ImportError:
        import main as script_main
        return script_main


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _reply(text: str, options=None, done: bool = False) -> dict:
    return {"text": text, "options": options or [], "done": done}


def _opt(id_: str, title: str, description: str = "") -> dict:
    return {"id": id_, "title": title[:60], "description": description[:72]}


def _parse_option(option_id: str):
    """'branch:3' -> ('branch', '3')"""
    category, _, value = (option_id or "").partition(":")
    return category, value


GLOBAL_RESTART_WORDS = {
    "menu", "restart", "cancel booking", "start over",
    "மெனு", "மீண்டும் தொடங்கு", "பதிவை ரத்து செய்",
}
# Typing this anywhere (outside free-text data states) re-opens the
# language picker without wiping the rest of the session.
GLOBAL_LANGUAGE_WORDS = {"language", "மொழி"}
# States where free text typed by the user IS the data being collected —
# global restart/language words are NOT intercepted here, so "menu" typed as
# an address, for instance, is taken literally.
FREE_TEXT_DATA_STATES = {
    "ASK_NAME", "ASK_AGE", "ASK_MOBILE",
    "ASK_REASON", "TRACK_ENTER_CODE", "TRACK_ENTER_MOBILE",
}


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def handle_message(session: dict, text: Optional[str] = None,
                    option_id: Optional[str] = None,
                    contact_phone: Optional[str] = None) -> dict:
    """Advances the conversation by one turn. Mutates `session` in place —
    caller is responsible for persisting it (chat_session.save_session)."""
    text = (text or "").strip()

    if option_id is None and text.lower() in GLOBAL_RESTART_WORDS \
            and session.get("state") not in FREE_TEXT_DATA_STATES:
        lang = session.get("lang")  # a "menu"/"restart" shouldn't force re-picking the language
        session.clear()
        if lang:
            session["lang"] = lang
            session["state"] = "MENU"
        else:
            session["state"] = "START"

    elif option_id is None and text.lower() in GLOBAL_LANGUAGE_WORDS \
            and session.get("state") not in FREE_TEXT_DATA_STATES \
            and session.get("state") not in (None, "START"):
        # Keep everything else in session (branch picked, patient name typed
        # so far, etc.) — just park them on the language picker and resume
        # afterwards via the _lang_change flag.
        session["_lang_change"] = True
        session["state"] = "SELECT_LANGUAGE"

    state = session.get("state", "START")
    handler = _HANDLERS.get(state, _h_start)
    try:
        result = handler(session, text, option_id, contact_phone)
    except HTTPException as exc:
        # Any of _resolve_main().py's endpoint functions raising a 4xx/5xx becomes a
        # friendly chat message instead of a crash.
        session["state"] = "MENU"
        result = _reply(
            t(session, "error_generic", detail=exc.detail),
            options=_menu_options(session),
        )

    # Recorded centrally (rather than in each handler) so EVERY screen with
    # buttons — menu, gender, mobile-confirm, confirm/cancel, etc, not just
    # branch/department/doctor/date/slot — can have its tapped option_id
    # resolved back to the human-readable title it showed. Callers (e.g.
    # webchat.py's conversation logger) read this before their next call
    # to look up what the *previous* screen's tap actually said.
    session["_last_options"] = result.get("options") or []
    return result



def _menu_options(session):
    return [
        _opt("menu:book", t(session, "btn_book_appt")),
        _opt("menu:track", t(session, "btn_track_appt")),
        _opt("menu:lang", t(session, "btn_language")),
    ]


# ---------------------------------------------------------------------------
# START / MENU
# ---------------------------------------------------------------------------

def _h_start(session, text, option_id, contact_phone):
    session.clear()
    session["state"] = "SELECT_LANGUAGE"
    return _reply(ASK_LANGUAGE_TEXT, options=LANGUAGE_OPTIONS)


def _h_select_language(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)

    if category == "lang" and value in ("en", "ta"):
        session["lang"] = value
    else:
        # No / unrecognised tap — show the picker again (bilingual, since we
        # still don't reliably know their preference).
        return _reply(ASK_LANGUAGE_TEXT, options=LANGUAGE_OPTIONS)

    session["state"] = "MENU"
    if session.pop("_lang_change", False):
        return _reply(t(session, "menu_after_lang_change"), options=_menu_options(session))
    return _reply(t(session, "welcome_menu"), options=_menu_options(session))


def _h_menu(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)

    if category == "menu" and value == "book":
        return _start_branch_selection(session)
    if category == "menu" and value == "track":
        session["state"] = "TRACK_ENTER_CODE"
        return _reply(t(session, "track_ask_code"))
    if category == "menu" and value == "lang":
        session["_lang_change"] = True
        session["state"] = "SELECT_LANGUAGE"
        return _reply(ASK_LANGUAGE_TEXT, options=LANGUAGE_OPTIONS)

    # No / unrecognised selection — re-show the menu
    return _reply(
        t(session, "menu_reprompt"),
        options=_menu_options(session),
    )


# ---------------------------------------------------------------------------
# BOOKING: branch -> department -> doctor -> date -> slot
# ---------------------------------------------------------------------------

def _start_branch_selection(session):
    with get_db_ctx() as db:
        branches = _resolve_main().list_branches(db=db)
    if not branches:
        session["state"] = "MENU"
        return _reply(t(session, "no_branches"), options=_menu_options(session))
    session["state"] = "SELECT_BRANCH"
    options = [_opt(f"branch:{b['id']}", b["name"]) for b in branches[:MAX_OPTIONS]]
    session["_last_options"] = options
    return _reply(t(session, "branch_prompt"), options=options)


def _h_select_branch(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category != "branch":
        return _reply(t(session, "tap_branch_again"),
                       options=session.get("_last_options", []))

    branch_id = int(value)
    with get_db_ctx() as db:
        departments = _resolve_main().list_departments(branch_id=branch_id, db=db)
    if not departments:
        return _reply(t(session, "no_departments"),
                       options=session.get("_last_options", []))

    branch_name = next((o["title"] for o in session.get("_last_options", []) if o["id"] == option_id), "")
    session["branch_id"] = branch_id
    session["branch_name"] = branch_name
    session["state"] = "SELECT_DEPARTMENT"
    options = [_opt(f"dept:{d['id']}", d["name"]) for d in departments[:MAX_OPTIONS]]
    session["_last_options"] = options
    return _reply(t(session, "dept_prompt"), options=options)


def _h_select_department(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)

    if category == "dept":
        department_id = int(value)
        dept_title = next((o["title"] for o in session.get("_last_options", []) if o["id"] == option_id), "")
        session.pop("_symptoms_captured", None)
        session.pop("reason", None)
        return _enter_department(session, department_id, dept_title)

    # No button tapped — treat the free text as a symptom description and
    # let the Ollama-backed recommend_department() (via analyze_symptoms)
    # pick the right department, same logic already used on the website.
    if len(text) < 3:
        return _reply(
            t(session, "dept_too_short"),
            options=session.get("_last_options", []),
        )

    with get_db_ctx() as db:
        result = _resolve_main().analyze_symptoms(
            _resolve_main().SymptomAnalysisRequest(symptoms=text, branch_id=session["branch_id"], language=session.get("lang", "en")),
            db=db
        )
    session["reason"] = text          # symptoms already given — reused as the visit reason
    session["_symptoms_captured"] = True
    reply = _enter_department(session, result["department_id"], result["department_name"])
    reply["text"] = (
        t(session, "symptom_suggestion",
          department=result["department_name"], explanation=result.get("explanation", ""))
        + reply["text"]
    )
    return reply


def _enter_department(session, department_id: int, department_name: str) -> dict:
    """Shared by both the tap path and the Ollama symptom path: locks in the
    department, then moves straight into patient-details collection (doctor
    selection happens afterwards, once we know who we're booking for)."""
    session["department_id"] = department_id
    session["department_name"] = department_name
    session["state"] = "ASK_NAME"
    session["_last_options"] = []
    return _reply(t(session, "ask_name_intro"))


def _start_doctor_selection(session) -> dict:
    """Called once all patient details are collected (end of the ASK_*
    chain). Fetches doctors for the branch+department chosen earlier."""
    with get_db_ctx() as db:
        doctors = _resolve_main().list_doctors(branch_id=session["branch_id"], department_id=session["department_id"], db=db)
    if not doctors:
        session["state"] = "MENU"
        return _reply(t(session, "no_doctors"), options=_menu_options(session))
    session["state"] = "SELECT_DOCTOR"
    options = [
        _opt(f"doc:{d['id']}", f"Dr. {d['name']}", d.get("qualification", ""))
        for d in doctors[:MAX_OPTIONS]
    ]
    session["_last_options"] = options
    return _reply(t(session, "doctor_prompt"), options=options)


def _h_select_doctor(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category != "doc":
        return _reply(t(session, "tap_doctor_again"),
                       options=session.get("_last_options", []))

    doctor_id = int(value)
    doc_title = next((o["title"] for o in session.get("_last_options", []) if o["id"] == option_id), "")
    with get_db_ctx() as db:
        dates = _resolve_main().available_dates(doctor_id=doctor_id, days=DATE_LOOKAHEAD_DAYS, db=db)
    dates = [d for d in dates if not d["full"]]
    if not dates:
        return _reply(t(session, "no_dates"),
                       options=session.get("_last_options", []))

    session["doctor_id"] = doctor_id
    session["doctor_name"] = doc_title
    session["state"] = "SELECT_DATE"
    options = [
        _opt(f"date:{d['date']}", d["date"], f"{d['weekday']} · {d['free_slots']} slots free")
        for d in dates[:MAX_OPTIONS]
    ]
    session["_last_options"] = options
    return _reply(t(session, "date_prompt"), options=options)


def _h_select_date(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category != "date":
        return _reply(t(session, "tap_date_again"),
                       options=session.get("_last_options", []))

    with get_db_ctx() as db:
        slots = _resolve_main().doctor_slots(doctor_id=session["doctor_id"], appointment_date=value, db=db)
    free_slots = [s["time"] for s in slots if s["status"] == "AVAILABLE"]
    if not free_slots:
        return _reply(t(session, "no_slots"),
                       options=session.get("_last_options", []))

    session["appointment_date"] = value
    session["state"] = "SELECT_SLOT"
    options = [_opt(f"slot:{s}", s) for s in free_slots[:MAX_OPTIONS]]
    session["_last_options"] = options
    return _reply(t(session, "slot_prompt"), options=options)


def _h_select_slot(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category != "slot":
        return _reply(t(session, "tap_slot_again"),
                       options=session.get("_last_options", []))

    session["time_slot"] = value
    session["state"] = "CONFIRM"
    session["_last_options"] = []
    summary = t(
        session, "confirm_summary",
        patient=session["patient_name"],
        age_gender=f"{session.get('age') or '—'} / {session.get('gender')}",
        mobile=session["mobile"],
        branch=session.get("branch_name") or "—",
        department=session.get("department_name") or "—",
        doctor=session.get("doctor_name") or "—",
        date=session["appointment_date"],
        time=session["time_slot"],
    )
    return _reply(summary, options=[_opt("confirm:yes", t(session, "btn_confirm")),
                                     _opt("confirm:no", t(session, "btn_cancel"))])


# ---------------------------------------------------------------------------
# PATIENT DETAILS COLLECTION
# ---------------------------------------------------------------------------

def _h_ask_name(session, text, option_id, contact_phone):
    if len(text) < 1:
        return _reply(t(session, "ask_name_invalid"))
    session["patient_name"] = text
    session["state"] = "ASK_AGE"
    return _reply(t(session, "ask_age"))


def _h_ask_age(session, text, option_id, contact_phone):
    if (option_id and _parse_option(option_id) == ("age", "skip")) or text.lower() == "skip":
        session["age"] = None
    elif text.isdigit() and 0 < int(text) < 120:
        session["age"] = int(text)
    else:
        return _reply(t(session, "ask_age_invalid"))
    session["state"] = "ASK_GENDER"
    return _reply(t(session, "gender_prompt"),
                   options=[_opt("gender:Male", t(session, "btn_male")),
                            _opt("gender:Female", t(session, "btn_female")),
                            _opt("gender:Other", t(session, "btn_other"))])


def _h_ask_gender(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category == "gender":
        session["gender"] = value
    elif text:
        session["gender"] = text
    else:
        return _reply(t(session, "gender_prompt"),
                       options=[_opt("gender:Male", t(session, "btn_male")),
                                _opt("gender:Female", t(session, "btn_female")),
                                _opt("gender:Other", t(session, "btn_other"))])
    session["state"] = "ASK_MOBILE"
    if contact_phone:
        return _reply(
            t(session, "mobile_confirm_prompt", contact_phone=contact_phone),
            options=[_opt(f"mobile:{contact_phone}", t(session, "btn_use_number")),
                     _opt("mobile:other", t(session, "btn_use_other"))],
        )
    return _reply(t(session, "ask_mobile"))


def _h_ask_mobile(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category == "mobile" and value != "other":
        session["mobile"] = value
    elif category == "mobile" and value == "other":
        return _reply(t(session, "ask_mobile_other"))
    elif text and (text.isdigit() or text.replace("+", "").isdigit()) and len(text) >= 7:
        session["mobile"] = text
    else:
        return _reply(t(session, "ask_mobile_invalid"))
    if session.get("_symptoms_captured"):
        return _start_doctor_selection(session)
    session["state"] = "ASK_REASON"
    return _reply(t(session, "ask_reason_prompt"))


def _h_ask_email(session, text, option_id, contact_phone):
    if text.lower() == "skip" or (option_id and _parse_option(option_id) == ("email", "skip")):
        session["email"] = None
    elif "@" in text and "." in text:
        session["email"] = text
    else:
        return _reply(t(session, "ask_email_invalid"))
    session["state"] = "ASK_ADDRESS"
    return _reply(t(session, "ask_address"))


def _h_ask_address(session, text, option_id, contact_phone):
    if len(text) < 1:
        return _reply(t(session, "ask_address_invalid"))
    session["address"] = text

    if session.get("_symptoms_captured"):
        # Symptoms were already typed at the department-selection step and
        # stored as the reason — don't ask a second time.
        return _start_doctor_selection(session)

    session["state"] = "ASK_REASON"
    return _reply(t(session, "ask_reason_prompt2"))


def _h_ask_reason(session, text, option_id, contact_phone):
    if text.lower() == "skip":
        session["reason"] = ""
    else:
        session["reason"] = text
    # Patient details are now complete — move on to doctor/date/slot.
    return _start_doctor_selection(session)


# ---------------------------------------------------------------------------
# CONFIRM & BOOK  (calls the real book_appointment() from _resolve_main().py)
# ---------------------------------------------------------------------------

def _h_confirm(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category != "confirm":
        return _reply(t(session, "confirm_tap_again"),
                       options=[_opt("confirm:yes", t(session, "btn_confirm")),
                                _opt("confirm:no", t(session, "btn_cancel"))])

    if value == "no":
        lang = session.get("lang")  # preserve language choice across the reset
        session.clear()
        session["state"] = "MENU"
        if lang:
            session["lang"] = lang
        return _reply(t(session, "booking_discarded"), options=_menu_options(session))

    if session.get("reschedule_code"):
        with get_db_ctx() as db:
            req = _resolve_main().RescheduleRequest(
                appointment_date=session["appointment_date"],
                time_slot=session["time_slot"],
                mobile=session["reschedule_mobile"]
            )
            try:
                result = _resolve_main().reschedule_appointment(
                    code=session["reschedule_code"],
                    req=req,
                    mobile=session["reschedule_mobile"],
                    db=db
                )
            except HTTPException as e:
                result = {"status": "CONFLICT", "message": e.detail}

        if result.get("status") == "CONFLICT":
            session["state"] = "SELECT_SLOT"
            alt = result.get("alternatives") or []
            alt_text = (t(session, "alt_prefix") + ", ".join(alt[:5])) if alt else ""
            return _reply(t(session, "slot_conflict", message=result["message"], alt_text=alt_text),
                           options=session.get("_last_options", []))

        lang = session.get("lang")
        session.clear()
        if lang:
            session["lang"] = lang
        session["state"] = "MENU"
        return _reply(
            t(session, "reschedule_success", date=req.appointment_date, time=req.time_slot) + "\n\n" + t(session, "type_menu_more"),
            options=_menu_options(session)
        )

    # Otherwise, Normal Booking Logic
    req = _resolve_main().BookRequest(
        patient_name=session["patient_name"],
        age=session.get("age"),
        gender=session.get("gender"),
        mobile=session["mobile"],
        email=None,
        address="",
        reason=session.get("reason", ""),
        branch_id=session["branch_id"],
        department_id=session["department_id"],
        doctor_id=session["doctor_id"],
        appointment_date=session["appointment_date"],
        time_slot=session["time_slot"],
    )
    with get_db_ctx() as db:
        result = _resolve_main().book_appointment(req, db=db)

    if result.get("status") == "CONFLICT":
        session["state"] = "SELECT_SLOT"
        alt = result.get("alternatives") or []
        alt_text = (t(session, "alt_prefix") + ", ".join(alt[:5])) if alt else ""
        return _reply(t(session, "slot_conflict", message=result["message"], alt_text=alt_text),
                       options=session.get("_last_options", []))

    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    session["state"] = "MENU"
    s = result["summary"]
    return _reply(
        t(session, "booking_success",
          code=result["appointment_code"], patient=s["patient_name"], doctor=s["doctor"],
          department=s["department"], branch=s["branch"], date=s["date"], time=s["time"]),
        options=_menu_options(session),
        done=True,
    )


# ---------------------------------------------------------------------------
# TRACK / CANCEL
# ---------------------------------------------------------------------------

def _h_track_enter_code(session, text, option_id, contact_phone):
    if not text:
        return _reply(t(session, "track_code_invalid"))
    session["track_code"] = text.strip().upper()
    session["state"] = "TRACK_ENTER_MOBILE"
    return _reply(t(session, "track_ask_mobile"))


def _h_track_enter_mobile(session, text, option_id, contact_phone):
    if not text or len(text) < 7:
        return _reply(t(session, "ask_mobile_invalid"))

    with get_db_ctx() as db:
        appt = _resolve_main().lookup_appointment(code=session["track_code"], mobile=text.strip(), db=db)
    session["track_mobile"] = text.strip()
    session["state"] = "TRACK_RESULT"

    body = t(
        session, "track_result_body",
        code=appt["appointment_code"], patient=appt["patient_name"], doctor=appt["doctor_name"],
        department=appt["department_name"], branch=appt["branch_name"],
        date=appt["appointment_date"], time=appt["time_slot"], status=appt["status"],
    )

    if appt["status"] == "CONFIRMED":
        return _reply(body, options=[_opt("track:reschedule", t(session, "btn_reschedule_appt")),
                                      _opt("track:cancel", t(session, "btn_cancel_appt")),
                                      _opt("menu:book", t(session, "btn_book_another"))])
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    session["state"] = "MENU"
    return _reply(body + t(session, "type_menu_more"), options=_menu_options(session))


def _h_track_result(session, text, option_id, contact_phone):
    category, value = _parse_option(option_id) if option_id else (None, None)
    if category == "menu" and value == "book":
        return _start_branch_selection(session)
    if category == "track" and value == "reschedule":
        with get_db_ctx() as db:
            from backend.database.models import Appointment, Doctor, Branch, Department
            row = db.query(Appointment).filter(Appointment.appointment_code == session["track_code"]).first()
            if not row or row.mobile != session["track_mobile"]:
                raise HTTPException(status_code=404, detail="No appointment found")
            
            doctor_id = row.doctor_id
            doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
            branch = db.query(Branch).filter(Branch.id == row.branch_id).first()
            department = db.query(Department).filter(Department.id == row.department_id).first()
            dates = _resolve_main().available_dates(doctor_id=doctor_id, days=DATE_LOOKAHEAD_DAYS, db=db)
            
            # Extract attributes before session closes!
            doctor_name = doctor.name if doctor else "Unknown"
            branch_name = branch.name if branch else "Unknown"
            department_name = department.name if department else "Unknown"
            patient_name = row.patient_name
            age = row.age
            gender = row.gender
            mobile = row.mobile
            
        dates = [d for d in dates if not d["full"]]
        if not dates:
            return _reply(t(session, "no_dates"),
                           options=[_opt("menu:start", t(session, "btn_book_another"))])
                           
        session["doctor_id"] = doctor_id
        session["doctor_name"] = doctor_name
        session["branch_name"] = branch_name
        session["department_name"] = department_name
        session["patient_name"] = patient_name
        session["age"] = age
        session["gender"] = gender
        session["mobile"] = mobile
        
        session["reschedule_code"] = session["track_code"]
        session["reschedule_mobile"] = session["track_mobile"]
        session["state"] = "SELECT_DATE"
        
        options = [
            _opt(f"date:{d['date']}", d["date"], f"{d['weekday']} · {d['free_slots']} slots free")
            for d in dates[:MAX_OPTIONS]
        ]
        session["_last_options"] = options
        return _reply(t(session, "reschedule_date_prompt"), options=options)

    if category == "track" and value == "cancel":
        with get_db_ctx() as db:
            result = _resolve_main().cancel_appointment(
                code=session["track_code"],
                mobile=session["track_mobile"],
                db=db
            )
        lang = session.get("lang")
        session.clear()
        if lang:
            session["lang"] = lang
        session["state"] = "MENU"
        return _reply(
            t(session, "cancel_success", code=result["appointment_code"]) + t(session, "type_menu_more"),
            options=_menu_options(session),
        )
    return _reply(t(session, "choose_option_generic"),
                  options=[_opt("track:cancel", t(session, "btn_cancel_appt")),
                           _opt("menu:book", t(session, "btn_book_another"))])


# ---------------------------------------------------------------------------
# dispatch table
# ---------------------------------------------------------------------------




_HANDLERS = {
    "START": _h_start,
    "SELECT_LANGUAGE": _h_select_language,
    "MENU": _h_menu,
    "SELECT_BRANCH": _h_select_branch,
    "SELECT_DEPARTMENT": _h_select_department,
    "SELECT_DOCTOR": _h_select_doctor,
    "SELECT_DATE": _h_select_date,
    "SELECT_SLOT": _h_select_slot,
    "ASK_NAME": _h_ask_name,
    "ASK_AGE": _h_ask_age,
    "ASK_GENDER": _h_ask_gender,
    "ASK_MOBILE": _h_ask_mobile,
    "ASK_EMAIL": _h_ask_email,
    "ASK_ADDRESS": _h_ask_address,
    "ASK_REASON": _h_ask_reason,
    "CONFIRM": _h_confirm,
    "TRACK_ENTER_CODE": _h_track_enter_code,
    "TRACK_ENTER_MOBILE": _h_track_enter_mobile,
    "TRACK_RESULT": _h_track_result,
}