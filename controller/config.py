from dataclasses import dataclass
import os
import serial

MM44_PORTS_DEFAULT = (
    "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Cable_FTXWTKP3-if00-port0,"
    "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Cable_FTXWTKP3-if01-port0"
)
MFC_PORT_DEFAULT = "/dev/ttyUSB2"

MM44_BAUD = 9600
MM44_TIMEOUT = 0.15

MFC_BAUD = 9600
MFC_PARITY = serial.PARITY_NONE
MFC_STOPBITS = 2
MFC_BYTESIZE = 8
MFC_TIMEOUT = 0.6

WORD_ORDER = "hi_lo"

REG_FLOW_ACTUAL = 0x0000
REG_VALVE_CMD   = 0x000A
REG_CTRL_MODE   = 0x000E

DT = 1.0

MM44_LATEST_JSON = "/tmp/mm44_latest.json"
MM44_CMD_JSON = "/tmp/mm44_cmd.json"

LOG_DIR_DEFAULT = os.environ.get("PHREG_LOG_DIR", "/mnt/phreg_logs")
LOG_RETENTION_DAYS = 35
LOG_INTERVAL_S = 60

MM44_STALE_SEC = 3.0
AIR_BASELINE_MIN = 5.0

CO2_MIN, CO2_MAX = 0.0, 100.0
AIR_MIN, AIR_MAX = AIR_BASELINE_MIN, 100.0

CO2_RATE_LIMIT_PER_S = 10.0
AIR_RATE_LIMIT_PER_S = 10.0

PID_KP = 25.0
PID_KI = 1.0
PID_KD = 0.0

MFC_MAX_RETRIES = 3
MFC_FAILS_BEFORE_FAILSAFE = 3

@dataclass
class ReactorCfg:
    name: str
    enabled: bool
    ph_mm44: int
    ph_ch: str
    do_mm44: int
    do_ch: str
    air_addr: int
    co2_addr: int
    ph_sp: float
    air_baseline: float

REACTORS_DEFAULT = [
    ReactorCfg("R1", True,  ph_mm44=0, ph_ch="C1", do_mm44=1, do_ch="C2", air_addr=1, co2_addr=2, ph_sp=7.40, air_baseline=20.0),
    ReactorCfg("R2", True,  ph_mm44=0, ph_ch="C2", do_mm44=1, do_ch="C3", air_addr=6, co2_addr=5, ph_sp=7.40, air_baseline=20.0),
    ReactorCfg("R3", True,  ph_mm44=1, ph_ch="C1", do_mm44=0, do_ch="C3", air_addr=7, co2_addr=4, ph_sp=7.40, air_baseline=20.0),
]
