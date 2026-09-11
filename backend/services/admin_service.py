from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import date
from backend.database.models import Appointment, Branch, Department, Doctor

def get_admin_stats(db: Session):
    total = db.query(func.count(Appointment.id)).scalar()
    active = db.query(func.count(Appointment.id)).filter(Appointment.status == 'BOOKED').scalar()
    cancelled = db.query(func.count(Appointment.id)).filter(Appointment.status == 'CANCELLED').scalar()
    today_count = db.query(func.count(Appointment.id)).filter(
        Appointment.status == 'BOOKED',
        Appointment.appointment_date == date.today().isoformat()
    ).scalar()

    by_branch_query = (
        db.query(Branch.name.label('branch'), func.count(Appointment.id).label('count'))
        .join(Appointment, Branch.id == Appointment.branch_id)
        .filter(Appointment.status == 'BOOKED')
        .group_by(Branch.id)
        .order_by(desc('count'))
        .all()
    )
    
    by_department_query = (
        db.query(Department.name.label('department'), func.count(Appointment.id).label('count'))
        .join(Appointment, Department.id == Appointment.department_id)
        .filter(Appointment.status == 'BOOKED')
        .group_by(Department.id)
        .order_by(desc('count'))
        .all()
    )
    
    top_doctors_query = (
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
        "by_branch": [{"branch": r.branch, "count": r.count} for r in by_branch_query],
        "by_department": [{"department": r.department, "count": r.count} for r in by_department_query],
        "top_doctors": [{"doctor": r.doctor, "branch": r.branch, "count": r.count} for r in top_doctors_query],
    }

def admin_appointment_query(db: Session, query, limit: int, offset: int):
    total = query.count()
    rows = query.order_by(desc(Appointment.appointment_date), desc(Appointment.time_slot), desc(Appointment.id)).offset(offset).limit(limit).all()
    
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
