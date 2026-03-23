def parse_mm44_line(line: str):
    parts = [p.strip() for p in line.split(";")]
    out = {}

    def is_chan(tok):
        return tok and tok.startswith("C") and len(tok) == 2 and tok[1].isdigit()

    i = 0
    while i < len(parts):
        tok = parts[i]
        if is_chan(tok) and i + 2 < len(parts):
            ch = tok
            kind = (parts[i + 1] or "").strip().upper()
            try:
                val = float(str(parts[i + 2]).strip())
            except Exception:
                val = None
            unit = None
            temp_c = None
            if i + 5 < len(parts):
                unit_candidate = (parts[i + 3] or "").strip()
                try:
                    temp_candidate = float(str(parts[i + 4]).strip())
                except Exception:
                    temp_candidate = None
                if unit_candidate != "":
                    unit = unit_candidate
                temp_c = temp_candidate
            if kind in ("PH", "DO", "OD"):
                out[ch] = {
                    "type": "pH" if kind == "PH" else "DO",
                    "value": val,
                    "unit": unit,
                    "temp_c": temp_c,
                }
        i += 1
    return out


def get_channel(mm44_data, mm44_idx: int, ch: str):
    dev = mm44_data.get(mm44_idx, {})
    return dev.get(ch.upper())


def validate_mapping(mm44_data, reactors, alarms):
    for r in reactors:
        ph_block = get_channel(mm44_data, r.ph_mm44, r.ph_ch)
        do_block = get_channel(mm44_data, r.do_mm44, r.do_ch)

        ph_missing_key = f"MAP_CH_MISSING_{r.name}_PH"
        ph_mismatch_key = f"MAP_TYPE_MISMATCH_{r.name}_PH"
        if ph_block is None:
            if r.ph_mm44 in mm44_data:
                alarms.add(ph_missing_key)
            else:
                alarms.discard(ph_missing_key)
            alarms.discard(ph_mismatch_key)
        else:
            alarms.discard(ph_missing_key)
            if ph_block.get("type") != "pH":
                alarms.add(ph_mismatch_key)
            else:
                alarms.discard(ph_mismatch_key)

        do_missing_key = f"MAP_CH_MISSING_{r.name}_DO"
        do_mismatch_key = f"MAP_TYPE_MISMATCH_{r.name}_DO"
        if do_block is None:
            if r.do_mm44 in mm44_data:
                alarms.add(do_missing_key)
            else:
                alarms.discard(do_missing_key)
            alarms.discard(do_mismatch_key)
        else:
            alarms.discard(do_missing_key)
            if do_block.get("type") != "DO":
                alarms.add(do_mismatch_key)
            else:
                alarms.discard(do_mismatch_key)
