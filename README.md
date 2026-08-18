# Pi Matrix Signage FPP Plugin v0.1.6

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

This test bootstrap contains Pi Matrix Signage v0.6.8. The next commercial-hardening stage should move the application payload out of the public bootstrap repository and retrieve a signed, licence-authorised release package from the ISSL/WHMCS licensing service.


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

- Bundles Pi Matrix Signage v0.6.8.
- Fixes Plugin Manager updates that copied new files but left the old Python process running.
- Verifies `/health` reports the expected application version before an install/update is considered successful.

## v0.1.6

- Fixes FPP uninstall on builds where sourcing `/opt/fpp/scripts/common` under `set -u` aborts with `LD_LIBRARY_PATH: unbound variable`.
- Plugin install/uninstall scripts are now self-contained and no longer source FPP `scripts/common`.
- Uninstall explicitly stops/disables the Pi Matrix service, removes the replaceable application and privileged helpers, preserves `/home/fpp/media/pi-matrix-signage-data`, and verifies that no Pi Matrix process/application directory remains before reporting success.
