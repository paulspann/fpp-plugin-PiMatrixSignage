# Pi Matrix Signage FPP Plugin v0.1.28

10+ bootstrap/integration plugin for Pi Matrix Signage on Raspberry Pi.

## What it does

- installs all required FPP/OS dependencies through FPP's Plugin Manager;
- installs Pi Matrix Signage as `pi-matrix-signage.service`;
- health-checks the application after installation;
- adds **Content Setup → Pi Matrix Signage** to the FPP menu;
- preserves Pi Matrix messages, schedules, media and licensing data across updates;
- supports normal FPP Plugin Manager updates without downgrading a newer application build.

No SSH is required for the customer installation flow.

## Repository / test installation

This bootstrap is configured for:

`https://github.com/paulspann/fpp-plugin-PiMatrixSignage`

Push the contents of this package to the **root of the `main` branch** so `pluginInfo.json` is available at:

`https://raw.githubusercontent.com/paulspann/fpp-plugin-PiMatrixSignage/main/pluginInfo.json`

For beta testing, open FPP's Plugin Manager, paste that raw `pluginInfo.json` URL into the custom plugin URL field, choose **Get Plugin Info**, then install **Pi Matrix Signage**. Once proven, the repository can be submitted to the normal FPP plugin catalogue separately.

## Current bootstrap payload

This test bootstrap contains Pi Matrix Signage v0.6.58. The next commercial-hardening stage should move the application payload out of the public bootstrap repository and retrieve a signed, licence-authorised release package from the ISSL/WHMCS licensing service.



## v0.1.28

- Bundles Pi Matrix Signage **v0.6.58** with layered live cloud-cover rendering for Sky Weather.
- Live weather now carries Open-Meteo total/low/mid/high cloud cover into the shader so full overcast renders as a continuous moving deck instead of sparse individual clouds.

## v0.1.2

- Lowers FPP Plugin Manager resource hints to 512 MB RAM / 1 CPU core so nominal 1 GB Raspberry Pi systems are not incorrectly flagged as insufficient.
- The installer still performs its real Pi Matrix Signage health check after installation.


## v0.1.3

- The FPP **Content Setup → Pi Matrix Signage** menu item now opens the Pi Matrix Signage web service directly on port 8090 instead of routing through FPP `plugin.php`.
- This avoids FPP's “Unknown / Please don't access the page directly” wrapper error.
- The existing FPP status/management page remains in the plugin package for diagnostics, but it is no longer used as the primary menu destination.


## v0.1.4

- Bundles Pi Matrix Signage **v0.6.7**.
- Makes **FPP Plugin Manager** the normal customer-facing update path; the Pi Matrix application no longer exposes its own Upgrade tab.
- Plugin Manager **Update** continues to run the idempotent installer, preserve persistent Pi Matrix data, start the service and verify the application health endpoint.
- The proven Pi Matrix privileged updater/rollback engine remains packaged inside the application for recovery and maintenance, but customers no longer upload release ZIP files manually.


## v0.1.5

- Bundles Pi Matrix Signage v0.6.29.
- Fixes Plugin Manager updates that copied new files but left the old Python process running.
- Verifies `/health` reports the expected application version before an install/update is considered successful.

## v0.1.7

- Fixes FPP uninstall on builds where sourcing `/opt/fpp/scripts/common` under `set -u` aborts with `LD_LIBRARY_PATH: unbound variable`.
- Plugin install/uninstall scripts are now self-contained and no longer source FPP `scripts/common`.
- Uninstall explicitly stops/disables the Pi Matrix service, removes the replaceable application and privileged helpers, preserves `/home/fpp/media/pi-matrix-signage-data`, and verifies that no Pi Matrix process/application directory remains before reporting success.
## v0.1.8 upgrade compatibility

FPP Plugin Manager updates intentionally do **not** ship `scripts/fpp_upgrade.sh`. Current FPP falls back to rerunning `scripts/fpp_install.sh` when that file is absent. This avoids a Git executable-mode failure where FPP tried to execute a newly uploaded `fpp_upgrade.sh` directly and `sudo` returned `command not found`. The normal install script is idempotent and already performs the application update, service restart, and exact running-version health check.


## v0.1.9

- Bundles Pi Matrix Signage **v0.6.30**.
- Installs/removes the new root-owned `pi-matrix-signage-reset` helper and grants only the plugin service account passwordless access to the three narrow privileged helpers.
- Adds transfer-safe factory reset support without removing the Pi Matrix Signage application or FPP plugin.

## v0.1.10

- Bundles Pi Matrix Signage **v0.6.31**.
- Fixes the Software licence support link so live licence rendering cannot overwrite it.

