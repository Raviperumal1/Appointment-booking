import sys
import os

sys.path.append(os.getcwd())

from backend.database.db import engine, Base
from sqlalchemy import text

with engine.begin() as conn:
    # Disable foreign key checks so we can drop tables out of order
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    
    # Drop modified tables
    conn.execute(text("DROP TABLE IF EXISTS user_scopes"))
    conn.execute(text("DROP TABLE IF EXISTS user_roles"))
    conn.execute(text("DROP TABLE IF EXISTS role_permissions"))
    conn.execute(text("DROP TABLE IF EXISTS permissions"))
    conn.execute(text("DROP TABLE IF EXISTS users"))
    conn.execute(text("DROP TABLE IF EXISTS roles"))
    
    # Re-enable foreign key checks
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

print("Dropped old tables.")

# Create the new tables
Base.metadata.create_all(bind=engine)
print("Created new tables.")

from backend.database.seed import seed_database
seed_database()
print("Seeded database.")
