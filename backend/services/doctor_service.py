from datetime import date, datetime, timedelta
from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.database.models import Doctor, Department, Branch, DoctorSpecialAvailability, DoctorSchedule, DoctorLeave, Appointment

def time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def minutes_to_time(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def generate_slots_for_schedule_rows(rows) -> List[str]:
    slots = []
    for row in rows:
        start = time_to_minutes(row["start_time"])
        end = time_to_minutes(row["end_time"])
        step = row["slot_minutes"]
        t = start
        while t + step <= end:
            slots.append(minutes_to_time(t))
            t += step
    return sorted(set(slots))


def get_booked_slots(db: Session, doctor_id: int, appt_date: str) -> set:
    appts = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == appt_date,
        Appointment.status.in_(['BOOKED', 'CONFIRMED', 'RESCHEDULED'])
    ).all()
    return {a.time_slot for a in appts}


def doctor_exists_active(db: Session, doctor_id: int):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.doctor_status == 'ACTIVE').first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found or not active")
    return {
        "id": doc.id,
        "name": doc.name,
        "doctor_type": doc.doctor_type, 
        "consultation_duration": doc.consultation_duration,
        "branch_id": doc.branch_id,
        "department_id": doc.department_id,
        "fee": doc.fee,
        "mobile": doc.mobile,
        "email": doc.email,
        "qualification": doc.qualification
    }


def doctor_on_leave(db: Session, doctor_id: int, the_date: date) -> bool:
    leave = db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == the_date.isoformat()).first()
    return bool(leave)


def slots_for_date(db: Session, doctor_id: int, the_date: date) -> List[str]:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        return []
        
    special = db.query(DoctorSpecialAvailability).filter(
        DoctorSpecialAvailability.doctor_id == doctor_id,
        DoctorSpecialAvailability.available_date == the_date.isoformat()
    ).order_by(DoctorSpecialAvailability.start_time).all()
    
    if any(row.is_blocked for row in special):
        return []
    
    if special:
        duration = doctor.consultation_duration or 30
        return generate_slots_for_schedule_rows([
            {"start_time": row.start_time, "end_time": row.end_time, "slot_minutes": duration}
            for row in special
        ])
        
    if doctor.doctor_type == "SPECIAL":
        return []
        
    dow = the_date.weekday()
    schedule_rows = db.query(DoctorSchedule).filter(
        DoctorSchedule.doctor_id == doctor_id,
        DoctorSchedule.day_of_week == dow
    ).all()
    
    if not schedule_rows:
        return []
        
    if doctor_on_leave(db, doctor_id, the_date):
        return []
        
    return generate_slots_for_schedule_rows([
        {"start_time": row.start_time, "end_time": row.end_time, "slot_minutes": row.slot_minutes}
        for row in schedule_rows
    ])


def classify_slots(
    db: Session,
    doctor_id: int,
    the_date: date,
    exclude_slot: Optional[str] = None,
    min_lead_minutes: int = 10,
):
    all_slots = slots_for_date(db, doctor_id, the_date)
    booked = get_booked_slots(db, doctor_id, the_date.isoformat())
    if exclude_slot:
        booked -= {exclude_slot}

    cutoff_minutes = None
    if the_date == date.today():
        cutoff = datetime.now() + timedelta(minutes=min_lead_minutes)
        cutoff_minutes = cutoff.hour * 60 + cutoff.minute

    result = []
    for s in all_slots:
        if cutoff_minutes is not None and time_to_minutes(s) < cutoff_minutes:
            status = "PAST"
        elif s in booked:
            status = "BOOKED"
        else:
            status = "AVAILABLE"
        result.append((s, status))
    return result


def get_available_departments(db: Session, branch_id: Optional[int] = None):
    if branch_id is not None:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
            
        deps = db.query(Department).join(Doctor, Doctor.department_id == Department.id).filter(
            Doctor.branch_id == branch_id,
            Doctor.doctor_status == 'ACTIVE'
        ).distinct().order_by(Department.name).all()
    else:
        deps = db.query(Department).order_by(Department.name).all()
        
    return [{"id": d.id, "name": d.name, "base_fee": d.base_fee} for d in deps]


def list_doctors_for_branch_department(db: Session, branch_id: int, department_id: Optional[int] = None):
    query = db.query(Doctor).filter(Doctor.branch_id == branch_id, Doctor.doctor_status == 'ACTIVE')
    if department_id is not None:
        query = query.filter(Doctor.department_id == department_id)
        
    doctors = query.order_by(Doctor.name).all()
    
    return [
        {
            "id": d.id,
            "name": d.name,
            "branch_id": d.branch_id,
            "department_id": d.department_id,
            "qualification": d.qualification,
            "fee": d.fee,
            "doctor_status": d.doctor_status,
        }
        for d in doctors
    ]


def list_doctors_with_availability(db: Session, branch_id: int, department_id: Optional[int], the_date: date):
    doctors = list_doctors_for_branch_department(db, branch_id, department_id)
    result = []
    for doc in doctors:
        schedule_rows = db.query(DoctorSchedule).filter(
            DoctorSchedule.doctor_id == doc["id"],
            DoctorSchedule.day_of_week == the_date.weekday()
        ).all()
        
        on_leave = doctor_on_leave(db, doc["id"], the_date)
        has_schedule = bool(schedule_rows)
        available = doc["doctor_status"] == "ACTIVE" and has_schedule and not on_leave
        
        status = "AVAILABLE" if available else "UNAVAILABLE"
        if doc["doctor_status"] != "ACTIVE":
            status = "INACTIVE"
        elif on_leave:
            status = "ON_LEAVE"
        elif not has_schedule:
            status = "NO_SCHEDULE"

        result.append(
            {
                "id": doc["id"],
                "name": doc["name"],
                "branch_id": doc["branch_id"],
                "department_id": doc["department_id"],
                "qualification": doc["qualification"],
                "fee": doc["fee"],
                "doctor_status": doc["doctor_status"],
                "available": available,
                "status": status,
                "on_leave": on_leave,
                "has_schedule": has_schedule,
            }
        )
    return result


