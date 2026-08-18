# WHMCS licensing setup – Pi Matrix Signage v0.6.2+

Pi Matrix Signage now uses the native **Pi Matrix Signage Licensing** WHMCS addon module rather than a standalone bridge script. The application still ships with `PIMATRIX_LICENSE_MODE=development` so an existing sign cannot be disabled before the commercial licensing product is ready.

## WHMCS

Install the separate `WHMCS-PiMatrix-Licensing-Addon-v1.0.0.zip` package into the WHMCS root so that the module lives at:

```text
modules/addons/pimatrixlicensing/
```

Then activate **Pi Matrix Signage Licensing** under WHMCS Addon Modules. The module automatically:

- creates its device/history tables;
- creates a random WHMCS local-key secret;
- creates an RSA signing key pair;
- detects the installed Software Licensing Addon's `check_license` or prefixed `*_check_license` function at runtime;
- registers WHMCS licensing verification and reissue hooks.

There is no manual extraction of `check_sample_code.php`, no separate bridge configuration file and no private signing key to copy to the Raspberry Pi.

For ISSL the endpoints are:

```text
https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php
https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php
```

The first URL returns a harmless health response when opened with GET. The second exposes only the public RSA key.

## WHMCS product

Create the Pi Matrix Signage product and choose **License Software** in Module Settings. Recommended settings:

- Prefix: `PMS-`
- Allow Reissue: enabled
- Allow Domain Conflict: unchecked
- Allow IP Conflict: checked
- Allow Directory Conflict: checked

The Pi's hashed Device ID is presented as a pseudo-domain to WHMCS, so the standard Software Licensing domain/location lock becomes the physical-controller lock. A normal WHMCS Reissue clears the location and the Pi Matrix addon clears its recorded device association through the official licensing reissue hook.

After the product exists, configure **Allowed WHMCS Product IDs** in the Pi Matrix addon so only that product can activate Pi Matrix Signage.

## Pi configuration

The persistent `license.env` should contain:

```text
PIMATRIX_LICENSE_MODE=development
PIMATRIX_LICENSE_PREFIX=PMS-
PIMATRIX_LICENSE_CHECK_HOURS=168
PIMATRIX_LICENSE_GRACE_DAYS=30
PIMATRIX_LICENSE_ENDPOINT=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php
PIMATRIX_LICENSE_PUBLIC_KEY_URL=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php
```

During initial testing leave `PIMATRIX_LICENSE_MODE=development`. Once a real WHMCS licence has activated and the replacement/reissue path has been tested, switch it to:

```text
PIMATRIX_LICENSE_MODE=whmcs
```

On the first activation/check, Pi Matrix downloads the public signing key over HTTPS and stores it locally in the persistent data directory. The WHMCS private key and local-key secret never leave the WHMCS server.
