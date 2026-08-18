# Pi Matrix Signage FPP Plugin

FPP 10+ bootstrap/integration plugin for Pi Matrix Signage on Raspberry Pi.

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

This test bootstrap contains Pi Matrix Signage v0.6.6. The next commercial-hardening stage should move the application payload out of the public bootstrap repository and retrieve a signed, licence-authorised release package from the ISSL/WHMCS licensing service.