def get_doctor(db: Session, doctor_id: int):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        return None
    return {
        "id": doc.id,
        "name": doc.name,
        "branch_id": doc.branch_id,
        "department_id": doc.department_id,
        "qualification": doc.qualification,
        "fee": doc.fee,
        "doctor_status": doc.doctor_status,
        "doctor_code": doc.doctor_code,
        "mobile": doc.mobile,
        "email": doc.email,
        "specialization": doc.specialization,
        "doctor_type": doc.doctor_type,
        "consultation_duration": doc.consultation_duration
    }


def update_doctor_status(db: Session, doctor_id: int, doctor_status: str):
    if doctor_status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(status_code=400, detail="doctor_status must be ACTIVE or INACTIVE")
        
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")
        
    doc.doctor_status = doctor_status
    db.commit()
    db.refresh(doc)
    return get_doctor(db, doctor_id)


def create_doctor(db: Session, data: dict):
    branch = db.query(Branch).filter(Branch.id == data["branch_id"]).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    department = db.query(Department).filter(Department.id == data["department_id"]).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
        
    if data["doctor_status"] not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(status_code=400, detail="doctor_status must be ACTIVE or INACTIVE")
    if data["fee"] < 0:
        raise HTTPException(status_code=400, detail="fee must be non-negative")
    if data.get("doctor_type", "REGULAR") not in {"REGULAR", "SPECIAL"}:
        raise HTTPException(status_code=400, detail="doctor_type must be REGULAR or SPECIAL")

    doc = Doctor(
        doctor_code=data.get("doctor_code"),
        name=data["name"],
        mobile=data.get("mobile"),
        email=data.get("email"),
        branch_id=data["branch_id"],
        department_id=data["department_id"],
        qualification=data.get("qualification", ""),
        specialization=data.get("specialization") or data.get("qualification", ""),
        fee=data["fee"],
        doctor_status=data["doctor_status"],
        doctor_type=data.get("doctor_type", "REGULAR"),
        consultation_duration=data.get("consultation_duration", 30)
    )
    
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return get_doctor(db, doc.id)


def update_doctor(db: Session, doctor_id: int, data: dict):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if data.get("branch_id") is not None:
        branch = db.query(Branch).filter(Branch.id == data["branch_id"]).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
            
    if data.get("department_id") is not None:
        department = db.query(Department).filter(Department.id == data["department_id"]).first()
        if not department:
            raise HTTPException(status_code=404, detail="Department not found")
            
    if data.get("doctor_status") is not None and data["doctor_status"] not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(status_code=400, detail="doctor_status must be ACTIVE or INACTIVE")
        
    if data.get("fee") is not None and data["fee"] < 0:
        raise HTTPException(status_code=400, detail="fee must be non-negative")
        
    if data.get("doctor_type") is not None and data["doctor_type"] not in {"REGULAR", "SPECIAL"}:
        raise HTTPException(status_code=400, detail="doctor_type must be REGULAR or SPECIAL")

    for key in ["doctor_code", "name", "mobile", "email", "branch_id", "department_id", "qualification", "specialization", "fee", "doctor_status", "doctor_type", "consultation_duration"]:
        if key in data and data[key] is not None:
            setattr(doc, key, data[key])
            
    if data.get("consultation_duration") is not None:
        db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_id).update(
            {"slot_minutes": data["consultation_duration"]}
        )

    db.commit()
    db.refresh(doc)
    return get_doctor(db, doc.id)


def delete_doctor(db: Session, doctor_id: int):
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")
        
    appointment = db.query(Appointment).filter(Appointment.doctor_id == doctor_id).first()
    if appointment:
        raise HTTPException(status_code=400, detail="Cannot delete doctor with existing appointments")
        
    db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_id).delete()
    db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id).delete()
    db.delete(doc)
    db.commit()
    
    return {"id": doc.id}


def find_alternatives(db: Session, doctor_id: int, the_date: date, requested_slot: str, max_dates: int = 5):
    classified = classify_slots(db, doctor_id, the_date)
    free_today = [s for s, status in classified if status == "AVAILABLE"]

    req_min = time_to_minutes(requested_slot)
    next_time = min((s for s in free_today if time_to_minutes(s) > req_min), default=None)
    prev_time = max((s for s in free_today if time_to_minutes(s) < req_min), default=None)

    next_date_slots = []
    next_date = None
    if not free_today:
        for offset in range(1, max_dates + 1):
            candidate = the_date + timedelta(days=offset)
            candidate_classified = classify_slots(db, doctor_id, candidate)
            candidate_free = [s for s, status in candidate_classified if status == "AVAILABLE"]
            if candidate_free:
                next_date = candidate.isoformat()
                next_date_slots = candidate_free[:4]
                break

    return {
        "requested_date": the_date.isoformat(),
        "requested_time": requested_slot,
        "same_day_full": len(free_today) == 0,
        "next_available_time": next_time,
        "previous_available_time": prev_time,
        "next_available_date": next_date,
        "next_available_date_slots": next_date_slots,
    }
