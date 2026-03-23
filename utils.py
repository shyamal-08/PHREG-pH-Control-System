from datetime import datetime

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def rate_limit(new, old, max_delta):
    d = new - old
    if d > max_delta:
        return old + max_delta
    if d < -max_delta:
        return old - max_delta
    return new

def safe_float(x):
    try:
        return float(str(x).strip())
    except Exception:
        return None

def now_iso():
    return datetime.now().isoformat(timespec="seconds")
