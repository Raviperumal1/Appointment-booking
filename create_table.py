import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from backend.database.db import engine, Base

Base.metadata.create_all(bind=engine)
print("Table created successfully")
