#!/usr/bin/env python3
"""
Read-only probe for Maono mics (VID 0x352f) using the DGM20 framing from
https://git.reiners.io/justin/dgm20-linux/PROTOCOL.md

Only sends type 4 (read one) and type 6 (range read). Never writes.

  python3 pd200x_probe.py                 # find device, dump descriptor, read identity
  python3 pd200x_probe.py scan            # also read every register 0x2000-0x20FF
  python3 pd200x_probe.py listen          # print unsolicited packets (turn knobs / press buttons)
"""
import glob, os, select, struct, sys, time

VID = 0x352F
REQ, REP = 0x4B, 0x4B  # PD200X: same report id both ways (DGM20 used 0x51/0x11)


def find_nodes():
    out = []
    for dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(f"{dev}/device/uevent").read()
        except OSError:
            continue
        hid_id = next((l.split("=", 1)[1] for l in uevent.splitlines() if l.startswith("HID_ID=")), "")
        parts = hid_id.split(":")
        if len(parts) == 3 and int(parts[1], 16) == VID:
            desc = open(f"{dev}/device/report_descriptor", "rb").read()
            out.append(("/dev/" + os.path.basename(dev), int(parts[2], 16), desc))
    return out


def build(ptype, words):
    payload = b"".join(struct.pack("<H", w & 0xFFFF) for w in words)
    body = bytes([0xC4, 5 + len(payload) + 2, 0, 0, ptype]) + payload
    csum = (-sum(body)) & 0xFFFF
    pkt = bytes([REQ]) + body + struct.pack("<H", csum)
    return pkt.ljust(64, b"\0")


def parse(raw):
    if len(raw) < 8 or raw[0] != REP or raw[1] != 0xC4:
        return None
    ln = raw[2]
    ptype = raw[5]
    payload = raw[6:1 + ln - 2]
    words = [struct.unpack_from("<H", payload, i)[0] for i in range(0, len(payload) - 1, 2)]
    csum_ok = ((sum(raw[1:1 + ln - 2]) + struct.unpack_from("<H", raw, 1 + ln - 2)[0]) & 0xFFFF) == 0
    return ptype, words, csum_ok


def xfer(fd, ptype, words, want, timeout=0.4):
    os.write(fd, build(ptype, words))
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], end - time.time())
        if not r:
            break
        raw = os.read(fd, 128)
        p = parse(raw)
        if p and p[0] == want:
            return p
        if p:
            print(f"   (other packet: type {p[0]} {[hex(w) for w in p[1]]})")
    return None


def words_to_ascii(ws):
    b = b"".join(struct.pack("<H", w) for w in ws)
    return "".join(chr(c) for c in b if 32 <= c < 127)


def main():
    nodes = find_nodes()
    if not nodes:
        sys.exit("no 352f:* hidraw node found (lsusb | grep -i 352f)")
    for path, pid, desc in nodes:
        vendor_page = b"\x06\x01\xff" in desc
        print(f"{path}  352f:{pid:04x}  descriptor {len(desc)}B  vendor-page-0xFF01={vendor_page}")
        print("   descriptor:", desc.hex(" "))
    target = next((n for n in nodes if b"\x06\x01\xff" in n[2]), None)
    if not target:
        sys.exit("no node with vendor usage page 0xFF01 - protocol differs, send me the descriptors above")
    path = target[0]
    fd = os.open(path, os.O_RDWR)
    print(f"\nusing {path}")

    if "listen" in sys.argv:
        print("listening, Ctrl-C to stop", flush=True)
        while True:
            raw = os.read(fd, 128)
            print(f"{time.strftime('%H:%M:%S')}  rid {raw[0]:02x}  " + raw[:raw[2] + 3 if len(raw) > 2 and raw[1] == 0xC4 else 16].hex(" "), parse(raw), flush=True)

    r = xfer(fd, 6, [0x0003, 8], 6)
    print("model    :", repr(words_to_ascii(r[1][2:])) if r else "no reply", "" if not r or r[2] else "(bad csum)")
    r = xfer(fd, 6, [0x000B, 3], 6)
    print("firmware :", ".".join(map(str, r[1][2:])) if r else "no reply")
    r = xfer(fd, 4, [0x1008], 4)
    print("dfu-mode :", r[1] if r else "no reply")

    if "scan" in sys.argv:
        print("\nscanning 0x2000-0x20FF (type 4 reads):")
        for a in range(0x2000, 0x2100):
            r = xfer(fd, 4, [a], 4, timeout=0.25)
            if r and len(r[1]) >= 2:
                print(f"  0x{a:04X} = {r[1][1]:5d}  (0x{r[1][1]:04x})")
    os.close(fd)


if __name__ == "__main__":
    main()
