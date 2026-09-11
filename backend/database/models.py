from typing import Optional, List
from pydantic import BaseModel, Field

from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, JSON, Index
import enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from backend.database.db import Base

# auth section

class PatientRegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str
    dob: str
    gender: str
    mobile: str
    email: Optional[str] = None
    address: str
    emergency_contact: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None


class PatientLoginRequest(BaseModel):
    username_or_mobile_or_email: str
    password: str


class GoogleAuthRequest(BaseModel):
    credential: str


class PatientProfileUpdate(BaseModel):
    full_name: str
    dob: str
    gender: str
    mobile: str
    email: Optional[str] = None
    address: str
    emergency_contact: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None


# config section

class AIProviderConfig(BaseModel):
    active_provider: str = "gemini"  # which provider the chatbot actually calls: gemini | claude | openai
    gemini_api_key: str = ""
    gemini_model: str = ""
    claude_api_key: str = ""
    claude_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""


class WhatsAppConfig(BaseModel):
    access_token: str = ""
    phone_number_id: str = ""
    business_account_id: str = ""
    verify_token: str = ""
    api_version: str = ""


class NotificationConfig(BaseModel):
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    smtp_host: str = ""
    smtp_port: str = ""
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


# branch & doctor section

class BranchStatusRequest(BaseModel):
    branch_status: str


class BranchCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    branch_status: str


class BranchUpdateRequest(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    branch_status: Optional[str] = None


class DoctorStatusRequest(BaseModel):
    doctor_status: str


class DoctorCreateRequest(BaseModel):
    doctor_code: Optional[str] = Field(None, min_length=1)
    name: str = Field(..., min_length=1)
    branch_id: int
    department_id: int
    qualification: str = Field(..., min_length=1)
    fee: int = Field(..., ge=0)
    doctor_status: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    specialization: Optional[str] = None
    doctor_type: str = "REGULAR"
    consultation_duration: int = Field(30, ge=5, le=240)


class DoctorUpdateRequest(BaseModel):
    doctor_code: Optional[str] = None
    name: Optional[str] = None
    branch_id: Optional[int] = None
    department_id: Optional[int] = None
    qualification: Optional[str] = None
    fee: Optional[int] = Field(None, ge=0)
    doctor_status: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    specialization: Optional[str] = None
    doctor_type: Optional[str] = None
    consultation_duration: Optional[int] = Field(None, ge=5, le=240)


class DoctorScheduleRequest(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str
    end_time: str


class SpecialAvailabilityRequest(BaseModel):
    available_date: str
    start_time: str = "00:00"
    end_time: str = "00:00"
    is_blocked: bool = False


# booking section

class BookRequest(BaseModel):
    patient_name: str = Field(..., min_length=1)
    age: Optional[int] = None
    gender: Optional[str] = None
    mobile: str = Field(..., min_length=7)
    email: Optional[str] = None
    address: str = ""
    reason: Optional[str] = ""
    branch_id: int
    department_id: int
    doctor_id: int
    appointment_date: str  # YYYY-MM-DD
    time_slot: str  # HH:MM


class CancelRequest(BaseModel):
    mobile: str = Field(..., min_length=7, description="Must match the mobile number on the booking")


class RescheduleRequest(BaseModel):
    mobile: Optional[str] = None
    appointment_date: str  # YYYY-MM-DD
    time_slot: str  # HH:MM


class PatientImportCommitRequest(BaseModel):
    token: str = Field(..., min_length=1)
    import_valid_records: bool = True


class SymptomAnalysisRequest(BaseModel):
    symptoms: str = Field(..., min_length=3)
    branch_id: Optional[int] = None
    language: str = "en"


# admin section

class CompleteAppointmentRequest(BaseModel):
    symptoms: str
    diagnosis: str
    notes: Optional[str] = None


class CreatePrescriptionRequest(BaseModel):
    appointment_code: str
    medicines: List[dict]  # [{"name": "...", "dosage": "...", "frequency": "..."}]
    instructions: Optional[str] = None
    validity_days: int = 30


class CreateMedicalReportRequest(BaseModel):
    appointment_code: str
    report_name: str
    report_type: str  # LAB_TEST, IMAGING, SCAN, etc.
    findings: Optional[str] = None
    status: str = "COMPLETED"  # PENDING, COMPLETED, REVIEWED


# user management section

class StaffUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=10, max_length=256)
    role: str = Field(..., min_length=3)
    branch_id: Optional[int] = None
    department_id: Optional[int] = None


class StaffUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    branch_id: Optional[int] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


class UserListResponse(BaseModel):
    id: int
    name: Optional[str] = None
    email: Optional[str] = None
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    is_active: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UserCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=5, max_length=100)
    password: str = Field(..., min_length=6)
    role_id: int
    branch_id: Optional[int] = None
    department_id: Optional[int] = None


class UserUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=5, max_length=100)
    role_id: int
    branch_id: Optional[int] = None
    department_id: Optional[int] = None
    is_active: int = 1


class UserPasswordUpdateRequest(BaseModel):
    new_password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)


# roles & permissions section

class PermissionResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    module: Optional[str] = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_system_role: bool = False
    permissions: List[PermissionResponse] = []


class RolePermissionsUpdate(BaseModel):
    permissions: List[str]


class RoleCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []


# conversation section

class ConversationMessageRequest(BaseModel):
    text: str
    chat_user_id: int
    source: str = "WEB"


class ConversationStateResponse(BaseModel):
    previous: Optional[str] = None
    current: str


class ConversationBookingContext(BaseModel):
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    doctor_id: Optional[int] = None
    doctor_name: Optional[str] = None
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    appointment_code: Optional[str] = None


class ConversationMessageData(BaseModel):
    id: int
    text: str


class ConversationTurnResponse(BaseModel):
    conversation_id: int
    turn_number: int
    user_message: ConversationMessageData
    bot_message: ConversationMessageData
    state: ConversationStateResponse
    booking: ConversationBookingContext
    language: str
    next_expected_input: Optional[str] = None


class ConversationHistoryItem(BaseModel):
    turn: int
    user: str
    bot: str


# models

# branch & doctor section

class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    phone = Column(String(50), nullable=False)
    branch_status = Column(String(20), nullable=False, default='OPEN')


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    base_fee = Column(Integer, nullable=False)


class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    qualification = Column(String(255), nullable=False)
    fee = Column(Integer, nullable=False)
    doctor_status = Column(String(20), nullable=False, default='ACTIVE')
    doctor_code = Column(String(50), unique=True)
    mobile = Column(String(50))
    email = Column(String(100))
    specialization = Column(String(255))
    doctor_type = Column(String(50), nullable=False, default='REGULAR')
    consultation_duration = Column(Integer, nullable=False, default=30)

    branch = relationship("Branch")
    department = relationship("Department")


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedule"
    id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(String(20), nullable=False)
    end_time = Column(String(20), nullable=False)
    slot_minutes = Column(Integer, nullable=False, default=30)


class DoctorSpecialAvailability(Base):
    __tablename__ = "doctor_special_availability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    available_date = Column(String(20), nullable=False)
    start_time = Column(String(20), nullable=False)
    end_time = Column(String(20), nullable=False)
    is_blocked = Column(Integer, nullable=False, default=0)


class DoctorLeave(Base):
    __tablename__ = "doctor_leave"
    id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    leave_date = Column(String(20), nullable=False)


# patient section

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(50), nullable=False, unique=True)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    dob = Column(String(50), nullable=False)
    gender = Column(String(20), nullable=False)
    mobile = Column(String(50), nullable=False, unique=True)
    email = Column(String(100))
    address = Column(Text, nullable=False)
    emergency_contact = Column(String(100))
    blood_group = Column(String(20))
    allergies = Column(Text)
    medical_history = Column(Text)
    age = Column(Integer)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    symptoms = Column(Text)
    status = Column(String(20), nullable=False, default='ACTIVE')
    created_at = Column(DateTime, default=func.now())


# user & roles section

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    role = relationship("Role")
    branch = relationship("Branch")
    department = relationship("Department")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255))
    module = Column(String(50))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)


# appointment & records section

