# Pi Matrix Signage v0.6.2 – Install / Upgrade

v0.6.2 switches the commercial-licensing integration to the native **Pi Matrix Signage Licensing** WHMCS addon while keeping licence enforcement **disabled by default** (`development` mode). Existing installations therefore continue to operate normally while WHMCS is commissioned.

## Upgrade from v0.5.x / v0.6.x

1. Open **Upgrade** in Pi Matrix Signage.
2. Upload `PiMatrixSignage-v0.6.2.zip`.
3. Wait for the service to restart and reconnect.
4. Confirm the interface reports `v0.6.2`.
5. If this installation predates v0.6.0, run `sudo ./install.sh` once from the release folder so `python3-cryptography` and the persistent `license.env` systemd configuration are installed.

The browser upgrade preserves the database, media, uploaded shaders, users, messages, scenes, schedules, playlists, backups and FPP/display configuration.

## Manual / fresh install

```bash
cd /home/fpp/media/upload
unzip -o PiMatrixSignage-v0.6.2.zip
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
PIMATRIX_LICENSE_MODE=development
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

## GPIO / physical controls (rPi-MFC)

Pi Matrix Signage can monitor the Hanson rPi-MFC's three dedicated user inputs from **Display setup → GPIO / physical controls**. The fixed mappings are Input A/CN2 = GPIO6 (header pin 31), Input B/CN3 = GPIO13 (header pin 33), and Input C/CN4 = GPIO26 (header pin 37).

Use voltage-free switch/relay contacts only; the inputs use pull-ups and should be switched to GND. Do not apply external 5V/12V to a GPIO input.
