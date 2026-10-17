# pd200x-linux

Goal: Linux control tool for the **Maono PD200X** USB mic (settings Maono Link exposes on
Windows/macOS: EQ, RGB, monitoring, etc.). Userspace over hidraw, not a kernel driver.
Audio already works via standard USB audio class.

## Prior art

https://git.reiners.io/justin/dgm20-linux — same approach for the Maono DGM20 (`352f:0105`).
Pure Python, no deps: protocol library, CLI (`dgm20ctl`), local web UI, udev rule, installer.
Read its PROTOCOL.md first: https://git.reiners.io/justin/dgm20-linux/raw/branch/main/PROTOCOL.md

Key finding there: the DGM20 plugin in Maono Link 4.0.88 (`DGM20_OLD.dll`) shares widget code
with the **PD200X plugin**. It includes 5-band parametric EQ, HPF/LPF and RGB colour registers the
DGM20 never uses. These are likely PD200X features.

## DGM20 protocol (assumed to carry over; unverified on PD200X)

- Vendor HID interface, usage page `0xFF01`. Requests use report `0x51` (65-byte write: id + 64),
  replies use report `0x11`. Reports `0x50`/`0x10` (15 bytes) exist but are unused.
- Packet: `[id] C4 len 00 00 type payload(u16 LE words) csum(u16 LE)`, zero-padded to 64.
  `len` = byte count from `C4` to the end, including the checksum.
  `csum` = -(sum of bytes from `C4` through the end of the payload) & 0xFFFF.
- Types: 2 = write ack (status 0 = ok); 3 = write `addr,value` pairs (the mic also sends type 3
  on its own when hardware controls change); 4 = read `addr` → `addr,value`;
  6 = range read `addr,count` → `addr,count,values...`; 5 = bulk write (serial number only).
- DGM20 registers: 0x0003 model (8 words ASCII), 0x000B firmware (3 words), 0x001E serial,
  0x1008 DFU mode, 0x100A factory reset, 0x2022 mute, 0x2026 monitor (2000 on/3000 off),
  0x2027 NC, 0x2028 NC level, 0x202C vocal enhance.
- Unused on the DGM20, likely PD200X: EQ bands at 0x204D + 5·i, each
  `[enable, type, freq Hz, gain dB×10+2000, Q×100]`; HPF 0x2066; LPF 0x206B;
  light on/off 0x2036; colour index 0x2038.

## PD200X findings (confirmed 2026-10-17, read-only, fw 1.0.3, `352f:0104`)

- Descriptor: report 0x01 = consumer keys (vol+/-, play/pause, voice cmd); vendor page 0xFF01 has
  report **0x4B** (63 B in+out) and **0x54** (10 B in+out). No 0x51/0x11.
- DGM20 framing works unchanged on report **0x4B**, same id both directions, 64-byte write.
  Types 4 and 6 confirmed.
- ASCII strings pack 2 bytes per word, low byte first (0x0003 model = "PD200X").
- Identity: 0x0000 "P0KT05PD200X", 0x000B fw 1.0.3, 0x0016/17 VID/PID, 0x0018–1A date 2023-04-06,
  0x001E serial (16 B ASCII), 0x1000 = 700…, 0x1008 = 0.
- Settings block 0x2000–0x2038 only (0x2039+ no reply; DGM20 EQ addrs 0x204D+ absent).
  0x2002–0x2009 = ASCII "Factory1Preset 1". Values seen: 2022=1 2023=96 2024=100 2027=2000
  2028=2010 2029=100 202A=200 202B=20 202D=2000 202E=100 202F=200 2030=80 2031=3000 2032=1
  2034=1000 2035=1 2036=1 2037=100 2038=0.
- Two lights: big ring around the mic (on), small ring around the volume knob. Small ring was off
  while 0x2022=1 (muted) and goes blue on the button press that makes it live.
