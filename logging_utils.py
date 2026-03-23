import csv
from pathlib import Path
from datetime import datetime, timedelta

from .config import LOG_RETENTION_DAYS

def ensure_dir(path: str):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False

def month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")

def reactor_log_path(log_dir: str, reactor_name: str, dt: datetime) -> str:
    return str(Path(log_dir) / f"{reactor_name}_{month_key(dt)}.csv")

def purge_old_logs(log_dir: str, now_dt: datetime, retention_days: int = LOG_RETENTION_DAYS):
    try:
        base = Path(log_dir)
        if not base.exists():
            return
        cutoff = now_dt - timedelta(days=int(retention_days))
        for p in base.glob("R*_????-??.csv"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass

def append_csv_row(path: str, header: list, row: dict):
    try:
        p = Path(path)
        is_new = (not p.exists()) or p.stat().st_size == 0
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            if is_new:
                w.writeheader()
            w.writerow(row)
    except Exception:
        pass
