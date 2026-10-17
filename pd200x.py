"""Protocol library for the Maono PD200X (352f:0104) over hidraw.

Framing is the DGM20 one on HID report 0x4B (same id both directions):
  4B C4 len 00 00 type payload(u16 LE words) csum(u16 LE), zero-padded to 64 bytes.
See CLAUDE.md for the register map. This module only reads for now.
"""
import fcntl
import glob
import os
import select
import struct
import time
from contextlib import contextmanager

VID, PID = 0x352F, 0x0104
REPORT = 0x4B
T_ACK, T_WRITE, T_READ, T_RANGE = 2, 3, 4, 6
METER = 0x2034  # streamed by the mic (~18 Hz) while live; never a reply. Same dB x10 + 2000
                # encoding as everything else, as far as we can tell (1000 = -100 dB floor).

REG_FIRST, REG_LAST = 0x2000, 0x2089  # readable settings block on fw 1.2.9

EQ_BANDS = [("band 1", 0x204D), ("band 2", 0x2052), ("band 3", 0x2057), ("band 4", 0x205C),
            ("band 5", 0x2061), ("high-pass", 0x2066), ("low-pass", 0x206B)]
EQ_TYPES = {0: "peak", 1: "low-pass", 2: "high-pass", 3: "low-shelf?", 4: "high-shelf?"}
COLOURS = {0: "white", 1: "red", 2: "orange", 3: "yellow", 4: "green", 5: "cyan", 6: "blue",
           7: "pink", 8: "rgb-wave", 9: "rgb-static"}  # confirmed by eye; 10 looks like 9

# Registers we may write: confirmed meaning only (see CLAUDE.md). Anything else is refused,
# which also keeps out 0x1008 (DFU) and 0x100A (factory reset). Type 5 is never sent.
WRITABLE = {0x2022, 0x2023, 0x2026, 0x2027, 0x202C, 0x202D, 0x2031, 0x2036, 0x2037, 0x2038}
WRITABLE |= {base + i for _, base in EQ_BANDS for i in range(5)}


class DeviceError(Exception):
    pass


def find_node():
    for dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(f"{dev}/device/uevent").read()
            desc = open(f"{dev}/device/report_descriptor", "rb").read()
        except OSError:
            continue
        hid_id = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_ID=")), "")
        parts = hid_id.split(":")
        if (len(parts) == 3 and int(parts[1], 16) == VID and int(parts[2], 16) == PID
                and b"\x06\x01\xff" in desc):
            return "/dev/" + os.path.basename(dev)
    raise DeviceError("no PD200X found (lsusb | grep 352f)")


def build(ptype, words):
    payload = b"".join(struct.pack("<H", w & 0xFFFF) for w in words)
    body = bytes([0xC4, 7 + len(payload), 0, 0, ptype]) + payload
    return (bytes([REPORT]) + body + struct.pack("<H", (-sum(body)) & 0xFFFF)).ljust(64, b"\0")


def parse(raw):
    if len(raw) < 8 or raw[0] != REPORT or raw[1] != 0xC4 or raw[2] < 7 or raw[2] + 1 > len(raw):
        return None
    ln = raw[2]
    if (sum(raw[1:ln - 1]) + struct.unpack_from("<H", raw, ln - 1)[0]) & 0xFFFF:
        return None
    payload = raw[6:ln - 1]
    return raw[5], [struct.unpack_from("<H", payload, i)[0] for i in range(0, len(payload) - 1, 2)]


