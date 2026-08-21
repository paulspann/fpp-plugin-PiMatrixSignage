# Pi Matrix Signage v0.6.42 – Install / Upgrade

Pi Matrix Signage is intended to be installed and updated through the **FPP Plugin Manager** on FPP 10+. The old customer-facing browser Upgrade tab has been removed; the underlying health-check and rollback machinery remains installed for safe application replacement.

## Normal FPP Plugin installation / upgrade

1. Open **FPP → Content Setup → Plugin Manager**.
2. Install **Pi Matrix Signage**, or choose **Update** when a newer plugin release is offered.
3. FPP runs the Pi Matrix plugin installer without SSH, preserves persistent Pi Matrix data, starts the service and verifies `http://127.0.0.1:8090/health`.
4. Open **Content Setup → Pi Matrix Signage** to return directly to the application.

The FPP-managed upgrade preserves the Pi Matrix database, media, uploaded shaders, users, messages, scenes, schedules, playlists, backups and licensing data.

## Manual / fresh install

```bash
cd /home/fpp/media/upload
unzip -o PiMatrixSignage-v0.6.42.zip
cd PiMatrixSignage
sudo ./install.sh
```

On a fresh install open `http://fpp.local:8090` (or the Pi's IP address on port 8090). The initial login is `admin / pimatrix`; the UI requires that default password to be changed.

## WHMCS licensing

The installer creates/retains:

```text
/home/fpp/media/pi-matrix-signage-data/license.env
```

A new installation defaults to:

```text
PIMATRIX_LICENSE_MODE=whmcs
PIMATRIX_LICENSE_PREFIX=PMS-
PIMATRIX_LICENSE_CHECK_HOURS=168
PIMATRIX_LICENSE_GRACE_DAYS=30
PIMATRIX_LICENSE_ENDPOINT=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php
PIMATRIX_LICENSE_PUBLIC_KEY_URL=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php
```

Install and activate the separate **Pi Matrix Signage Licensing for WHMCS v1.0.0** addon before changing `PIMATRIX_LICENSE_MODE` to `whmcs`.

The signing public key is downloaded automatically over HTTPS on the first real licence check, so there is no public-key file to copy manually. See `WHMCS-LICENSING.md`.

### Existing v0.6.0/v0.6.1 installs

`license.env` is deliberately persistent and the installer will not overwrite it. If it still points at the old `/pimatrix-licensing/pimatrix-license.php` bridge, update the two endpoint lines to the native addon URLs above before enabling WHMCS mode.

## Panel-output hardware detection

Pi Matrix Signage automatically checks FPP's detected cape identity and the physical EEPROM location that FPP records during startup. Current FPP can remove the temporary `/sys/bus/i2c/devices/*-0050/eeprom` node after it has copied/read the EEPROM, so Pi Matrix Signage does not require that temporary sysfs node to remain present. If FPP confirms that the cape identity came from a physical rPi-MFC EEPROM, the Hanson direct-HUB75 output is offered. A virtual rPi-MFC cape selection alone is not enough. If physical Hanson hardware is not confirmed, Hanson is hidden. Colorlight, Adafruit RGB Matrix HAT / Bonnet and Adafruit Triple Matrix Bonnet remain available as manual output choices; Adafruit hardware is not auto-detected because there is no reliable common identification signal across all board revisions.

Some older/unprogrammed rPi-MFC boards may not expose a usable EEPROM identity. For support/recovery only, `PIMATRIX_FORCE_RPI_MFC=1` can be added to the persistent `license.env` environment file before restarting Pi Matrix Signage. Do not use this override unless the hardware has been positively identified.

## Adafruit direct-HUB75 outputs

**Adafruit RGB Matrix HAT / Bonnet:** on Raspberry Pi 4-class hardware, configure FPP LED Panels/RGBMatrix with the `adafruit-hat` wiring pinout and one parallel output. Do not use `adafruit-hat-pwm` unless the documented GPIO4-to-GPIO18 hardware modification is physically present. 64×64 panels may require the board's Address-E jumper configuration.

**Adafruit Triple Matrix Bonnet:** configure FPP LED Panels/RGBMatrix with the `regular` wiring pinout and **3 parallel outputs** (Active3). Each IDC socket is a separate parallel HUB75 string. Power the LED panels independently from a correctly-sized 5V supply/distribution system.

Current FPP RGBMatrix direct-panel output is not supported on Raspberry Pi 5, so these Pi Matrix Signage options are intended for Raspberry Pi 4-class controllers.

## GPIO / physical controls

Pi Matrix Signage can monitor three GPIO inputs from **Display setup → GPIO / physical controls**. The fixed mappings are Input A = GPIO6 (header pin 31), Input B = GPIO13 (header pin 33), and Input C = GPIO26 (header pin 37). On a Hanson rPi-MFC use the dedicated CN2/CN3/CN4 connectors. On a Colorlight installation wire a dry/voltage-free contact directly between the matching Raspberry Pi header pin and a Pi GND pin; the switch does not connect to the Colorlight receiver. Never apply external voltage to a Pi GPIO input.

GPIO physical controls are automatically unavailable when either Adafruit direct-HUB75 output is selected because both the `adafruit-hat` and Active3/`regular` mappings use GPIO6, GPIO13 and GPIO26 for panel signals.

Use voltage-free switch/relay contacts only; the inputs use pull-ups and should be switched to GND. Do not apply external 5V/12V to a GPIO input.
