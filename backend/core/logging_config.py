import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional

# Context variable for tracking request ID across async tasks
request_id_ctx_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

class RequestIDFilter(logging.Filter):
    """
    Injects request_id from contextvar into the log record.
    """
    def filter(self, record):
        req_id = request_id_ctx_var.get()
        record.request_id = f"request_id={req_id}" if req_id else ""
        
        # Ensure module/category alignment
        module_name = record.name.split('.')[-1].upper()
        if len(module_name) > 10:
            module_name = module_name[:10]
        record.category = f"{module_name:<10}"
        
        return True

class CustomFormatter(logging.Formatter):
    """
    Custom formatter that formats logs as requested:
    YYYY-MM-DD HH:MM:SS | LEVEL    | CATEGORY   | [request_id=xxx |] Message
    """
    def format(self, record):
        # Format time
        record.asctime = self.formatTime(record, self.datefmt)
        
        # Level alignment
        level = f"{record.levelname:<8}"
        
        # Format the basic structure
        parts = [
            record.asctime,
            level,
            record.category
        ]
        
        # Add request_id if present
        if getattr(record, 'request_id', ""):
            parts.append(record.request_id)
            
        parts.append(record.getMessage())
        
        log_line = " | ".join(parts)
        
        if record.exc_info:
            # Add exception info if any
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                log_line = f"{log_line}\n{record.exc_text}"
                
        return log_line

def setup_logging():
    env = os.getenv("ENVIRONMENT", "production")
    
    # Configure base logging level from env, default INFO
    log_level_str = os.getenv("LOG_LEVEL", "INFO" if env == "production" else "DEBUG").upper()
    try:
        log_level = getattr(logging, log_level_str)
    except AttributeError:
        log_level = logging.INFO

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers to prevent duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # Create and add formatter
    formatter = CustomFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(formatter)
    
    # Add filter
    req_filter = RequestIDFilter()
    console_handler.addFilter(req_filter)
    
    root_logger.addHandler(console_handler)
    
    # Set levels for third party libs to avoid noise
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if os.getenv("LOG_SQL", "false").lower() == "true" else logging.WARNING
    )

def mask_phone(phone: str) -> str:
    if not phone:
        return "***"
    return f"***{phone[-4:]}"

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***@***"
    parts = email.split("@")
    name = parts[0]
    domain = parts[1]
    if len(name) > 1:
        masked_name = f"{name[0]}***"
    else:
        masked_name = "***"
    return f"{masked_name}@{domain}"
