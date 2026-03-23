import json

from .config import MM44_CMD_JSON, MM44_LATEST_JSON
from .utils import now_iso

def read_cmd_json(path: str = MM44_CMD_JSON):
    try:
        with open(path, "r") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return None

def write_dashboard(state, alarms, mm44_ports, mm44_data, last_mm44_raw, mfc_port,
                    no_mfc, control_mode, deadband, reactor_values, reactors,
                    path: str = MM44_LATEST_JSON):
    try:
        payload = {
            "ts": now_iso(),
            "state": state,
            "alarms": sorted(list(alarms)),
            "mm44_ports": mm44_ports,
            "mm44_data": mm44_data,
            "last_raw": last_mm44_raw,
            "mfc_port": mfc_port,
            "no_mfc": bool(no_mfc),
            "control_mode": control_mode,
            "deadband": deadband,
            "reactors": reactor_values,
            "mapping": [
                {
                    "name": r.name,
                    "enabled": r.enabled,
                    "ph": {"mm44": r.ph_mm44, "ch": r.ph_ch},
                    "do": {"mm44": r.do_mm44, "ch": r.do_ch},
                    "air_addr": r.air_addr,
                    "co2_addr": r.co2_addr,
                } for r in reactors
            ]
        }
        with open(path, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass
