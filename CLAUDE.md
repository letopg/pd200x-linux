# pd200x-linux

Linux control tool for the Maono PD200X USB mic (`352f:0104`) over hidraw. User docs are in
README.md; the protocol and register map are in PROTOCOL.md. Keep PROTOCOL.md up to date when a
register is confirmed.

## Code

- `pd200x.py`: protocol library. `SETTINGS`, `set_setting` and `set_band` are shared by the CLI and
  the web UI. `PD200X.write()` refuses registers outside `WRITABLE`, requires a status-0 ack and
  reads each value back (except `NO_READBACK`).
- `pd200xctl`: CLI. `pd200x-web`: stdlib HTTP server with one inline page. Its `Meter` thread
  holds its own read-only fd for the 0x2034 level stream.
- `pd200x_probe.py`: read-only probe (`scan`, `listen`).
- `re/` (gitignored): Maono Link extracted DLLs, Ghidra project and the `PD200X.dll` decompile
  (`re/pd200x.c`), `pcapdump.py` for USBPcap captures (HID out = ep 0x02, in = 0x82).

## Safety rules

- Never send type 5. Never write 0x1008 (DFU) or 0x100A (factory reset).
- Only add a register to `WRITABLE` once its meaning is confirmed (Windows capture or decompile,
  then a test on the device).
- Don't touch the mic's buttons or knobs while writing settings.
- Before a test write, read the current value and restore it afterwards.
- Don't run `install.sh` for real on the dev machine; test it with a temporary `PREFIX`.

## Open questions

- 0x2024, 0x2025, 0x2028–0x202B, 0x202E, 0x202F, 0x2032, 0x203C, 0x203D; what 0x2039 reads (16).
- EQ type codes 3/4 (shelves?) and the unused band groups at 0x203E–0x204C and 0x2070–0x2088.
- Holding VOL for 3 s (noise reduction per the manual) changed no register on fw 1.2.9.