- Listen + audio test (mic sends type 3 on its own): **0x2022 = mute, 1 = muted, 0 = live**, same as
  DGM20. Confirmed with audio: it was exact digital silence while 0x2022=1, and audio started the
  moment 0x2022→0. Earlier notes that said "unmuted" at scan time were wrong: the mic was muted.
  **0x2034 = level meter**: the mic streams it at ~18 Hz only while live (seen ~1050–1940).
  **0x2023 = mic volume**: the knob in its default blue-LED mode, steps of 4 (seen 60–100). A short
  press of VOL switches the knob LED to green (headphone volume, presumably 0x2030; unverified) and
  sends nothing by itself. Confirmed by the user: the web UI slider on 0x2023 changes mic volume.
- Maono Link writes (type 3, `FUN_18002a750` in PD200X.dll): 0x2026 and 0x202C are checkboxes
  (0/1), 0x2027/0x202D slider, 0x2035←1 + 0x2025←20 when EQ goes to "custom", 0x2036 light
  on/off, 0x2037 brightness, 0x2038 colour, 0x2039 (another light setting, can't be read),
  0x2031 2000/3000.
- **EQ (from PD200X.dll, `FUN_180013ee0` + `FUN_18000b540`)**: 7 bands, band i at 0x204D+5·i
  (0x204D–0x206F). These registers can be written but not read back, so the tool must keep EQ
  state itself. Each band is sent as ONE type-3 packet with 5 addr/value pairs (`FUN_18002a820`
  builds it, len = 4·n+7): `[enable(1 = active), type, freq Hz, gain dB×10+2000, Q×100]`.
  UI type → wire code: 0 peak→0, 3 low-pass→1, 4 high-pass→2, 1→3, 2→4 (1/2 probably the shelves;
  unconfirmed). Every factory preset has band 0 = high-pass (20–110 Hz), bands 1–5 = peaks, and
  band 6 = low-pass (7–22 kHz). Preset tables are in .data at 0x1801e50e8… as 32-byte records
  `{f64 freq, f64 gain, f64 Q, i32 type, u8 bypass}`.
  Selecting "custom" first writes 0x2035←1 and 0x2025←20, then sends all bands.
- **Write path confirmed**: a type-3 write `[0x2022, 0]` gets a type-2 ack with status 0, the
  read-back changes, and audio starts at the write. Test scripts are in the session scratchpad
  (`wr.py` single-register write with allow-list, `wrtest.py` records audio around a write).
- **EQ write test FAILED on fw 1.0.3**: 5-pair band packets (byte-identical to the app's) and a
  single write to 0x2055 get **no ack at all** and make no audible change, with or without
  0x2025←20. Writes to known registers are acked (status 0), including two-pair packets, so the
  mic seems to silently drop writes to registers it doesn't have. So far the device ignores
  writes outside 0x2000–0x2038.
  MaonoDevicesInfo.txt maps pid_0104 → PD200X.dll (correct plugin). The app's state read on
  connect is: range 0x0003×16, 0x000B×3, 0x0010×2 (DSP version? reads 6,6), 0x001E×20, then 0x2022×10,
  0x202C×10, 0x2036×8. It never reads EQ back. No PD200X firmware is bundled in the installer.
  0x2035 is written ←1 on connect (host flag?), followed by a read of 0x2089 (no reply).
- **Windows USB capture `pd1.pcapng`** (parse with `re/pcapdump.py`; HID out = ep 0x02, in = 0x82):
  - **The mic never acks EQ band packets, on Windows either.** Missing ack is normal for EQ, not a
    failure sign. Our band packets are byte-identical to the app's (64 B on the wire).
  - App band layout: **0x204D, 0x2052, 0x2057, 0x205C, 0x2061 = 5 peak/shelf bands, 0x2066 =
    high-pass (wire type 2), 0x206B = low-pass (wire type 1)**, as in the DGM20 notes. The bands are
    sent ~50 ms apart. Profile 1 = [peak 110 Hz +3 dB Q0.5, 500, 1k, 2k, 5k flat, HPF 10 Hz off,
    LPF 7 kHz on]. Profile 2 = [type 3 (low shelf?) 200 Hz −5 dB Q0.8, peak 366 Hz −2 dB Q0.5,
    1k, 5k, 10k +3 dB Q0.5, HPF 110 Hz on, LPF 22 kHz off].
  - Connect sequence: read 0x1008, range 0x0003×16, 0x000B×3, 0x0010×2, 0x001E×20, write
    0x2035←1, read 0x2089 (no reply), range 0x2022×10, 0x202C×10, 0x2036×8 (**no reply**: it runs
    past 0x2038), then writes 0x2027←2000, 0x2030←100, 0x202D←2000 (this explains 0x2030 → 100).
  - **Compressor: 0x2026 on/off, 0x2027 threshold** (dB×10+2000; app sent 1681 = −31.9 dB).
    **Limiter: 0x202C on/off, 0x202D threshold** (sent 1790 = −21.0 dB). All acked.
  - **EQ with the app's exact layout and values (`re/eq_ab2.py`, profile 1 ↔ −12 dB at 2–6 kHz) has
    no effect**, measured on the USB recording with music at −44 dBFS and checked by ear on the
    headphone monitor (monitoring on). Still unknown whether the EQ is audible on Windows.
  - Earlier Linux EQ tests used the wrong layout (HPF at 0x204D, LPF at 1 kHz, outside the app's
    range), so they don't prove anything. Retest `re/eq_ab2.py` (app layout) needs real sound at
    the mic; the first run was only room noise (−55 dBFS), so it was inconclusive.
- **0x2031 = direct monitoring (headphone jack): 2000 = on, 3000 = off.** Confirmed by ear: writing
  2000 made the mic audible in the headphones. The app's checkbox writes it, and on startup the app
  writes its saved "MonitorState" setting to it.
- Manual: VOL short press toggles the knob between mic gain and headphone volume (sends nothing by
  itself). Long press (3 s) turns noise reduction on, and then the knob sets the NR level.
  So 0x2023 (turned in headphone mode?) and 0x2030 are likely gain/volume, and 0x2026–0x202B
  probably include NR. Unverified.
- 0x3000…0xF000 range reads return what looks like stale buffer junk (repeating 8-word pattern
  after a Windows session), not real registers. Ignore them.
- After a Windows Maono Link session (user picked an EQ profile, LED blue at level 90,
  compressor+limiter OFF): **0x2037 = brightness (90)**, **0x2038 = colour index (blue = 6)**,
  0x2023 96→100, 0x2030 80→100. Nothing else readable changed (0x2025 still 0, name unchanged),
  so the EQ profile isn't stored in readable registers. Compressor and limiter both OFF fits
  0x2026 = 0 and 0x202C = 0 (the two checkboxes; probably compressor = 0x2026 with params
  0x2027–0x202B and limiter = 0x202C with 0x202D–0x2031; unverified).
  Plugin strings: "Compressor", "Limiter", "Noise Cancellation", "Gain & Volume", "mic_gain1",
  "hp_gain", "MonitorState".
- /tmp is tmpfs and is wiped on reboot, so RE work lives in `re/` (Ghidra, extracted DLLs,
  `re/pd200x.c` decompile). The hidraw node number changes across boots (hidraw1 → hidraw0).
  Access comes from `udev/70-pd200x.rules` (TAG+="uaccess", installed to /etc/udev/rules.d/),
  which gives the logged-in user an ACL. No more chown needed.
- Maono Link installer (NSIS, `7z x`) contains PD200X.dll and PD200XW.dll (x64 MSVC, Qt). PD200X.dll
  code has immediates 0x2022–0x203B (incl. 0x2039–0x203B, not readable).

## Firmware 1.2.9 (user updated via Maono Link on Windows, 2026-10-17)

- The mic didn't answer HID at all after the update until it was **replugged**.
- **The EQ works on Windows with 1.2.9** (confirmed by ear with an extreme custom profile "x",
  slot 9). Factory profiles are too subtle to hear. Everything above about the EQ "not working" was
  fw 1.0.3.
- **EQ works from Linux on 1.2.9**: a single write 0x206B←0 / ←1 (LPF enable) is acked (status 0),
  reads back, and the user confirmed by ear that it switches the 1 kHz low-pass off and on.
- Readable range is now **0x2000–0x2089** (138 registers); the EQ can be read back. Scan with
  profile "x" active:
  - 0x204D [1,0,125,2000,100] · 0x2052 [1,0,250,2000,100] · 0x2057 [1,0,500,2000,100] ·
    0x205C [1,0,986,2120,100] (+12 dB) · 0x2061 [1,0,5470,2008,100] ·
    0x2066 HPF [0,2,20,2000,100] (off) · 0x206B LPF [1,1,1000,2000,100] (**on, 1 kHz**).
  - New block 0x203E/0x2043/0x2048: [0,0,100|1000|10000,2000,100], 3 band-shaped groups, all off
    (simple 3-band mode? unknown).
  - 0x2070/0x2075/0x207A/0x207F/0x2084: [0,0,1000,2000,100], 5 more empty band slots. 0x2089 = 0.
  - 0x2039=16 0x203A=0 0x203B=1540 0x203C=167 0x203D=18 (unknown).
  - Changed vs 1.0.3: 0x2028=2050 0x2029=3 0x202A=320 0x202B=3 (compressor params?), 0x2023=70,
    0x2030=60, 0x2031=2000 (monitor on), 0x2037=70, 0x2038=0.

## Code

- `pd200x.py`: protocol library (no deps). Finds the node by VID/PID plus the 0xFF01 descriptor,
  flocks the hidraw fd for each transaction, skips 0x2034 meter packets, and range reads in chunks
  of 16 (falling back to single reads). Read-only so far.
- `pd200xctl status [--raw]`: decoded settings (plus a full register dump).
- `pd200xctl set KEY VALUE` (mute, monitor, volume, light, brightness, colour, compressor[-threshold],
  limiter[-threshold]) and `pd200xctl eq BAND [--on|--off] [--freq] [--gain] [--q]`.
  `PD200X.write()` only writes registers in the `WRITABLE` allowlist, requires a status-0 ack and
  reads each value back. Colour indices (0x2038, confirmed by eye on fw 1.2.9): 0 white, 1 red, 2 orange, 3 yellow,
  4 green, 5 cyan, 6 blue, 7 pink, 8 RGB wave, 9 static RGB; 10 looks like 9, so the CLI allows 0–9. Ranges are
  conservative guesses: thresholds −60..0 dB, EQ gain ±12 dB, Q 0.1–10, freq 20–22000.
- Value parsing and the write logic (`SETTINGS`, `set_setting`, `set_band`) live in `pd200x.py`, so
  the CLI and the web UI share them.
- `pd200x-web [--port 8200]`: stdlib HTTP server bound to 127.0.0.1 with a single inline page (no
  external assets). It polls `/api/status` every 2 s; `POST /api/set` and `/api/eq` take JSON. It
  rejects any Host header other than 127.0.0.1/localhost (DNS rebinding) and any non-JSON POST
  (cross-site form posts). The device is opened per request, so a replug recovers on its own.
- Level meter: a `Meter` thread in pd200x-web holds its own read-only fd (hidraw copies every input
  report to every open fd, so it doesn't steal replies) and keeps the latest 0x2034 value. The page
  polls `GET /api/meter` every 100 ms and shows −60..0 dB with a 1.5 s peak hold. It shows
  "no signal" when the last packet is older than 0.5 s (the mic sends nothing while muted).
  **0x2034 decodes as dB×10+2000** (looks right: with music it read −44..−52 dB, while the
  recording measured −44 dBFS RMS earlier).

## Safety rules

- Never send type 5. Never write 0x1008 or 0x100A.
- Read-only exploration first; only write registers once their meaning is confirmed.
- Don't touch the mic's buttons/knobs while writing settings (the DGM20's control channel froze;
  recovery needed a physical replug).

## Plan

1. Run `pd200x_probe.py` (read-only). Run it with no args to find the hidraw node, dump the report
   descriptor and read model/firmware. Use `scan` to read 0x2000–0x20FF and `listen` to log
   unsolicited packets while turning knobs or tapping mute. If the descriptor lacks `06 01 ff`,
   the protocol differs; analyse the descriptor.
2. Static analysis: extract the Maono Link Windows installer (7z/innoextract), find the PD200X
   plugin DLL, decompile with Ghidra to get the register meanings and value encodings.
3. Fallback only: Windows VM with USB passthrough plus USBPcap/Wireshark; diff captures while
   changing one setting at a time in Maono Link.
4. Build it like dgm20-linux: protocol lib, CLI, web UI, udev rule, flock per transaction.
