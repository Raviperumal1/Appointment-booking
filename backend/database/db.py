import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# Load variables from a .env file (if present) into the environment
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to your .env file or environment "
        "variables, e.g.:\n"
        "  DATABASE_URL=mysql+pymysql://user:password@localhost:3306/hospital_db"
    )

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,  # Recommended for MySQL to handle disconnected sessions
)

# Enforce FK constraints on SQLite (off by default) if they still use it
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


class _CustomBase:
    __table_args__ = {'extend_existing': True}


Base = declarative_base(cls=_CustomBase)


def init_db():
    """Create tables if they don't exist. Call once on startup, same as before."""
    # Import models here (not at module top) to avoid circular imports
    # between database.py and models.py.
    Base.metadata.create_all(bind=engine)

    from backend.database.seed import seed_database
    seed_database()


def get_db():
    """
    FastAPI dependency. Use with Depends(get_db) in route signatures:

        def my_route(db: Session = Depends(get_db)):
            ...

    FastAPI closes the generator (and thus the session) after the
    response is sent.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_ctx():
    """
    Context-manager version, for the few places (background jobs,
    scripts, or code outside a route function) where you can't use
    FastAPI's Depends() and need `with get_db_ctx() as db:` instead.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()