class PD200X:
    def __init__(self, path=None):
        self.path = path or find_node()
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except PermissionError:
            raise DeviceError(f"no permission for {self.path} (sudo chown $USER {self.path})")

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _locked(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def _xfer(self, ptype, words, match, timeout=0.5):
        with self._locked():
            os.write(self.fd, build(ptype, words))
            end = time.monotonic() + timeout
            while (left := end - time.monotonic()) > 0:
                if not select.select([self.fd], [], [], left)[0]:
                    break
                p = parse(os.read(self.fd, 64))
                if p and match(*p):
                    return p[1]
        return None

    def read(self, addr):
        r = self._xfer(T_READ, [addr], lambda t, w: t == T_READ and w[:1] == [addr])
        return r[1] if r else None

    def read_range(self, addr, count):
        r = self._xfer(T_RANGE, [addr, count], lambda t, w: t == T_RANGE and w[:2] == [addr, count])
        return r[2:] if r else None

    def read_block(self, first, last, chunk=16):
        """Read first..last inclusive; returns {addr: value} for whatever answered."""
        regs = {}
        for a in range(first, last + 1, chunk):
            n = min(chunk, last + 1 - a)
            vals = self.read_range(a, n)
            if vals is None:  # the whole range fails if it runs past the end; fall back to singles
                vals = [self.read(a + i) for i in range(n)]
            regs.update({a + i: v for i, v in enumerate(vals) if v is not None})
        return regs

    def write(self, pairs):
        """Write [(addr, value), ...] in one packet, check the ack and read every value back."""
        for addr, value in pairs:
            if addr not in WRITABLE:
                raise DeviceError(f"refusing to write unconfirmed register {addr:#06x}")
            if not 0 <= value <= 0xFFFF:
                raise DeviceError(f"value {value} out of range for {addr:#06x}")
        words = [w for pair in pairs for w in pair]
        ack = self._xfer(T_WRITE, words, lambda t, w: t == T_ACK)
        if ack is None:
            raise DeviceError("no ack from mic")
        if ack[0] != 0:
            raise DeviceError(f"mic rejected write (status {ack[0]})")
        for addr, value in pairs:
            got = self.read(addr)
            if got != value:
                raise DeviceError(f"{addr:#06x} reads {got} after writing {value}")

    def identity(self):
        def ascii(ws):
            b = b"".join(struct.pack("<H", w) for w in ws or [])
            return b.split(b"\0")[0].decode("ascii", "replace")
        fw = self.read_range(0x000B, 3)
        return {"model": ascii(self.read_range(0x0003, 8)),
                "firmware": ".".join(map(str, fw)) if fw else None,
                "serial": ascii(self.read_range(0x001E, 10))}


def db(v):
    """dB x10 + 2000 encoding."""
    return (v - 2000) / 10


def from_db(d):
    return int(round(d * 10)) + 2000


# --- settings: shared by pd200xctl and the web UI. Parsers raise ValueError on bad input.

def parse_bool(v):
    if v not in ("on", "off"):
        raise ValueError("expected on or off")
    return v == "on"


def parse_int(lo, hi):
    def f(v):
        n = int(v)
        if not lo <= n <= hi:
            raise ValueError(f"expected {lo}-{hi}")
        return n
    return f


def parse_db(v):
    d = float(v)
    if not -60 <= d <= 0:
        raise ValueError("expected -60..0 dB")
    return from_db(d)


def parse_colour(v):
    names = {name: idx for idx, name in COLOURS.items()}
    if v in names:
        return names[v]
    if not v.isdigit():
        raise ValueError(f"expected {', '.join(names)} or an index 0-9")
    return parse_int(0, 9)(v)


# key -> (register, value parser)
SETTINGS = {
    "mute": (0x2022, lambda v: int(parse_bool(v))),
    "monitor": (0x2031, lambda v: 2000 if parse_bool(v) else 3000),
    "mic-volume": (0x2023, parse_int(0, 100)),  # knob in blue-LED mode
    "light": (0x2036, lambda v: int(parse_bool(v))),
    "brightness": (0x2037, parse_int(0, 100)),
    "colour": (0x2038, parse_colour),
    "compressor": (0x2026, lambda v: int(parse_bool(v))),
    "compressor-threshold": (0x2027, parse_db),
    "limiter": (0x202C, lambda v: int(parse_bool(v))),
    "limiter-threshold": (0x202D, parse_db),
}

BAND_NAMES = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "hpf": 5, "lpf": 6}


def set_setting(dev, key, value):
    if key not in SETTINGS:
        raise ValueError(f"unknown setting {key!r}")
    addr, conv = SETTINGS[key]
    try:
        raw = conv(str(value))
    except (ValueError, KeyError) as e:
        raise ValueError(f"bad value {value!r} for {key}: {e}")
    dev.write([(addr, raw)])


def set_band(dev, band, on=None, freq=None, gain=None, q=None):
    """Change some fields of one EQ band; returns (name, new words) or (name, None) if unchanged."""
    if band not in BAND_NAMES:
        raise ValueError(f"unknown band {band!r} (1-5, hpf, lpf)")
    name, base = EQ_BANDS[BAND_NAMES[band]]
    cur = dev.read_range(base, 5)
    if cur is None:
        raise DeviceError("EQ not readable (needs firmware 1.2.x)")
    new = list(cur)
    if on is not None:
        new[0] = int(bool(on))
    if freq is not None:
        if not 20 <= int(freq) <= 22000:
            raise ValueError("freq expects 20-22000 Hz")
        new[2] = int(freq)
    if gain is not None:
        if not -12 <= float(gain) <= 12:
            raise ValueError("gain expects -12..12 dB")
        new[3] = from_db(float(gain))
    if q is not None:
        if not 0.1 <= float(q) <= 10:
            raise ValueError("q expects 0.1-10")
        new[4] = int(round(float(q) * 100))
    if new == cur:
        return name, None
    dev.write([(base + i, v) for i, v in enumerate(new)])  # one 5-pair packet, like the app
    return name, new


def decode(regs):
    g = regs.get
    s = {
        "mute": None if g(0x2022) is None else bool(g(0x2022)),
        "monitoring": {2000: True, 3000: False}.get(g(0x2031)),
        "mic_volume": g(0x2023),
        "reg_2030": g(0x2030),
        "light": {"on": None if g(0x2036) is None else bool(g(0x2036)),
                  "brightness": g(0x2037), "colour": g(0x2038)},
        "compressor": {"on": None if g(0x2026) is None else bool(g(0x2026)),
                       "threshold_db": None if g(0x2027) is None else db(g(0x2027))},
        "limiter": {"on": None if g(0x202C) is None else bool(g(0x202C)),
                    "threshold_db": None if g(0x202D) is None else db(g(0x202D))},
        "eq": None,
    }
    if all(g(base + i) is not None for _, base in EQ_BANDS for i in range(5)):
        s["eq"] = [{"name": name, "on": bool(g(base)), "type": EQ_TYPES.get(g(base + 1), g(base + 1)),
                    "freq_hz": g(base + 2), "gain_db": db(g(base + 3)), "q": g(base + 4) / 100}
                   for name, base in EQ_BANDS]
    return s
