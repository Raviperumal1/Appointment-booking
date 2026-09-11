class Permissions:
    USERS_READ = "users.read"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    USERS_DEACTIVATE = "users.deactivate"
    
    ROLES_READ = "roles.read"
    ROLES_MANAGE = "roles.manage"
    
    BRANCHES_READ = "branches.read"
    BRANCHES_CREATE = "branches.create"
    BRANCHES_UPDATE = "branches.update"
    BRANCHES_DEACTIVATE = "branches.deactivate"
    
    DEPARTMENTS_READ = "departments.read"
    DEPARTMENTS_CREATE = "departments.create"
    DEPARTMENTS_UPDATE = "departments.update"
    DEPARTMENTS_DEACTIVATE = "departments.deactivate"
    
    DOCTORS_READ = "doctors.read"
    DOCTORS_CREATE = "doctors.create"
    DOCTORS_UPDATE = "doctors.update"
    DOCTORS_DEACTIVATE = "doctors.deactivate"
    DOCTORS_ASSIGN = "doctors.assign"
    
    PATIENTS_READ = "patients.read"
    PATIENTS_CREATE = "patients.create"
    PATIENTS_UPDATE = "patients.update"
    
    BOOKINGS_READ = "bookings.read"
    BOOKINGS_CREATE = "bookings.create"
    BOOKINGS_UPDATE = "bookings.update"
    BOOKINGS_CANCEL = "bookings.cancel"

class Roles:
    ADMIN = "ADMIN"
    BRANCH_ADMIN = "BRANCH_ADMIN"
    DEPARTMENT_ADMIN = "DEPARTMENT_ADMIN"
    DOCTOR = "DOCTOR"
