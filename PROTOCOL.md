# Maono PD200X HID protocol

Notes for the Maono PD200X USB mic (`352f:0104`). They come from the device itself, captures of
Maono Link 4.0.88 on Windows, and the app's PD200X plugin (`PD200X.dll`). Firmware 1.2.9 unless
stated otherwise. The framing is the same as the Maono DGM20's, documented in
[dgm20-linux](https://git.reiners.io/justin/dgm20-linux/raw/branch/main/PROTOCOL.md).

Audio is plain USB audio class. This protocol only carries settings.

## Transport

The mic exposes a HID interface. Report 0x01 holds consumer keys (volume, play/pause, voice
command). The vendor usage page `0xFF01` has two reports:

- **0x4B** (63 bytes in and out): all requests and replies use it, with the same id both ways.
  Write 64 bytes to hidraw (the report id plus 63).
- 0x54 (10 bytes in and out): unused.

hidraw delivers each input report to every open fd, so a second reader (such as a level meter)
doesn't take replies away from the fd that sent the request.

## Packet

```
4B  C4  len  00  00  type  payload (u16 LE words)  csum (u16 LE)   zero-padded to 64 bytes
```

- `len` counts the bytes from `C4` to the end of the checksum: 7 + 2 × words.
- `csum = -(sum of bytes from C4 to the end of the payload) & 0xFFFF`.

| type | direction | payload |
|---|---|---|
| 2 | mic → host | write ack: `status` (0 = ok) |
| 3 | host → mic | write: `addr, value, addr, value, …` |
| 3 | mic → host | the same format, sent on its own when a button or knob changes something, and for the level meter |
| 4 | both | read one: request `addr`, reply `addr, value` |
| 6 | both | range read: request `addr, count`, reply `addr, count, values…` |
| 5 | — | bulk write (serial number on the DGM20). **Never send it.** |

A range read that runs past the last readable register gets no reply at all. Read in chunks and
fall back to single reads.

On firmware 1.0.3 the mic ignored writes outside 0x2000–0x2038 and didn't ack them. On 1.2.9 every
write tested so far is acked.

## Encodings

- **dB**: `value = dB × 10 + 2000` (gains, thresholds, level meter).
- **Q**: `Q × 100`.
- **Strings**: 2 ASCII bytes per word, low byte first, NUL-terminated.

## Identity

| addr | content |
|---|---|
| 0x0000 | "P0KT05PD200X" |
| 0x0003 | model, 8 words ("PD200X") |
| 0x000B | firmware, 3 words (major, minor, patch) |
| 0x0010 | 2 words (6, 6); the app reads them, meaning unknown |
| 0x0016 / 0x0017 | VID / PID |
| 0x0018–0x001A | date (2023-04-06) |
| 0x001E | serial, 16 bytes |
| 0x1008 | DFU mode. **Never write.** |
| 0x100A | factory reset. **Never write.** |

## Settings (0x2000–0x2089)

Readable as one block on firmware 1.2.9 (1.0.3 only answers up to 0x2038).

| addr | setting | values |
|---|---|---|
| 0x2002–0x2009 | preset name | string ("Factory1Preset 1") |
| 0x2022 | mute | 1 = muted, 0 = live |
| 0x2023 | mic volume | 0–100 (knob with green LED, steps of 4) |
| 0x2026 | compressor | 0/1 |
| 0x2027 | compressor threshold | dB |
| 0x202C | limiter | 0/1 |
| 0x202D | limiter threshold | dB |
| 0x2030 | headphone volume | 0–100 (knob with blue LED; a short VOL press switches the knob) |
| 0x2031 | direct monitoring | 2000 = on, 3000 = off |
| 0x2034 | level meter | dB; streamed by the mic at ~18 Hz while live, nothing while muted |
| 0x2035 | host flag? | the app writes 1 on connect |
| 0x2036 | light | 0/1 |
| 0x2037 | brightness | 0–100 |
| 0x2038 | colour | 0 white, 1 red, 2 orange, 3 yellow, 4 green, 5 cyan, 6 blue, 7 pink, 8 RGB wave, 9 static RGB |
| 0x2039 | light linkage (lights off while muted) | 0/1; write only: reads 16 regardless |
| 0x203A | noise cancellation | 0/1 |
| 0x203B | noise cancellation level | `(level + 120) × 10`, level 0–40 (1200–1600) |

Not understood yet: 0x2024 (100), 0x2025 (the app writes 20 when switching the EQ to custom),
0x2028–0x202B (probably compressor parameters), 0x202E, 0x202F, 0x2032, 0x203C (167), 0x203D (18).

### EQ

Seven bands of 5 registers each, `[enable, type, freq Hz, gain dB, Q]`:

| base | band |
|---|---|
| 0x204D, 0x2052, 0x2057, 0x205C, 0x2061 | bands 1–5 (peak or shelf) |
| 0x2066 | high-pass |
| 0x206B | low-pass |

Type codes: 0 peak, 1 low-pass, 2 high-pass, 3 and 4 probably low and high shelf (unconfirmed).

Maono Link sends each band as one type-3 packet with 5 pairs, about 50 ms apart. When it selects a
custom profile it first writes 0x2035 ← 1 and 0x2025 ← 20. Profiles are stored in the app, not on
the mic. The EQ only takes effect on firmware 1.2.x (1.0.3 ignores it).

More band-shaped groups that the app doesn't use: 0x203E, 0x2043, 0x2048 (3 groups at
100 Hz/1 kHz/10 kHz, all off), and 0x2070–0x2088 (5 empty slots). 0x2089 = 0.

## Connect sequence (Maono Link)

Read 0x1008, range 0x0003×16, 0x000B×3, 0x0010×2, 0x001E×20, write 0x2035 ← 1, read 0x2089, range
0x2022×10, 0x202C×10, 0x2036×8. Then it writes its saved settings (compressor and limiter
thresholds, headphone volume, monitoring).

## Cautions

- The DGM20's control channel could freeze when its buttons were used during writes; recovering
  took a replug. Avoid touching the controls while writing.
- After a firmware update the mic didn't answer HID until it was replugged.
- Range reads at 0x3000 and above return stale buffer contents, not registers.
