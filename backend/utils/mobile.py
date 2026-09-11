import re

def normalize_mobile_number(mobile: str) -> str:
    """
    Centralized mobile number normalization logic.
    For Indian numbers:
    - Removes whitespace, +, -, (, )
    - Handles '00' prefix
    - Handles '91' prefix for 10-digit Indian numbers
    Returns the canonical 10-digit mobile number, or the stripped string if it doesn't match the Indian pattern.
    """
    if not mobile:
        return ""
    
    # 1-3. Remove +, -, spaces, ( )
    cleaned = re.sub(r'[\s\+\-\(\)]+', '', mobile)
    
    # 4. Handle 00 international prefix
    if cleaned.startswith('00'):
        cleaned = cleaned[2:]
        
    # 5-6. Handle Indian country code 91
    if len(cleaned) == 12 and cleaned.startswith('91'):
        cleaned = cleaned[2:]
        
    # Return canonical string
    return cleaned