class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index('idx_unique_booked_slot', 'doctor_id', 'appointment_date', 'time_slot', unique=True, sqlite_where=text("status != 'CANCELLED'")),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_code = Column(String(50), nullable=False, unique=True)
    patient_name = Column(String(255), nullable=False)
    age = Column(Integer)
    gender = Column(String(20))
    mobile = Column(String(50), nullable=False)
    email = Column(String(100))
    address = Column(Text, nullable=False)
    reason = Column(Text)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    symptoms = Column(Text)
    appointment_date = Column(String(20), nullable=False)
    time_slot = Column(String(20), nullable=False)
    fee = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='BOOKED')
    created_at = Column(DateTime, default=func.now())


class Consultation(Base):
    __tablename__ = "consultations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    department_id = Column(Integer, ForeignKey("departments.id"))
    consultation_date = Column(String(20), nullable=False)
    consultation_time = Column(String(20), nullable=False)
    symptoms = Column(Text)
    diagnosis = Column(Text)
    notes = Column(Text)
    treatment_plan = Column(Text)
    follow_up_date = Column(String(20))
    created_by = Column(Integer)
    consultation_status = Column(String(20), nullable=False, default='COMPLETED')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Prescription(Base):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    prescription_date = Column(String(20), nullable=False)
    medicines = Column(Text, nullable=False)
    instructions = Column(Text)
    validity_days = Column(Integer, default=30)
    status = Column(String(20), nullable=False, default='ACTIVE')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"), nullable=False)
    medicine_name = Column(String(255), nullable=False)
    dosage = Column(String(100))
    frequency = Column(String(100))
    duration = Column(String(100))
    route = Column(String(100))
    quantity = Column(String(50))
    instructions = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=func.now())


class MedicalReport(Base):
    __tablename__ = "medical_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    report_name = Column(String(255), nullable=False)
    report_type = Column(String(50), nullable=False)
    report_date = Column(String(20), nullable=False)
    findings = Column(Text)
    status = Column(String(20), nullable=False, default='PENDING')
    file_path = Column(String(500))
    original_filename = Column(String(255))
    mime_type = Column(String(100))
    file_size = Column(Integer)
    uploaded_by = Column(Integer)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# notification & audit section

class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    recipient_type = Column(String(50), nullable=False)
    channel = Column(String(50), nullable=False)
    recipient = Column(String(100))
    status = Column(String(20), nullable=False)
    error_message = Column(Text)
    created_at = Column(DateTime, default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    actor_label = Column(String(100))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(String(50))
    result = Column(String(20), nullable=False)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=func.now())


# conversation section

class ChatUser(Base):
    __tablename__ = "chat_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    mobile = Column(String(50), unique=True)
    name = Column(String(255))
    patient_id = Column(Integer, ForeignKey("patients.id"))
    created_at = Column(String(50), nullable=False)


class ChatUserChannel(Base):
    __tablename__ = "chat_user_channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_user_id = Column(Integer, ForeignKey("chat_users.id"), nullable=False)
    source = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=False)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_user_id = Column(Integer, ForeignKey("chat_users.id"), nullable=False)
    source = Column(String(50), nullable=False)
    sender = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    timestamp = Column(String(50), nullable=False)


class ConversationState(str, enum.Enum):
    START = "START"
    GREETING = "GREETING"
    SELECT_BRANCH = "SELECT_BRANCH"
    SELECT_DEPARTMENT = "SELECT_DEPARTMENT"
    ANALYZE_SYMPTOMS = "ANALYZE_SYMPTOMS"
    ASK_NAME = "ASK_NAME"
    ASK_AGE = "ASK_AGE"
    ASK_GENDER = "ASK_GENDER"
    ASK_MOBILE = "ASK_MOBILE"
    ASK_ADDRESS = "ASK_ADDRESS"
    SELECT_DOCTOR = "SELECT_DOCTOR"
    SELECT_DATE = "SELECT_DATE"
    SELECT_TIME = "SELECT_TIME"
    CONFIRM_APPOINTMENT = "CONFIRM_APPOINTMENT"
    BOOKING_COMPLETED = "BOOKING_COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ConversationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ConversationMetadata(Base):
    __tablename__ = "conversation_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_user_id = Column(Integer, ForeignKey("chat_users.id"), nullable=False, index=True)

    patient_name = Column(String(255), nullable=True, index=True)
    patient_mobile = Column(String(50), nullable=True, index=True)

    context = Column(JSON, default=dict)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())