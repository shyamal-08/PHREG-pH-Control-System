import time
import struct
import minimalmodbus

from .config import (
    MFC_BAUD, MFC_PARITY, MFC_STOPBITS, MFC_BYTESIZE, MFC_TIMEOUT,
    WORD_ORDER, MFC_MAX_RETRIES
)

def make_mfc(port, addr):
    inst = minimalmodbus.Instrument(port, addr, mode=minimalmodbus.MODE_RTU)
    inst.serial.baudrate = MFC_BAUD
    inst.serial.parity = MFC_PARITY
    inst.serial.stopbits = MFC_STOPBITS
    inst.serial.bytesize = MFC_BYTESIZE
    inst.serial.timeout = MFC_TIMEOUT
    inst.clear_buffers_before_each_transaction = True
    inst.close_port_after_each_call = True
    return inst

def write_u16(inst, reg, value):
    inst.write_register(reg, int(value), 0, functioncode=6, signed=False)

def read_f32(inst, reg):
    w0, w1 = inst.read_registers(reg, 2, functioncode=3)
    if WORD_ORDER == "hi_lo":
        b = struct.pack(">HH", w0, w1)
    else:
        b = struct.pack(">HH", w1, w0)
    return struct.unpack(">f", b)[0]

def write_f32(inst, reg, value):
    b = struct.pack(">f", float(value))
    hi, lo = struct.unpack(">HH", b)
    if WORD_ORDER == "hi_lo":
        inst.write_registers(reg, [hi, lo])
    else:
        inst.write_registers(reg, [lo, hi])

def mfc_try(fn, *args, retries=MFC_MAX_RETRIES, delay=0.05):
    last = None
    for _ in range(retries):
        try:
            return fn(*args), None
        except Exception as e:
            last = e
            time.sleep(delay)
    return None, last