## v0.1.11

- Bundles Pi Matrix Signage **v0.6.33**.
- Moves the System support package from Backup & restore to System diagnostics and aligns its access permission with that page.
- Adds customer-facing support instructions to that panel, directing users to support@issl.co.uk with the generated diagnostic ZIP and useful fault details.



## v0.1.12

- Bundles Pi Matrix Signage **v0.6.34**.
- Makes GPIO / physical-control wiring guidance hardware-aware: Hanson installations use CN2/CN3/CN4, while Colorlight installations use the Raspberry Pi header directly on GPIO6/GPIO13/GPIO26.


## v0.1.13

- Bundles Pi Matrix Signage **v0.6.35**.
- Automatically detects a physical Hanson rPi-MFC from its FPP EEPROM identity.
- Hides Hanson output/profile choices when the board is absent and assumes Colorlight instead, while retaining a support-only environment override for old/unprogrammed boards.


## v0.1.14

- Bundles Pi Matrix Signage **v0.6.37**.
- Fixes Hanson rPi-MFC detection on current FPP by using FPP's recorded physical EEPROM origin/cache after FPP removes its temporary sysfs EEPROM node.
- Keeps virtual rPi-MFC cape selections from being mistaken for physically fitted Hanson hardware.


## v0.1.15

- Bundles Pi Matrix Signage **v0.6.44** selectable FPP-first / appliance interface mode.
- Keeps FPP as the internal bootstrap/update/hardware platform while making Pi Matrix Signage the normal customer-facing controller UI.
- Enables the bare controller URL to open Pi Matrix Signage without intercepting FPP APIs or explicit engineering pages.
- Installs the narrow managed-update helper used by Pi Matrix Signage's Controller software panel.
- Uninstall removes the appliance Apache entry point and restores the normal FPP root behaviour.


## v0.1.16

- Bundles Pi Matrix Signage **v0.6.46**.
- Adds cached background application-update checking and top-of-screen update notification without putting network update checks on the renderer or normal status-request path.


## v0.1.17

- Bundles Pi Matrix Signage **v0.6.47**.
- Adds the low-resolution Designer split-flap text animation with per-character fake flips, stagger and settle order controls.



## v0.1.20

- Bundles Pi Matrix Signage **v0.6.50**.
- Adds the low-resolution effects/shader expansion: new text animations, mechanical split-flap casing, rolling live digits, colour wave, six new built-in shaders, expanded Aurora and five additional pixel scene/layer transitions.


## v0.1.19

- Bundles Pi Matrix Signage **v0.6.49**.
- Sequential split-flap lines now retain one fixed departure-board cell bank and visibly flap surplus characters to blank when the next line is shorter.

## v0.1.18

- Bundles Pi Matrix Signage **v0.6.48**.
- Adds optional sequential multiline text: non-empty lines can automatically share a text layer’s available scene timeline and display one after another.


## v0.1.21

- Bundles Pi Matrix Signage **v0.6.51**.
- Strengthens the low-resolution Departure Board Black split-flap casing with larger fixed cells, clearer frames, distinct upper/lower flap faces, a visible over-glyph centre hinge and persistent blank physical modules.


## v0.1.22

- Bundles Pi Matrix Signage **v0.6.52**.
- Moves departure/airport split-flap casing fully outside the glyph, adds guaranteed inner LED clearance and exposes adjustable casing padding for low-resolution physical-module styling.


## v0.1.23

- Bundles Pi Matrix Signage **v0.6.53**.
- Adds locally calculated live lunar phase rendering to the Sky Weather shader, including waxing/waning orientation and cloud occlusion without an additional network request.


## v0.1.24

- Bundles Pi Matrix Signage **v0.6.54**.
- Split-flap messages now enter from genuinely blank cells on an empty display; fake flips remain for subsequent populated-cell transitions and clearing cells to blank.

## v0.1.25

- Bundles Pi Matrix Signage **v0.6.55**.
- Makes first-arrival split-flap characters visibly unfold from a blank centre hinge without fake/random startup glyphs, and makes character-to-blank transitions fold away physically.

## v0.1.26

- Bundles Pi Matrix Signage **v0.6.56**.
- Blank split-flap cells now advance through the ordered alphabetic/numeric flap wheel until they reach the requested face; fake/random startup glyphs remain disabled.
- Adds the fixed-font, numeric-only **Nixie tubes** display option with an eight-digit maximum.


## v0.1.27

- Bundles Pi Matrix Signage **v0.6.57**.
- Adds optional independent Nixie **Build up from 0000** animation with a dedicated total build duration; each tube advances only to its own requested digit rather than numerically counting the whole displayed value.
