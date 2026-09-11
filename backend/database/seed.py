from datetime import date, timedelta
from sqlalchemy.orm import Session
from backend.database.db import SessionLocal
from backend.database.models import (
    Role, Permission, RolePermission, Branch, Department,
    Doctor, DoctorSchedule, DoctorLeave, User
)
from backend.services.authorization import ROLE_PERMISSIONS
from backend.auth.patient_auth import hash_password

def seed_database():
    db: Session = SessionLocal()
    
    try:
        # Seed Roles
        roles = [
            "ADMIN", "BRANCH_ADMIN", "DEPARTMENT_ADMIN", "DOCTOR", "PATIENT"
        ]
        for role_name in roles:
            if not db.query(Role).filter(Role.name == role_name).first():
                db.add(Role(name=role_name))
        db.commit()

        # Seed Permissions
        permissions = [
            ("USER_READ", "Read Users", "Admin"),
            ("USER_MANAGE", "Manage Users", "Admin"),
            ("ROLE_MANAGE", "Manage Roles", "Admin"),
            ("BRANCH_READ", "Read Branches", "Branches"),
            ("BRANCH_MANAGE", "Manage Branches", "Branches"),
            ("DEPARTMENT_READ", "Read Departments", "Departments"),
            ("DEPARTMENT_MANAGE", "Manage Departments", "Departments"),
            ("DOCTOR_READ", "Read Doctors", "Doctors"),
            ("DOCTOR_MANAGE", "Manage Doctors", "Doctors"),
            ("PATIENT_READ", "Read Patients", "Patients"),
            ("PATIENT_UPDATE", "Update Patients", "Patients"),
            ("APPOINTMENT_READ", "Read Appointments", "Appointments"),
            ("APPOINTMENT_MANAGE", "Manage Appointments", "Appointments"),
            ("CONVERSATION_READ", "Read Conversations", "Conversations"),
            ("CONSULTATION_READ", "Read Consultations", "Consultations"),
            ("CONSULTATION_CREATE", "Create Consultations", "Consultations"),
            ("CONSULTATION_UPDATE", "Update Consultations", "Consultations"),
            ("PRESCRIPTION_READ", "Read Prescriptions", "Prescriptions"),
            ("PRESCRIPTION_CREATE", "Create Prescriptions", "Prescriptions"),
            ("MEDICAL_REPORT_READ", "Read Medical Reports", "Medical Reports"),
            ("MEDICAL_REPORT_UPLOAD", "Upload Medical Reports", "Medical Reports")
        ]
        
        for p_name, p_desc, p_mod in permissions:
            perm = db.query(Permission).filter(Permission.name == p_name).first()
            if not perm:
                db.add(Permission(name=p_name, description=p_desc, module=p_mod))
            else:
                perm.description = p_desc
                perm.module = p_mod
        db.commit()

        # Seed Role Permissions
        for role_name, perms in ROLE_PERMISSIONS.items():
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                continue
            
            if "*" in perms:
                # Give this role all permissions
                all_perms = db.query(Permission).all()
                for perm in all_perms:
                    if not db.query(RolePermission).filter_by(role_id=role.id, permission_id=perm.id).first():
                        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            else:
                for p_name in perms:
                    perm = db.query(Permission).filter(Permission.name == p_name).first()
                    if perm:
                        if not db.query(RolePermission).filter_by(role_id=role.id, permission_id=perm.id).first():
                            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.commit()

        # Seed Default Admin User
        if db.query(User).filter(User.email == "admin@varuvi.in").count() == 0:
            admin_role = db.query(Role).filter(Role.name == "ADMIN").first()
            if admin_role:
                admin_user = User(
                    name="Admin",
                    email="admin@varuvi.in",
                    password_hash=hash_password("admin123"),
                    role_id=admin_role.id,
                    is_active=1
                )
                db.add(admin_user)
                db.commit()
                
        # Seed test users for other roles
        test_users = {
            "branchadmin@varuvi.in": ("BRANCH_ADMIN", "Branch Admin"),
            "deptadmin@varuvi.in": ("DEPARTMENT_ADMIN", "Department Admin"),
            "doctoruser@varuvi.in": ("DOCTOR", "Doctor User")
        }
        for t_email, (t_role, t_name) in test_users.items():
            if db.query(User).filter(User.email == t_email).count() == 0:
                role_obj = db.query(Role).filter(Role.name == t_role).first()
                if role_obj:
                    new_u = User(
                        name=t_name,
                        email=t_email,
                        password_hash=hash_password("password123"),
                        role_id=role_obj.id,
                        is_active=1
                    )
                    db.add(new_u)
                    db.commit()

        # --- SEED HOSPITAL DATA (Branches, Departments, Doctors) if not exists ---
        if db.query(Branch).count() == 0:
            branches = [
                ("City Central Hospital", "12 Anna Salai, Chennai", "044-2000-1001", "OPEN"),
                ("Riverside Multispeciality", "45 Marine Drive, Chennai", "044-2000-1002", "OPEN"),
                ("Green Valley Hospital", "88 Anna Nagar West, Chennai", "044-2000-1003", "OPEN"),
                ("Sunrise Medical Center", "23 OMR Road, Chennai", "044-2000-1004", "OPEN"),
                ("Lakeview Speciality Hospital", "5 Adyar Lake Road, Chennai", "044-2000-1005", "OPEN"),
            ]
            for b_name, b_addr, b_phone, b_status in branches:
                db.add(Branch(name=b_name, address=b_addr, phone=b_phone, branch_status=b_status))
            db.commit()

        if db.query(Department).count() == 0:
            for d_name in ["Cardiology", "Neurology", "Orthopedics", "Dermatology", "General Medicine"]:
                db.add(Department(name=d_name))
            db.commit()

        if db.query(Doctor).count() == 0:
            first_names = ["Arjun", "Priya", "Karthik", "Divya", "Rahul", "Sneha", "Vikram", "Anjali", "Suresh", "Meena", "Ravi", "Lakshmi", "Ganesh", "Kavya"]
            last_names = ["Iyer", "Nair", "Menon", "Reddy", "Rao", "Sharma", "Pillai", "Krishnan", "Subramanian", "Varma"]
            quals = {
                "Cardiology": "MD, DM Cardiology",
                "Neurology": "MD, DM Neurology",
                "Orthopedics": "MS Orthopedics",
                "Dermatology": "MD Dermatology",
                "General Medicine": "MD General Medicine",
            }

            name_index = 0
            doctor_id = 1
            today = date.today()

            all_branches = db.query(Branch).order_by(Branch.id).all()
            all_depts = db.query(Department).order_by(Department.id).all()

            for branch in all_branches:
                for dept in all_depts:
                    for _ in range(2):
                        first = first_names[name_index % len(first_names)]
                        last = last_names[name_index % len(last_names)]
                        name_index += 1

                        status = "ACTIVE" if doctor_id % 7 != 0 else "INACTIVE"

                        doc = Doctor(
                            name=f"Dr. {first} {last}",
                            branch_id=branch.id,
                            department_id=dept.id,
                            qualification=quals[dept.name],
                            doctor_status=status
                        )
                        db.add(doc)
                        db.flush() # flush to get doc.id

                        # Add schedule
                        schedules = [
                            (doc.id, 0, "09:00", "13:00", 30),
                            (doc.id, 1, "09:00", "13:00", 30),
                            (doc.id, 2, "09:00", "13:00", 30),
                            (doc.id, 3, "09:00", "13:00", 30),
                            (doc.id, 4, "09:00", "13:00", 30),
                            (doc.id, 5, "14:00", "17:00", 30)
                        ]
                        for s_doc_id, s_day, s_start, s_end, s_slot in schedules:
                            db.add(DoctorSchedule(
                                doctor_id=s_doc_id, day_of_week=s_day,
                                start_time=s_start, end_time=s_end, slot_minutes=s_slot
                            ))

                        # Add leave
                        if doctor_id % 5 == 0:
                            leave_date = (today + timedelta(days=1)).isoformat()
                            db.add(DoctorLeave(doctor_id=doc.id, leave_date=leave_date))
                        if doctor_id % 11 == 0:
                            leave_date = (today + timedelta(days=2)).isoformat()
                            db.add(DoctorLeave(doctor_id=doc.id, leave_date=leave_date))

                        doctor_id += 1
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
