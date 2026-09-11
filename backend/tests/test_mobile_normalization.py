import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.utils.mobile import normalize_mobile_number

def test_normalization():
    cases = {
        "7373857342": "7373857342",
        "917373857342": "7373857342",
        "+917373857342": "7373857342",
        "+91 7373857342": "7373857342",
        "00917373857342": "7373857342",
        "91 7373857342": "7373857342"
    }
    
    all_passed = True
    for inp, expected in cases.items():
        res = normalize_mobile_number(inp)
        if res != expected:
            print(f"FAILED: {inp} -> {res} (Expected: {expected})")
            all_passed = False
        else:
            print(f"PASSED: {inp} -> {res}")
            
    if all_passed:
        print("All normalization tests passed.")
    else:
        print("Some normalization tests failed.")

if __name__ == "__main__":
    test_normalization()
