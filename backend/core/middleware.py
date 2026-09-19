import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.core.logging_config import request_id_ctx_var

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if request ID is provided in headers, otherwise generate a short one
        req_id = request.headers.get("X-Request-ID")
        if not req_id:
            req_id = uuid.uuid4().hex[:8]
            
        # Set the request ID in contextvar
        token = request_id_ctx_var.set(req_id)
        
        # Log request
        method = request.method
        path = request.url.path
        
        # We don't want to log every healthcheck ping
        if path == "/health":
            logger.debug(f"→ REQUEST  {method} {path}")
        else:
            logger.info(f"→ REQUEST  {method} {path}")
            
        start_time = time.perf_counter()
        
        try:
            response = await call_next(request)
            
            # Log response
            process_time_ms = int((time.perf_counter() - start_time) * 1000)
            status_code = response.status_code
            
            if path == "/health":
                logger.debug(f"← RESPONSE {status_code} {method} {path} | {process_time_ms}ms")
            elif status_code >= 500:
                logger.error(f"← RESPONSE {status_code} {method} {path} | {process_time_ms}ms")
            elif status_code >= 400:
                logger.warning(f"← RESPONSE {status_code} {method} {path} | {process_time_ms}ms")
            else:
                logger.info(f"← RESPONSE {status_code} {method} {path} | {process_time_ms}ms")
                
            return response
        finally:
            # Clean up contextvar
            request_id_ctx_var.reset(token)
