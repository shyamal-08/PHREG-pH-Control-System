import time
import sys
import select
import argparse
from datetime import datetime

import serial

from .config import (
    MM44_PORTS_DEFAULT, MFC_PORT_DEFAULT, DT, LOG_DIR_DEFAULT,
    LOG_INTERVAL_S, LOG_RETENTION_DAYS, MM44_BAUD, MM44_TIMEOUT,
    MM44_STALE_SEC, AIR_MIN, AIR_MAX, CO2_MIN, PID_KP, PID_KI, PID_KD,
    MFC_FAILS_BEFORE_FAILSAFE, REACTORS_DEFAULT, REG_CTRL_MODE,
    REG_VALVE_CMD, REG_FLOW_ACTUAL
)
from .utils import clamp, rate_limit, safe_float
from .pid import PID
from .mm44 import parse_mm44_line, get_channel, validate_mapping
from .mfc import make_mfc, write_u16, write_f32, read_f32, mfc_try
from .logging_utils import ensure_dir, purge_old_logs, reactor_log_path, append_csv_row
from .dashboard_io import read_cmd_json, write_dashboard

S_INIT = "INIT"
S_RUN = "RUN"
S_DEGRADED = "DEGRADED"
S_FAILSAFE = "FAILSAFE"


class PHREGController:
    def __init__(self):
        self.args = self._parse_args()
        self.dt_target = max(0.2, float(self.args.dt))
        self.ph_deadband = max(0.0, float(self.args.deadband))
        self.co2_rate = max(0.1, float(self.args.co2_rate))
        self.air_rate = max(0.1, float(self.args.air_rate))
        self.mm44_ports = [p.strip() for p in self.args.mm44_ports.split(",") if p.strip()]
        if len(self.mm44_ports) != 2:
            raise SystemExit("[FATAL] Need exactly 2 MM44 ports in --mm44_ports.")

        self.reactors = [r for r in REACTORS_DEFAULT]
        self._apply_runtime_config()

        if self.args.mode == "co2_only":
            self.pids = {r.name: PID(PID_KP, PID_KI, PID_KD, 0.0, float(self.args.co2_max)) for r in self.reactors}
        else:
            self.pids = {r.name: PID(PID_KP, PID_KI, PID_KD, -100.0, float(self.args.co2_max)) for r in self.reactors}

        self.co2_cmd = {r.name: 0.0 for r in self.reactors}
        self.air_cmd = {r.name: None for r in self.reactors}
        self.last_co2_flow = {r.name: None for r in self.reactors}
        self.last_ph_time = {r.name: 0.0 for r in self.reactors}
        self.last_logged_minute = {r.name: None for r in self.reactors}

        self.log_enabled = bool(self.args.log_enable)
        self.log_dir = self.args.log_dir
        self.log_interval = max(5, int(self.args.log_interval))
        self.log_retention_days = max(7, int(self.args.log_retention_days))
        self.last_log_ts = 0.0

        self.state = S_INIT
        self.alarms = set()
        self.mm44_list = []
        self.mm44_data = {}
        self.last_mm44_raw = {}
        self.air_mfc = {}
        self.co2_mfc = {}
        self.mfc_fail_count = 0
        self.show_raw = bool(self.args.raw)
        self.last_cmd_ts = None
        self.last_t = time.time()

    def _parse_args(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("--mm44_ports", type=str, default=MM44_PORTS_DEFAULT)
        ap.add_argument("--mfc", type=str, default=MFC_PORT_DEFAULT)
        ap.add_argument("--no_mfc", action="store_true")
        ap.add_argument("--raw", action="store_true")
        ap.add_argument("--dt", type=float, default=DT)
        ap.add_argument("--log_dir", type=str, default=LOG_DIR_DEFAULT)
        ap.add_argument("--log_enable", action="store_true")
        ap.add_argument("--log_interval", type=int, default=LOG_INTERVAL_S)
        ap.add_argument("--log_retention_days", type=int, default=LOG_RETENTION_DAYS)
        ap.add_argument("--deadband", type=float, default=0.05)
        ap.add_argument("--mode", choices=["co2_only", "split"], default="split")
        ap.add_argument("--air_boost_max", type=float, default=30.0)
        ap.add_argument("--co2_max", type=float, default=100.0)
        ap.add_argument("--air_rate", type=float, default=10.0)
        ap.add_argument("--co2_rate", type=float, default=10.0)
        ap.add_argument("--active_reactors", type=str, default="R1,R2,R3")
        ap.add_argument("--sp1", type=float, default=7.40)
        ap.add_argument("--sp2", type=float, default=7.40)
        ap.add_argument("--sp3", type=float, default=7.40)
        ap.add_argument("--air1", type=float, default=20.0)
        ap.add_argument("--air2", type=float, default=20.0)
        ap.add_argument("--air3", type=float, default=20.0)
        ap.add_argument("--r1_air", type=int, default=1)
        ap.add_argument("--r1_co2", type=int, default=2)
        ap.add_argument("--r2_air", type=int, default=6)
        ap.add_argument("--r2_co2", type=int, default=5)
        ap.add_argument("--r3_air", type=int, default=7)
        ap.add_argument("--r3_co2", type=int, default=4)
        return ap.parse_args()

    def _apply_runtime_config(self):
        active_set = {x.strip().upper() for x in self.args.active_reactors.split(",") if x.strip()}
        sp_map = {"R1": self.args.sp1, "R2": self.args.sp2, "R3": self.args.sp3}
        air_map = {"R1": self.args.air1, "R2": self.args.air2, "R3": self.args.air3}
        addr_map = {
            "R1": (self.args.r1_air, self.args.r1_co2),
            "R2": (self.args.r2_air, self.args.r2_co2),
            "R3": (self.args.r3_air, self.args.r3_co2),
        }
        for r in self.reactors:
            r.enabled = (r.name.upper() in active_set)
            r.ph_sp = clamp(float(sp_map.get(r.name, r.ph_sp)), 0.0, 14.0)
            r.air_baseline = clamp(float(air_map.get(r.name, r.air_baseline)), AIR_MIN, AIR_MAX)
            a, c = addr_map.get(r.name, (r.air_addr, r.co2_addr))
            r.air_addr = int(a)
            r.co2_addr = int(c)

    def alarms_str(self):
        return ",".join(sorted(self.alarms)) if self.alarms else "none"

    def set_state(self, new_state, reason=""):
        if new_state != self.state:
            print(f"[STATE] {self.state} -> {new_state} {('(' + reason + ')') if reason else ''}")
            self.state = new_state

    def close_mm44_all(self):
        for s in self.mm44_list:
            try:
                s.close()
            except Exception:
                pass
        self.mm44_list = []

    def open_mm44_all(self):
        self.mm44_list = []
        ok = True
        for p in self.mm44_ports:
            try:
                s = serial.Serial(p, MM44_BAUD, timeout=MM44_TIMEOUT)
                time.sleep(0.25)
                self.mm44_list.append(s)
                print(f"[MM44] open: {p}")
            except Exception as e:
                print(f"[MM44] open failed on {p}: {e}")
                ok = False
        return ok and len(self.mm44_list) == 2

    def apply_safe_outputs_for_reactor(self, r):
        r.air_baseline = clamp(float(r.air_baseline), AIR_MIN, AIR_MAX)
        self.co2_cmd[r.name] = 0.0
        self.air_cmd[r.name] = r.air_baseline
        if self.args.no_mfc:
            return
        if r.name in self.co2_mfc:
            mfc_try(write_f32, self.co2_mfc[r.name], REG_VALVE_CMD, 0.0)
        if r.name in self.air_mfc:
            mfc_try(write_f32, self.air_mfc[r.name], REG_VALVE_CMD, r.air_baseline)

    def open_mfcs(self):
        self.air_mfc = {}
        self.co2_mfc = {}
        try:
            for r in self.reactors:
                self.air_mfc[r.name] = make_mfc(self.args.mfc, r.air_addr)
                self.co2_mfc[r.name] = make_mfc(self.args.mfc, r.co2_addr)
            for r in self.reactors:
                _, err = mfc_try(write_u16, self.air_mfc[r.name], REG_CTRL_MODE, 10)
                if err:
                    raise err
                _, err = mfc_try(write_u16, self.co2_mfc[r.name], REG_CTRL_MODE, 10)
                if err:
                    raise err
                self.apply_safe_outputs_for_reactor(r)
            print("[MFC] init OK (ALL reactors): safe outputs set, mode=10.")
            return True
        except Exception as e:
            print(f"[MFC] init failed: {e}")
            self.air_mfc = {}
            self.co2_mfc = {}
            return False

    def failsafe_outputs(self):
        for r in self.reactors:
            self.apply_safe_outputs_for_reactor(r)

    def handle_stdin(self):
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            cmd = sys.stdin.readline().strip()
            c = cmd.lower()
            if c in ("q", "quit", "exit"):
                raise KeyboardInterrupt

    def init_state(self):
        self.alarms.clear()
        ok_mm44 = self.open_mm44_all()
        ok_mfc = True if self.args.no_mfc else self.open_mfcs()
        if not ok_mm44:
            self.alarms.add("MM44_OPEN_FAIL")
        if (not ok_mfc) and (not self.args.no_mfc):
            self.alarms.add("MFC_INIT_FAIL")
        for r in self.reactors:
            self.pids[r.name].reset()
            self.co2_cmd[r.name] = 0.0
            self.air_cmd[r.name] = r.air_baseline
            self.last_co2_flow[r.name] = None
            self.last_ph_time[r.name] = 0.0
        self.mm44_data = {}
        self.last_mm44_raw = {}
        self.mfc_fail_count = 0
        if ok_mm44 and ok_mfc:
            self.set_state(S_RUN, "init_ok")
        else:
            self.set_state(S_FAILSAFE, "init_failed")
            self.failsafe_outputs()

    def read_mm44(self):
        if self.state != S_INIT and len(self.mm44_list) != len(self.mm44_ports):
            self.alarms.add("MM44_DISCONNECTED")
            self.close_mm44_all()
            self.open_mm44_all()
        for idx, ser in enumerate(self.mm44_list):
            for _ in range(6):
                try:
                    raw = ser.readline().decode(errors="ignore").strip()
                except Exception:
                    self.alarms.add("MM44_READ_FAIL")
                    try:
                        ser.close()
                    except Exception:
                        pass
                    raw = ""
                if not raw:
                    break
                self.last_mm44_raw[idx] = raw
                if self.show_raw:
                    print(f"RAW[{idx}]: {raw}")
                parsed = parse_mm44_line(raw)
                if parsed:
                    dev = self.mm44_data.get(idx, {})
                    dev.update(parsed)
                    self.mm44_data[idx] = dev

    def build_reactor_values(self):
        reactor_values = {}
        for r in self.reactors:
            ph_b = get_channel(self.mm44_data, r.ph_mm44, r.ph_ch)
            do_b = get_channel(self.mm44_data, r.do_mm44, r.do_ch)
            ph = ph_b.get("value") if ph_b and ph_b.get("type") == "pH" else None
            do = do_b.get("value") if do_b and do_b.get("type") == "DO" else None
            if ph is not None and (0.0 <= ph <= 14.0):
                self.last_ph_time[r.name] = time.time()
            reactor_values[r.name] = {
                "enabled": r.enabled,
                "pH": ph,
                "DO": do,
                "temp_c_ph": ph_b.get("temp_c") if ph_b else None,
                "temp_c_do": do_b.get("temp_c") if do_b else None,
                "ph_sp": r.ph_sp,
                "air_baseline": r.air_baseline,
                "air_cmd": self.air_cmd[r.name] if self.air_cmd.get(r.name) is not None else r.air_baseline,
                "co2_cmd": self.co2_cmd[r.name],
                "co2_flow": self.last_co2_flow[r.name],
                "mfc_addrs": {"air": r.air_addr, "co2": r.co2_addr},
            }
        return reactor_values

    def update_stale_alarms(self):
        for r in self.reactors:
            stale_key = f"{r.name}_PH_STALE"
            if self.last_ph_time[r.name] > 0 and (time.time() - self.last_ph_time[r.name]) > MM44_STALE_SEC:
                self.alarms.add(stale_key)
            else:
                self.alarms.discard(stale_key)

    def state_transitions(self):
        if self.state == S_RUN:
            if ("MFC_HARD_FAIL" in self.alarms) and (not self.args.no_mfc):
                self.set_state(S_FAILSAFE, "mfc_hard_fail")
                self.failsafe_outputs()
            if all((f"{r.name}_PH_STALE" in self.alarms) for r in self.reactors):
                self.set_state(S_FAILSAFE, "all_ph_stale")
                self.failsafe_outputs()
        elif self.state == S_FAILSAFE:
            if self.args.no_mfc:
                self.set_state(S_RUN, "no_mfc_mode")
            else:
                self.failsafe_outputs()

    def control_loop(self, reactor_values, dt):
        if self.state not in (S_RUN, S_DEGRADED):
            return
        for r in self.reactors:
            r.air_baseline = clamp(float(r.air_baseline), AIR_MIN, AIR_MAX)
        if not self.args.no_mfc and self.air_mfc and self.co2_mfc:
            for r in self.reactors:
                if not r.enabled:
                    self.apply_safe_outputs_for_reactor(r)
                    continue
                ph = reactor_values[r.name]["pH"]
                if f"{r.name}_PH_STALE" in self.alarms or ph is None or not (0.0 <= ph <= 14.0):
                    self.apply_safe_outputs_for_reactor(r)
                    continue
                if abs(ph - r.ph_sp) <= self.ph_deadband:
                    u = 0.0
                else:
                    u = self.pids[r.name].update(ph, r.ph_sp, dt)
                if self.args.mode == "co2_only":
                    target_co2 = clamp(u, CO2_MIN, float(self.args.co2_max))
                    target_air = r.air_baseline
                else:
                    if u >= 0.0:
                        target_co2 = clamp(u, CO2_MIN, float(self.args.co2_max))
                        target_air = r.air_baseline
                    else:
                        target_co2 = 0.0
                        boost = min(float(self.args.air_boost_max), (-u))
                        target_air = clamp(r.air_baseline + boost, AIR_MIN, AIR_MAX)
                self.co2_cmd[r.name] = rate_limit(target_co2, self.co2_cmd[r.name], self.co2_rate * max(dt, 0.01))
                prev_air = self.air_cmd[r.name] if self.air_cmd[r.name] is not None else r.air_baseline
                self.air_cmd[r.name] = rate_limit(target_air, prev_air, self.air_rate * max(dt, 0.01))
                _, err_co2 = mfc_try(write_f32, self.co2_mfc[r.name], REG_VALVE_CMD, self.co2_cmd[r.name])
                if err_co2:
                    self.mfc_fail_count += 1
                    self.alarms.add("MFC_CO2_WRITE_FAIL")
                else:
                    self.alarms.discard("MFC_CO2_WRITE_FAIL")
                _, err_air = mfc_try(write_f32, self.air_mfc[r.name], REG_VALVE_CMD, self.air_cmd[r.name])
                if err_air:
                    self.mfc_fail_count += 1
                    self.alarms.add("MFC_AIR_WRITE_FAIL")
                else:
                    self.alarms.discard("MFC_AIR_WRITE_FAIL")
                val, err2 = mfc_try(read_f32, self.co2_mfc[r.name], REG_FLOW_ACTUAL)
                if err2:
                    self.alarms.add("MFC_CO2_READ_FAIL")
                else:
                    self.last_co2_flow[r.name] = val
                    self.alarms.discard("MFC_CO2_READ_FAIL")
            if self.mfc_fail_count >= MFC_FAILS_BEFORE_FAILSAFE:
                self.alarms.add("MFC_HARD_FAIL")
        else:
            for r in self.reactors:
                self.co2_cmd[r.name] = 0.0
                self.air_cmd[r.name] = r.air_baseline

    def sync_telemetry(self, reactor_values):
        for r in self.reactors:
            reactor_values[r.name]["co2_cmd"] = self.co2_cmd[r.name]
            reactor_values[r.name]["air_cmd"] = self.air_cmd[r.name] if self.air_cmd.get(r.name) is not None else r.air_baseline
            reactor_values[r.name]["air_baseline"] = r.air_baseline
            reactor_values[r.name]["co2_flow"] = self.last_co2_flow[r.name]

    def log_csv(self, reactor_values):
        if not self.log_enabled:
            return
        now_dt = datetime.now()
        if (time.time() - self.last_log_ts) < self.log_interval:
            return
        self.last_log_ts = time.time()
        purge_old_logs(self.log_dir, now_dt, retention_days=self.log_retention_days)
        header = [
            "timestamp", "reactor", "state", "enabled", "pH", "DO", "temp_c_ph", "temp_c_do",
            "ph_sp", "air_baseline", "air_cmd", "co2_cmd", "co2_flow", "alarms"
        ]
        minute_tag = now_dt.strftime("%Y-%m-%d %H:%M")
        for r in self.reactors:
            if self.last_logged_minute.get(r.name) == minute_tag:
                continue
            self.last_logged_minute[r.name] = minute_tag
            rv = reactor_values.get(r.name, {})
            row = {
                "timestamp": now_dt.isoformat(timespec="seconds"),
                "reactor": r.name,
                "state": self.state,
                "enabled": bool(rv.get("enabled", r.enabled)),
                "pH": rv.get("pH"),
                "DO": rv.get("DO"),
                "temp_c_ph": rv.get("temp_c_ph"),
                "temp_c_do": rv.get("temp_c_do"),
                "ph_sp": rv.get("ph_sp"),
                "air_baseline": rv.get("air_baseline"),
                "air_cmd": rv.get("air_cmd"),
                "co2_cmd": rv.get("co2_cmd"),
                "co2_flow": rv.get("co2_flow"),
                "alarms": self.alarms_str(),
            }
            path = reactor_log_path(self.log_dir, r.name, now_dt)
            append_csv_row(path, header, row)

    def print_status(self, reactor_values):
        print(
            f"{datetime.now().strftime('%H:%M:%S')}  STATE={self.state}  ALARMS={self.alarms_str()}\\n"
            f"R1 pH={reactor_values['R1']['pH']} (SP={reactor_values['R1']['ph_sp']:.2f}) DO={reactor_values['R1']['DO']}  AIR={reactor_values['R1']['air_cmd']:.1f}%  CO2={reactor_values['R1']['co2_cmd']:.1f}%\\n"
            f"R2 pH={reactor_values['R2']['pH']} (SP={reactor_values['R2']['ph_sp']:.2f}) DO={reactor_values['R2']['DO']}  AIR={reactor_values['R2']['air_cmd']:.1f}%  CO2={reactor_values['R2']['co2_cmd']:.1f}%\\n"
            f"R3 pH={reactor_values['R3']['pH']} (SP={reactor_values['R3']['ph_sp']:.2f}) DO={reactor_values['R3']['DO']}  AIR={reactor_values['R3']['air_cmd']:.1f}%  CO2={reactor_values['R3']['co2_cmd']:.1f}%\\n"
            "------------------------------------------------------------"
        )

    def run(self):
        print("\\nPHREG modular controller started.")
        print(f"MM44 ports: {self.mm44_ports}")
        print(f"MFC port: {self.args.mfc}  no_mfc={self.args.no_mfc}")
        for r in self.reactors:
            print(f"  {r.name}: enabled={r.enabled} AIR={r.air_addr} CO2={r.co2_addr} SP={r.ph_sp:.2f} baseline={r.air_baseline:.1f}%")
        if self.log_enabled and ensure_dir(self.log_dir):
            print(f"[LOG] CSV minute logging enabled -> {self.log_dir}")
        try:
            while True:
                now = time.time()
                dt = now - self.last_t
                self.last_t = now
                if dt <= 0:
                    dt = self.dt_target
                self.handle_stdin()
                if self.state == S_INIT:
                    self.init_state()
                self.read_mm44()
                validate_mapping(self.mm44_data, self.reactors, self.alarms)
                reactor_values = self.build_reactor_values()
                self.update_stale_alarms()
                self.state_transitions()
                self.control_loop(reactor_values, dt)
                self.sync_telemetry(reactor_values)
                write_dashboard(
                    self.state, self.alarms, self.mm44_ports, self.mm44_data, self.last_mm44_raw,
                    self.args.mfc, self.args.no_mfc, self.args.mode, self.ph_deadband,
                    reactor_values, self.reactors
                )
                self.log_csv(reactor_values)
                self.print_status(reactor_values)
                time.sleep(self.dt_target)
        except KeyboardInterrupt:
            pass
        finally:
            print("\\nStopping: CO2 -> 0 (safe).")
            if (not self.args.no_mfc) and self.co2_mfc:
                for r in self.reactors:
                    if r.name in self.co2_mfc:
                        try:
                            mfc_try(write_f32, self.co2_mfc[r.name], REG_VALVE_CMD, 0.0)
                        except Exception:
                            pass
            self.close_mm44_all()
            print("Done.")
