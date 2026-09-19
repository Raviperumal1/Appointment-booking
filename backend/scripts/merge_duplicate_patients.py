import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.database.db import engine
from sqlalchemy.orm import Session
from backend.database.models import Patient, Appointment, Consultation, Prescription, MedicalReport, ChatUser
from backend.utils.mobile import normalize_mobile_number
import logging
from backend.core.logging_config import setup_logging, mask_phone

setup_logging()
logger = logging.getLogger(__name__)
def merge_duplicates():
    with Session(engine) as db:
        patients = db.query(Patient).all()
        
        # Group by normalized mobile
        groups = {}
        for p in patients:
            if not p.mobile:
                continue
            norm = normalize_mobile_number(p.mobile)
            if norm:
                groups.setdefault(norm, []).append(p)
                
        merged_count = 0
        
        for norm, group in groups.items():
            if len(group) == 1:
                # Update to canonical format if needed
                primary = group[0]
                if primary.mobile != norm:
                    primary.mobile = norm
                    db.commit()
                continue
                
            logger.info(f"Found duplicates for {mask_phone(norm)}: {[p.id for p in group]}")
            
            # Sort to find primary (oldest first)
            group.sort(key=lambda x: x.id)
            primary = group[0]
            duplicates = group[1:]
            
            for dup in duplicates:
                # Merge non-empty fields
                if not primary.full_name and dup.full_name:
                    primary.full_name = dup.full_name
                if (primary.gender == "UNSPECIFIED" or not primary.gender) and dup.gender and dup.gender != "UNSPECIFIED":
                    primary.gender = dup.gender
                if not primary.email and dup.email:
                    primary.email = dup.email
                if not primary.dob and dup.dob:
                    primary.dob = dup.dob
                if not primary.address and dup.address:
                    primary.address = dup.address
                if not primary.blood_group and dup.blood_group:
                    primary.blood_group = dup.blood_group
                
                # Update foreign keys
                db.query(Appointment).filter(Appointment.patient_id == dup.id).update({"patient_id": primary.id})
                db.query(Consultation).filter(Consultation.patient_id == dup.id).update({"patient_id": primary.id})
                db.query(Prescription).filter(Prescription.patient_id == dup.id).update({"patient_id": primary.id})
                db.query(MedicalReport).filter(MedicalReport.patient_id == dup.id).update({"patient_id": primary.id})
                db.query(ChatUser).filter(ChatUser.patient_id == dup.id).update({"patient_id": primary.id})
                
                # Delete duplicate
                db.delete(dup)
                merged_count += 1
            
            # Set primary's mobile to normalized
            primary.mobile = norm
            db.commit()
            
        logger.info(f"Merged {merged_count} duplicate patients.")

if __name__ == "__main__":
    merge_duplicates()
