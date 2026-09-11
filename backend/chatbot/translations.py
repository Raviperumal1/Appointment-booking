
DEFAULT_LANG = "en"


# ============================================================================
# LANGUAGE SELECTION
# ============================================================================

ASK_LANGUAGE_TEXT = (
    "🌐 Please select your preferred language.\n"
    "உங்கள் விருப்ப மொழியைத் தேர்வு செய்யவும்."
)


LANGUAGE_OPTIONS = [
    {
        "id": "lang:en",
        "title": "English",
    },
    {
        "id": "lang:ta",
        "title": "தமிழ்",
    },
]


# ============================================================================
# TRANSLATIONS
# ============================================================================

TRANSLATIONS = {

    # ========================================================================
    # MAIN MENU
    # ========================================================================

    "welcome_menu": {
        "en": (
            "👋 Hi! Welcome to Varuvi.\n\n"
            "I can help you book an appointment "
            "or track/cancel an existing one.\n\n"
            "What would you like to do?"
        ),
        "ta": (
            "👋 வணக்கம்! Varuvi-க்கு வரவேற்கிறோம்.\n\n"
            "முன்பதிவு செய்யலாம், ஏற்கனவே உள்ள முன்பதிவைப் பார்க்கலாம் "
            "அல்லது ரத்து செய்யலாம்.\n\n"
            "என்ன செய்ய வேண்டும்?"
        ),
    },

    "menu_after_lang_change": {
        "en": "Language updated ✅\n\nWhat would you like to do?",
        "ta": "மொழி மாற்றப்பட்டது ✅\n\nஎன்ன செய்ய வேண்டும்?",
    },

    "btn_book_appt": {
        "en": "📅 Book Appointment",
        "ta": "📅 முன்பதிவு",
    },

    "btn_track_appt": {
        "en": "🔎 Track / Cancel Appointment",
        "ta": "🔎 முன்பதிவைப் பார்க்க / ரத்து செய்ய",
    },

    "btn_language": {
        "en": "🌐 Language",
        "ta": "🌐 மொழி",
    },

    "menu_reprompt": {
        "en": "Please choose an option below 👇",
        "ta": "ஒரு விருப்பத்தைத் தேர்வு செய்யவும் 👇",
    },


    # ========================================================================
    # TRACK APPOINTMENT
    # ========================================================================

    "track_ask_code": {
        "en": "Sure — please enter your *appointment code* (e.g. APT2508170123).",
        "ta": (
            "உங்கள் *முன்பதிவு குறியீட்டை* உள்ளிடவும் "
            "(எ.கா. APT2508170123)."
        ),
    },

    "track_code_invalid": {
        "en": "Please enter your *appointment code*.",
        "ta": "உங்கள் *முன்பதிவு குறியீட்டை* உள்ளிடவும்.",
    },

    "track_ask_mobile": {
        "en": "Thanks — what *mobile number* did you use for that booking?",
        "ta": "முன்பதிவுக்கு பயன்படுத்திய *மொபைல் எண்ணை* உள்ளிடவும்.",
    },


    # ========================================================================
    # BRANCH
    # ========================================================================

    "no_branches": {
        "en": "No *branches* are open for booking right now. Please try again later.",
        "ta": (
            "தற்போது எந்த *கிளையிலும்* முன்பதிவு இல்லை.\n"
            "பிறகு முயற்சிக்கவும்."
        ),
    },

    "branch_prompt": {
        "en": "Great! Which *branch* would you like to visit?",
        "ta": "எந்த *கிளையை* தேர்வு செய்ய வேண்டும்?",
    },

    "tap_branch_again": {
        "en": "Please tap a *branch* from the list above.",
        "ta": "மேலே உள்ள பட்டியலில் ஒரு *கிளையை* தேர்வு செய்யவும்.",
    },


    # ========================================================================
    # DEPARTMENT
    # ========================================================================

    "no_departments": {
        "en": "That branch has no *departments* open right now. Pick another branch.",
        "ta": (
            "இந்தக் கிளையில் தற்போது *மருத்துவத் துறைகள்* இல்லை.\n"
            "வேறு *கிளையை* தேர்வு செய்யவும்."
        ),
    },

    "dept_prompt": {
        "en": (
            "Choose a *department* 👇 or describe your *symptoms*, "
            "and I'll suggest the right department."
        ),
        "ta": (
            "*மருத்துவத் துறையை* தேர்வு செய்யவும் 👇\n"
            "அல்லது உங்கள் *அறிகுறிகளை* சொல்லுங்கள்."
        ),
    },

    "dept_too_short": {
        "en": (
            "Please tap a *department* above, or describe your *symptoms* "
            "in a few more words so I can suggest the right department."
        ),
        "ta": (
            "மேலே உள்ள *மருத்துவத் துறையை* தேர்வு செய்யவும் "
            "அல்லது உங்கள் *அறிகுறிகளை* சற்று விரிவாக சொல்லுங்கள்."
        ),
    },

    "symptom_suggestion": {
        "en": (
            "Based on your *symptoms*, *{department}* department is suitable.\n"
        ),
        "ta": (
            "உங்கள் *அறிகுறிகளை* வைத்து "
            "*{department}* துறை சரியாக இருக்கும்.\n"
        ),
    },


    # ========================================================================
    # PATIENT DETAILS
    # ========================================================================

    "ask_name_intro": {
        "en": (
            "What is the patient's *full name*?"
        ),
        "ta": (
            "நோயாளியின் *முழுப் பெயர்* என்ன?"
        ),
    },

    "ask_name_invalid": {
        "en": "Please enter the patient's *full name*.",
        "ta": "நோயாளியின் *முழுப் பெயரை* உள்ளிடவும்.",
    },

    "ask_age": {
        "en": "What is the patient's *age*?",
        "ta": "நோயாளியின் *வயது*?",
    },

    "ask_age_invalid": {
        "en": (
            "Please enter a valid *age* in years (numbers only), "
            "or type *skip*."
        ),
        "ta": (
            "சரியான *வயதை* எண்களில் உள்ளிடவும் "
            "அல்லது *skip* என உள்ளிடவும்."
        ),
    },

    "ask_mobile": {
        "en": "What is the patient's *mobile number*?",
        "ta": "நோயாளியின் *மொபைல் எண்*?",
    },

    "ask_mobile_invalid": {
        "en": "Please enter a valid *mobile number* (10+ digits).",
        "ta": "சரியான *மொபைல் எண்ணை* உள்ளிடவும் (10+ இலக்கங்கள்).",
    },

    "ask_mobile_other": {
        "en": "Please enter the *mobile number* to use.",
        "ta": "பயன்படுத்த வேண்டிய *மொபைல் எண்ணை* உள்ளிடவும்.",
    },

    "ask_email_invalid": {
        "en": "Please enter a valid *email address*.",
        "ta": "சரியான *மின்னஞ்சல் முகவரியை* உள்ளிடவும்.",
    },

    "ask_address": {
        "en": "What is the patient's *address*?",
        "ta": "நோயாளியின் *முகவரி*?",
    },

    "ask_address_invalid": {
        "en": "Please enter the patient's *address*.",
        "ta": "நோயாளியின் *முகவரியை* உள்ளிடவும்.",
    },


    # ========================================================================
    # GENDER
    # ========================================================================

    "gender_prompt": {
        "en": "Please choose an option.",
        "ta": "ஒரு விருப்பத்தைத் தேர்வு செய்யவும்.",
    },

    "btn_male": {
        "en": "Male",
        "ta": "ஆண்",
    },

    "btn_female": {
        "en": "Female",
        "ta": "பெண்",
    },

    "btn_other": {
        "en": "Other",
        "ta": "மற்றவை",
    },


    # ========================================================================
    # WHATSAPP MOBILE CONFIRMATION
    # ========================================================================

    "mobile_confirm_prompt": {
        "en": (
            "Use this *WhatsApp number* ({contact_phone}) "
            "for booking confirmation and reminders?"
        ),
        "ta": (
            "முன்பதிவு உறுதிப்படுத்தவும் நினைவூட்டவும் "
            "இந்த *WhatsApp எண்ணை* ({contact_phone}) பயன்படுத்தலாமா?"
        ),
    },

    "btn_use_number": {
        "en": "Yes, use this number",
        "ta": "ஆம், இந்த எண்ணைப் பயன்படுத்தலாம்",
    },

    "btn_use_other": {
        "en": "Use a different number",
        "ta": "வேறு எண்ணைப் பயன்படுத்தலாம்",
    },


    # ========================================================================
    # REASON / SYMPTOMS
    # ========================================================================

    "ask_reason_prompt": {
        "en": "Please describe the *symptoms* for this visit.",
        "ta": "இந்தச் சந்திப்புக்கான *அறிகுறிகளை* சொல்லுங்கள்.",
    },

    "ask_reason_prompt2": {
        "en": "Any specific *reason / symptoms* for the visit?",
        "ta": "இந்தச் சந்திப்புக்கான *காரணம் / அறிகுறிகள்* உள்ளதா?",
    },


    # ========================================================================
    # DOCTOR
    # ========================================================================

    "no_doctors": {
        "en": "Sorry, no *doctors* are available in that department. Please try another department.",
        "ta": (
            "மன்னிக்கவும், இந்தத் துறையில் தற்போது *மருத்துவர்* இல்லை.\n"
            "வேறு *துறையை* தேர்வு செய்யவும்."
        ),
    },

    "doctor_prompt": {
        "en": "Thanks! Now choose a *doctor*:",
        "ta": "இப்போது *மருத்துவரை* தேர்வு செய்யவும்:",
    },

    "tap_doctor_again": {
        "en": "Please tap a *doctor* from the list above.",
        "ta": "மேலே உள்ள பட்டியலில் ஒரு *மருத்துவரை* தேர்வு செய்யவும்.",
    },


    # ========================================================================
    # DATE
    # ========================================================================

    "no_dates": {
        "en": "This doctor has no free *slots* in the next few days. Pick another doctor.",
        "ta": (
            "இந்த மருத்துவருக்கு அடுத்த சில நாட்களில் காலி *நேரங்கள்* இல்லை.\n"
            "வேறு *மருத்துவரை* தேர்வு செய்யவும்."
        ),
    },

    "date_prompt": {
        "en": "Pick a *date*:",
        "ta": "*தேதியை* தேர்வு செய்யவும்:",
    },

    "tap_date_again": {
        "en": "Please tap a *date* from the list above.",
        "ta": "மேலே உள்ள பட்டியலில் ஒரு *தேதியை* தேர்வு செய்யவும்.",
    },


    # ========================================================================
    # TIME SLOT
    # ========================================================================

    "no_slots": {
        "en": "No free *time slots* left on that date. Pick another date.",
        "ta": (
            "அந்தத் தேதியில் காலி *நேரங்கள்* இல்லை.\n"
            "வேறு *தேதியை* தேர்வு செய்யவும்."
        ),
    },

    "slot_prompt": {
        "en": "Pick a *time slot*:",
        "ta": "*நேரத்தை* தேர்வு செய்யவும்:",
    },

    "tap_slot_again": {
        "en": "Please tap a *time slot* from the list above.",
        "ta": "மேலே உள்ள பட்டியலில் ஒரு *நேரத்தை* தேர்வு செய்யவும்.",
    },


    # ========================================================================
    # CONFIRMATION
    # ========================================================================

    "confirm_summary": {
        "en": (
            "📋 *Please confirm your appointment:*\n\n"
            "Patient: *{patient}*\n"
            "Age/Gender: *{age_gender}*\n"
            "Mobile: *{mobile}*\n"
            "Branch: *{branch}*\n"
            "Department: *{department}*\n"
            "Doctor: *{doctor}*\n"
            "Date: *{date}*\n"
            "Time: *{time}*\n"
        ),
        "ta": (
            "📋 *முன்பதிவு விவரங்களை உறுதிசெய்யவும்:*\n\n"
            "நோயாளர்: *{patient}*\n"
            "வயது/பாலினம்: *{age_gender}*\n"
            "மொபைல்: *{mobile}*\n"
            "கிளை: *{branch}*\n"
            "துறை: *{department}*\n"
            "மருத்துவர்: *{doctor}*\n"
            "தேதி: *{date}*\n"
            "நேரம்: *{time}*\n"
        ),
    },

    "btn_confirm": {
        "en": "✅ Confirm Booking",
        "ta": "✅ உறுதிசெய்",
    },

    "btn_cancel": {
        "en": "❌ Cancel",
        "ta": "❌ ரத்து செய்",
    },

    "confirm_tap_again": {
        "en": "Please tap *Confirm* or *Cancel*.",
        "ta": "*உறுதிசெய்* அல்லது *ரத்து செய்* என்பதைத் தேர்ந்தெடுக்கவும்.",
    },


    # ========================================================================
    # BOOKING DISCARDED
    # ========================================================================

    "booking_discarded": {
        "en": "No problem, booking cancelled. What would you like to do?",
        "ta": (
            "சரி, முன்பதிவு ரத்து செய்யப்பட்டது.\n\n"
            "என்ன செய்ய வேண்டும்?"
        ),
    },


    # ========================================================================
    # SLOT CONFLICT
    # ========================================================================

    "slot_conflict": {
        "en": (
            "⚠️ {message}{alt_text}\n\n"
            "Please pick another *time slot*."
        ),
        "ta": (
            "⚠️ {message}{alt_text}\n\n"
            "வேறு *நேரத்தை* தேர்வு செய்யவும்."
        ),
    },

    "alt_prefix": {
        "en": "\n\nAvailable alternative *time slots*: ",
        "ta": "\n\nகிடைக்கும் வேறு *நேரங்கள்*: ",
    },


    # ========================================================================
    # BOOKING SUCCESS
    # ========================================================================

    "booking_success": {
        "en": (
            "🎉 *Appointment booked!*\n\n"
            "Code: *{code}*\n"
            "Patient: *{patient}*\n"
            "Doctor: *{doctor}* ({department})\n"
            "Branch: *{branch}*\n"
            "Date & Time: *{date}* at *{time}*\n"
            "A confirmation has been sent to your number. See you then! 🙌\n\n"
            "Type *menu* anytime to book another appointment."
        ),
        "ta": (
            "🎉 *முன்பதிவு முடிந்தது!*\n\n"
            "குறியீடு: *{code}*\n"
            "நோயாளர்: *{patient}*\n"
            "மருத்துவர்: *{doctor}* ({department})\n"
            "கிளை: *{branch}*\n"
            "தேதி & நேரம்: *{date}* *{time}*\n"
            "உறுதிப்படுத்தல் உங்கள் எண்ணுக்கு அனுப்பப்பட்டுள்ளது. 🙌\n\n"
            "மற்றொரு முன்பதிவுக்கு *menu* என அனுப்பவும்."
        ),
    },


    # ========================================================================
    # TRACK RESULT
    # ========================================================================

    "track_result_body": {
        "en": (
            "📄 Appointment {code}\n"
            "Patient: *{patient}*\n"
            "Doctor: *{doctor}* ({department})\n"
            "Branch: *{branch}*\n"
            "Date & Time: *{date}* at *{time}*\n"
            "Status: *{status}*"
        ),
        "ta": (
            "📄 முன்பதிவு {code}\n"
            "நோயாளர்: *{patient}*\n"
            "மருத்துவர்: *{doctor}* ({department})\n"
            "கிளை: *{branch}*\n"
            "தேதி & நேரம்: *{date}* *{time}*\n"
            "நிலை: *{status}*"
        ),
    },

    "type_menu_more": {
        "en": "\n\nType *menu* for more options.",
        "ta": "\n\nமேலும் விருப்பங்களுக்கு *menu* என அனுப்பவும்.",
    },


    # ========================================================================
    # TRACK / CANCEL BUTTONS
    # ========================================================================

    "btn_cancel_appt": {
        "en": "❌ Cancel this appointment",
        "ta": "❌ இந்த முன்பதிவை ரத்து செய்ய",
    },

    "btn_book_another": {
        "en": "📅 Book another appointment",
        "ta": "📅 மற்றொரு முன்பதிவு",
    },


    # ========================================================================
    # CANCEL SUCCESS
    # ========================================================================

    "cancel_success": {
        "en": "✅ Appointment {code} has been cancelled. Confirmation sent to your number.",
        "ta": (
            "✅ முன்பதிவு {code} ரத்து செய்யப்பட்டது.\n"
            "உங்கள் எண்ணுக்கு தகவல் அனுப்பப்பட்டுள்ளது."
        ),
    },


    # ========================================================================
    # GENERIC
    # ========================================================================

    "choose_option_generic": {
        "en": "Please choose an option.",
        "ta": "ஒரு விருப்பத்தைத் தேர்வு செய்யவும்.",
    },

    "error_generic": {
        "en": (
            "Sorry — {detail}\n\n"
            "Type *menu* to start again."
        ),
        "ta": (
            "மன்னிக்கவும் — {detail}\n\n"
            "மீண்டும் தொடங்க *menu* என அனுப்பவும்."
        ),
    },
    "btn_reschedule_appt": {
        "en": "Reschedule",
        "ta": "மாற்றி அமை",
    },
    "reschedule_date_prompt": {
        "en": "📅 Select a new date for your appointment:",
        "ta": "📅 உங்கள் முன்பதிவிற்கான புதிய தேதியைத் தேர்ந்தெடுக்கவும்:",
    },
    "reschedule_slot_prompt": {
        "en": "⏰ Select a new time slot:",
        "ta": "⏰ புதிய நேரத்தைத் தேர்ந்தெடுக்கவும்:",
    },
    "reschedule_confirm_summary": {
        "en": (
            "🔄 **Confirm Reschedule**\n\n"
            "Patient: {patient}\n"
            "Doctor: {doctor}\n\n"
            "Old Slot: {old_date} at {old_time}\n"
            "New Slot: *{date} at {time}*"
        ),
        "ta": (
            "🔄 **மாற்றத்தை உறுதிப்படுத்தவும்**\n\n"
            "நோயாளி: {patient}\n"
            "மருத்துவர்: {doctor}\n\n"
            "பழைய நேரம்: {old_date}, {old_time}\n"
            "புதிய நேரம்: *{date}, {time}*"
        ),
    },
    "reschedule_success": {
        "en": "✅ Your appointment has been successfully rescheduled to {date} at {time}!",
        "ta": "✅ உங்கள் முன்பதிவு {date}, {time}-க்கு வெற்றிகரமாக மாற்றப்பட்டது!",
    },
    "reschedule_conflict": {
        "en": "⚠️ Sorry, that slot is no longer available. Please select another.",
        "ta": "⚠️ மன்னிக்கவும், அந்த நேரம் இப்போது காலியாக இல்லை. வேறு நேரத்தைத் தேர்ந்தெடுக்கவும்.",
    },
}




# ============================================================================
# TRANSLATION HELPER
# ============================================================================

def t(session: dict, key: str, **kwargs) -> str:
    """
    Return translated text for the selected language.

    English is the fallback language.
    """

    lang = session.get("lang", DEFAULT_LANG)

    entry = TRANSLATIONS.get(key)

    if entry is None:
        return key

    template = (
        entry.get(lang)
        or entry.get(DEFAULT_LANG)
        or key
    )

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # Do not crash the WhatsApp conversation because
            # a dynamic placeholder was missing.
            return template

    return template