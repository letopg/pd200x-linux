# pd200x-linux

Control the **Maono PD200X** USB microphone (`352f:0104`) on Linux: mute, volumes, monitoring,
ring light, compressor, limiter, noise cancellation and the 7-band EQ. These are the settings
Maono Link offers on Windows and macOS.

Pure Python 3 standard library, no dependencies. It talks to the mic over hidraw from userspace;
audio itself already works through the standard USB audio driver. Modelled on
[dgm20-linux](https://git.reiners.io/justin/dgm20-linux) for the Maono DGM20.

Tested with firmware 1.2.9. On 1.0.3 the EQ has no effect; update the firmware with Maono Link
(and replug the mic afterwards).

## Install

```sh
./install.sh              # copies to ~/.local, installs the udev rule (asks for sudo)
./install.sh --service    # also runs the web UI at login (systemd user service)
./install.sh --uninstall
```

The udev rule (`udev/70-pd200x.rules`) gives the logged-in user access to the mic's hidraw node.
Without it, the tools need root.

You can also run `pd200xctl` and `pd200x-web` straight from the checkout.

## Command line

```
pd200xctl status [--raw]
pd200xctl set mute on|off
pd200xctl set monitor on|off                    headphone monitoring
pd200xctl set mic-volume 0-100
pd200xctl set headphone-volume 0-100
pd200xctl set light on|off
pd200xctl set brightness 0-100
pd200xctl set colour white|red|orange|yellow|green|cyan|blue|pink|rgb-wave|rgb-static
pd200xctl set light-linkage on|off              lights off while muted
pd200xctl set compressor on|off
pd200xctl set compressor-threshold -60..0       dB
pd200xctl set limiter on|off
pd200xctl set limiter-threshold -60..0          dB
pd200xctl set noise-cancel on|off
pd200xctl set noise-cancel-level 0-40
pd200xctl eq BAND [--on|--off] [--freq HZ] [--gain DB] [--q Q]   BAND = 1-5, hpf, lpf
```

Every write is checked: the mic must acknowledge it, and the value is read back. Light linkage is
the exception: the mic doesn't report it, so only the acknowledgement is checked.

## Web UI

```sh
pd200x-web [--port 8200]
```

Then open <http://127.0.0.1:8200/>. It shows every setting above, the EQ and a live level meter.
It only listens on localhost, and rejects foreign Host headers and non-JSON posts, so other
websites can't drive it.

## Protocol

See [PROTOCOL.md](PROTOCOL.md). `pd200x_probe.py` is the read-only probe used to explore the
device (`scan` dumps registers, `listen` prints what the mic sends when you use its controls).

The writable registers are an allowlist in `pd200x.py`. Only registers whose meaning has been
confirmed are on it; the DFU and factory-reset registers never are.

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Maono.
