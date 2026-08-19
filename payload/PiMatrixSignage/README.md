# Pi Matrix Signage v0.6.24


## v0.6.24 – optional Colorlight output

- Adds a saved Hanson rPI-MFC / Colorlight output choice in Display Setup.
- Supports Colorlight 5A-75B and 5A-75E receiver profiles with a dedicated network-interface setting.
- Builds hardware-specific FPP setup instructions and checks whether the selected interface is present.
- Adds common Colorlight scan rates while preserving rPI-MFC validation and GPIO behaviour.

## v0.6.23 – reliable black colour selection

- Stops the colour picker's internal native input from being enhanced as a second nested colour field, which caused the popover to jump and then disappear.
- Adds Black and White to the preset palette for immediate selection.
- Applies a preset on the first click and closes the popover without changing the inspector layout.


## v0.6.22 – duplicate-free Cloud Text

- Prevents a phrase at the start of a new shuffled round from duplicating one still visible from the preceding round.
- Removes duplicate input phrases using case-insensitive, whitespace-normalized matching while preserving the first spelling entered.
- Automatically spaces arrivals according to the number of unique phrases when that is lower than Maximum visible.


## v0.6.21 – accurate colour by word

- Makes **Colour by word** follow the real rendered word boundaries rather than dividing the layer into equal-width colour bands.
- Keeps every letter of a word in one palette colour regardless of differences in word length, spacing, alignment or font width.


## v0.6.20 – stable Cloud Text arrivals

- Keeps every phrase at one random position for its complete visible lifetime, preventing apparent instant duplicates when another phrase expires.
- Gives each playback a fresh stable random seed instead of deriving positioning from render-frame timing.
- Enforces at least 0.2 seconds of fade-in and fade-out so Cloud Text cannot appear or disappear as a hard cut.


## v0.6.19 – free-positioned Cloud Text

- Replaces Cloud Text's visibly column-based slots with collision-aware random positioning across the complete layer.
- Randomizes both horizontal and vertical placement while retrying positions that would overlap visible text.
- Retains whole-word wrapping, in-layer containment, spacing and the maximum-visible limit.


## v0.6.18 – whole-word Cloud Text wrapping

- Prevents Cloud Text from splitting a word across two lines.
- Wraps only at spaces and shrinks unusually long individual words to keep them visible inside their reserved area.


## v0.6.17 – Cloud Text layers

- Adds a **Cloud Text** Designer layer for displaying a list of short phrases at randomized positions.
- Shuffles the complete phrase list before repeating, so every entry receives a turn while each playback uses a fresh order and placement.
- Automatically fits every phrase inside a reserved area of the layer, keeping visible phrases fully on-screen and preventing overlap.
- Adds controls for appearance interval, visible time, fade-in/out, maximum simultaneous phrases, spacing, font, LED text rendering and solid or random-palette colours.


## v0.6.16 – built-in Help manual

- Adds a comprehensive searchable operating manual at `/help` covering setup, licensing, content, Designer, shaders, live weather, playlists, schedules, emergency operation, backups, users, permissions, remote control, maintenance and troubleshooting.
- Adds a top-bar **Help** link that opens the manual in a new browser tab.
- Automatically changes the Help link fragment as users navigate so it opens at the section matching the current application page.


## v0.6.15 – live WHMCS licence enforcement

- Changes new installations from development licensing to live WHMCS enforcement by default.
- Migrates an existing default `PIMATRIX_LICENSE_MODE=development` setting to `whmcs` during upgrade while preserving its licence key, signed entitlement, endpoint and device identity.
- Keeps development mode available only as an explicit diagnostic override.


## v0.6.14 – streamlined Display setup

- Removes the entire customer-facing **Software updates** information block from Display setup, including the installed-version badge and FPP update instructions.
- Keeps the underlying FPP update, health-check, licence refresh and rollback machinery unchanged.


## v0.6.13 – licence refresh after software updates

- Re-authenticates an installed WHMCS licence shortly after the application restarts on a new software version.
- Sends the newly installed application version through the existing signed licence-check request and records the version successfully reported.
- Retries later if WHMCS is temporarily unavailable without blocking installation, startup or the existing offline grace entitlement.


## v0.6.12 – optional live weather shader

- Adds an optional **Use live weather** mode to the built-in Sky Weather shader for both scene backgrounds and shader layers.
- Uses the existing Open-Meteo integration to select clear, cloudy, rain, snow or storm visuals and day/night phase automatically.
- Maps live cloud cover, wind direction, wind speed and precipitation intensity to the shader while retaining saved manual controls as an offline fallback.
- Keeps manual Sky Weather operation unchanged when live weather is disabled.


## v0.6.11 – independent sun and moon positioning

- Keeps cloud and weather animation speed independent from the sun or moon.
- Adds horizontal position and height controls for the sun or moon.
- Makes the celestial body stationary by default, with optional left-to-right or right-to-left movement and a separate speed control.


## v0.6.10 – animated sky and weather shader

- Adds a built-in **Sky Weather** generator with clear, partly cloudy, overcast, rain, snow and storm modes.
- Provides day, sunset and night phases with a moving sun or moon, stars, horizon glow and layered wind-driven clouds.
- Adds controls for movement speed, wind direction, cloud cover, precipitation intensity, sun/moon size and all key colours.
- Keeps rain streaks, snow particles, clouds and lightning readable on low-resolution P5/P10 panels.


## v0.6.9 – settings menu

- Moves **Display setup**, **Backup & restore**, and **Users** out of the main navigation into a cogwheel menu at the top right.
- Preserves each destination's existing user permission and visibility rules.
- Hides the cogwheel when the signed-in user has access to none of its destinations.


## v0.6.8 – reliable FPP Plugin Manager restart

- Fixes FPP Plugin Manager updates leaving the previous Pi Matrix Signage Python process running after new application files were installed.
- The installer now explicitly restarts an already-active `pi-matrix-signage.service`; `systemctl enable --now` alone does not restart an active service.
- This makes the newly installed version take effect immediately without SSH or rebooting the FPP device.


## v0.6.7 – FPP-managed updates

- Removes the customer-facing **Upgrade** tab now that Pi Matrix Signage is installed and updated through the FPP Plugin Manager.
- Removes the obsolete Upgrade checkbox from the Users tab; existing backend `can_upgrade` data remains untouched for legacy maintenance endpoints.
- Keeps the existing privileged upgrade helper, health-check, safety backup and rollback code packaged underneath rather than deleting the proven recovery machinery.
- Makes legacy upgrade-page JavaScript conditional so removing the page cannot cause browser startup errors.

## v0.6.6 – FPP Plugin installer support

- Adds an installer mode for the FPP Plugin Manager so FPP 10 can install system/Python dependencies before Pi Matrix Signage is deployed.
- `install.sh` now honours `PIMATRIX_SKIP_DEPENDENCY_INSTALL=1`, avoiding a second apt transaction when installation is launched by the Pi Matrix Signage FPP plugin.
- Normal standalone installation behaviour is unchanged when that environment variable is not set.

## v0.6.5 – WHMCS activation diagnostics

- Works with WHMCS Pi Matrix Licensing addon v1.0.1.
- A rejected WHMCS activation no longer installs an invalid licence locally.
- Development mode now shows the actual last WHMCS activation failure instead of leaving a confusing half-installed state.

## v0.6.4 – development-mode WHMCS activation testing

- Keeps the licence key field and **Activate / update licence** button usable while the controller is in Development mode.
- Development mode now means only that commercial enforcement is disabled; it no longer prevents testing a genuine WHMCS licence against the real device ID.
- After a successful test activation the Software licence panel shows the masked key, customer/product details and signed verification/grace dates while continuing to leave display output unlocked.
- **Check now** can refresh an installed test licence in Development mode; background enforcement/refresh remains disabled until `PIMATRIX_LICENSE_MODE=whmcs` is deliberately enabled.

## v0.6.3 – WHMCS licensing startup fix

- Fixes the v0.6.2 startup crash `NameError: login_required is not defined` on the `/api/license` route.
- The application-wide `before_request` authentication gate already protects `/api/license`, so the invalid redundant decorator has been removed.
- Adds a cold-import startup regression test so route decorators are evaluated during automated testing, matching the failure mode systemd exposed on the Pi.
- WHMCS addon endpoints and device-binding behaviour are unchanged from v0.6.2.

## v0.6.2 – native WHMCS addon licensing

- Replaces the standalone WHMCS bridge endpoint with the native **Pi Matrix Signage Licensing** WHMCS addon module.
- Defaults to `https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php`.
- Automatically downloads and pins the addon's RSA public signing key from the WHMCS server on first activation; no manual public-key copy is required.
- Can refresh the pinned public key once if the WHMCS addon signing key is intentionally rotated/recreated.
- Keeps commercial enforcement in development mode by default until the WHMCS addon/product has been tested.


## v0.6.1 – ISSL WHMCS endpoint configuration

- Originally preconfigured the standalone ISSL bridge endpoint (superseded by the native WHMCS addon in v0.6.2).
- Kept licensing in **development mode** while the original WHMCS bridge was commissioned.
- Superseded by v0.6.2 native addon endpoints.




## v0.6.0 – WHMCS commercial licensing foundation

- Adds a **Software licence** panel under Display setup with controller Device ID, licence state, activation, manual re-check and local-clear actions.
- Adds a stable privacy-minimised Device ID derived primarily from the Raspberry Pi hardware serial, hashed before it is displayed or sent.
- Adds commercial **WHMCS mode** and a separate **development mode** so licensing can be commissioned without locking out the current development installation.
- WHMCS mode accepts only **RSA/SHA-256 signed entitlements** from the configured HTTPS bridge; the Pi contains the public verification key only.
- Signed entitlements support an online-validity window and an offline grace period, so a temporary Internet/WHMCS outage does not immediately stop a sign.
- Normal message/playlist/schedule/emergency output is gated by licence validity in WHMCS mode. Panel test patterns remain available for hardware installation and diagnosis before activation.
- Adds persistent `/home/fpp/media/pi-matrix-signage-data/license.env` configuration and installs Python cryptography support.
- The original companion WHMCS bridge proved the device-locking/signing design; v0.6.2 replaces it with the native WHMCS addon.

This release deliberately remains in **development licensing mode** by default. Switch to `PIMATRIX_LICENSE_MODE=whmcs` only after the native WHMCS addon and a real test licence have been installed and tested. Source-code compilation/anti-tamper and signed upgrade packages remain later commercial-hardening stages.

## v0.5.14 – Cars on Road direction fix

- Fixes **Right to left** traffic so the cars now both **face left and actually travel right-to-left**.
- The previous shader reversed the time movement and then mirrored the x-coordinate, unintentionally reversing the motion twice.
- Adds a regression test for the horizontal direction calculation.

## v0.5.13 – Cars on Road true 16-pixel rendering

- Rebuilds **Cars on Road** around the physical LED pixel height instead of normalised scene proportions.
- At a 16-pixel layer the cars are now roughly **8–9 pixels high**, with chunky side-view bodies, roofs, windows, wheels and bright front/rear lights.
- Removes the lane/road-scene concept almost entirely; only a thin 2-pixel road/base remains so the cars dominate the strip.
- Direction is now simply **Left to right** or **Right to left**. Controls are reduced to **Speed**, **Cars**, **Car size**, road colour and light colours.

## v0.5.12 – Cars on Road low-height simplification

- Simplifies **Cars on Road** for the real target use case of **about 16 pixels high**.
- Removes lane markings and other wasted detail that does not read well on short LED strips.
- Uses a much simpler side-view car silhouette with brighter motion cues so the traffic remains readable at low height.
- Replaces lane-count style controls with **Traffic rows** and **Road height** controls more suited to compact shader bands.

## v0.5.11 – Cars on Road shader side-view fix

- Reworks **Cars on Road** into a true **side-view** road scene instead of the earlier top-down style.
- Cars now move **left to right**, **right to left**, or **both directions** depending on the new **Direction** control.
- The shader now renders a clearer LED-friendly road scene with horizontal traffic, simple car silhouettes, wheels, windows, headlights, taillights and lane markings.
- Keeps the same built-in shader name so existing scenes can be switched over without re-importing assets.

## v0.5.10 – Cars on Road shader

- Adds a new built-in **Cars on Road** shader for backgrounds or shader layers.
- Shows a stylised road with moving traffic, lane markings, headlights and taillights so it reads well on LED matrix displays.
- Includes controls for **Speed**, **Lane count**, **Road width**, and the road / shoulder / marking / headlight / taillight colours.

## v0.5.9 – narrower Designer rail

- Narrows the Designer left rail from a maximum of 380 px to 330 px, returning more horizontal space to the preview and inspector.
- Keeps the compact eight-button Align row, two-column Snap controls, three-column template buttons and three-column Add Layer controls introduced in v0.5.8.
- Retains the v0.5.8 fix preventing the Templates toolbar from expanding vertically.

## v0.5.8 – compact Designer rail layout

- Fixes the large empty **Templates** block introduced by the v0.5.7 full-screen Designer workspace. The old horizontal toolbar `flex-basis` was being interpreted as vertical height inside the new left rail.
- Makes the left Designer rail slightly wider on desktop so Edit, Align and Snap tools wrap less.
- Keeps all eight Align buttons on one compact row.
- Keeps the three quick templates together and places **More templates…** beside **Apply** instead of wasting a full row.
- Lays out Add layer actions as a compact three-column grid.
- Leaves the single-column responsive layout unchanged on narrower screens.

## v0.5.7 – full-screen Message library and Designer

- **Messages now opens as a full-width library** instead of permanently reserving a narrow list beside the editor.
- Selecting a saved message or choosing **+ New message** opens a dedicated full-width Designer; **← Messages** returns to the library without resetting the current editor state.
- The freed left rail in the Designer now holds the **Edit / Align / Snap controls, Templates / Add layer controls, Layers, Zones and Components**, leaving the right side for the message name, preview, timeline/scene controls and selected-layer properties.
- The full-width library uses responsive message cards and now exposes **Import** alongside **+ New message**.
- Returning to the Messages tab from another section takes you to the library first, reducing accidental edits and making message discovery the natural starting point.

## v0.5.6 – Water Ripples shader

- Adds an original built-in **Water Ripples** shader designed for narrow P5/P10 water bands as well as larger shader layers.
- Three styles: **Gentle water**, **Ripples**, and **Pool shimmer**.
- Controls for speed, wave height, ripple size, choppiness, water/deep/highlight colours and opacity. The shader has a transparent area above its animated water surface, so a bottom strip can sit naturally over an existing scene background.
- Adds a **Water / swim** Designer template that places the effect across roughly the bottom third of a 32-pixel display and leaves the upper area for a headline.
- The shader is lightweight enough to run at native LED resolution on the intended Pi/FPP platform; it remains compatible with the existing Auto/½/¼ shader performance controls.

No database migration or privileged-helper change is required.

## v0.5.5 – Random character reveal

- Adds **Random character reveal** for text layers. Characters appear in their final positions in a stable random order over the layer's Effect period.

## v0.5.2 – action-bar alignment

- Aligns file-based Import controls with the other Message, Playlist, Component and configuration action buttons.
- Removes inherited form-label bottom margin/direction from file buttons; no functional or database changes.

## v0.5.1 – portability, history and Designer workflow

This release concentrates on moving/recovering creative work and making Designer faster to use:

- **Import / export** for individual messages, reusable components and playlists. Exports are portable ZIPs and include referenced images, fonts, source/processed video and uploaded shaders so the content can be moved to another Pi Matrix Signage installation without rebuilding it. Playlist export includes the messages used by that playlist.
- **Portable full configuration** export/import for application content and operational configuration: display settings, messages, components, playlists, timed schedules, conditional rules and brightness schedules, together with persistent media. For safety, named user accounts/password hashes and FPP itself remain the job of **Backup & restore**, not the portable configuration format. Importing a portable full configuration replaces the current creative/automation configuration after confirmation.
- **Message version history**. Every successful Save creates an immutable revision (unchanged repeat saves are ignored), up to the latest 60 revisions per message. History records who saved it and when; any earlier version can be restored, and that restore itself becomes a new revision so it can be reversed. Existing messages receive an upgrade-baseline revision automatically.
- **Cross-message layer clipboard**. Copy one or many Designer layers with `Ctrl/Cmd+C`, open another message and paste with `Ctrl/Cmd+V`. Dependent zones and group relationships are remapped safely. The clipboard persists in the browser so it survives message navigation/reloads.
- **Expanded keyboard shortcuts** including Save, Copy/Paste, Duplicate, Select All, Group/Ungroup, Undo/Redo, Delete, front/back ordering, preview play/pause and one/five-pixel nudging. A `?` shortcut opens an in-app shortcut reference.
- **P5 LED preview simulation** on both Dashboard and Designer. Switch between **Exact pixels**, **P5 LED dots** and **Smooth**. P5 mode calculates the logical LED pitch from the actual rendered preview size and masks each logical pixel into an individual round LED with a dark physical gap, providing a much closer browser approximation of a P5 matrix.

The database schema is v9. No privileged-helper change is required.

## v0.5.0 – operational automation and mobile remote

This release adds four day-to-day operational features without complicating Designer:

- **Conditional content rules** under Schedules. Rules can show a message or playlist based on live temperature, feels-like temperature, wind speed, wind gust, humidity, weather condition, or a value from a JSON/API endpoint. Rules have priority, an optional “must remain true for” delay, and a minimum on-screen hold to avoid rapid flicker around thresholds. Conditional rules compete with normal timed schedules by priority.
- **Emergency / Priority mode**. Configure one saved message under Schedules → Emergency mode. The Dashboard and mobile remote then get a one-button emergency override. Emergency mode outranks manual overrides, conditional rules, timed schedules and the default message, while still allowing the outgoing message's configured exit effect to finish first. Ending Emergency mode restores whichever automatic/manual content should currently be active.
- **Brightness schedules** under Schedules. Create day/time profiles such as daytime 70%, evening 40% and overnight 10%. Overnight windows are supported and overlapping profiles use priority. The normal Display setup brightness remains the fallback.
- **Mobile Remote** at `/remote`, linked from the top bar. It provides large touch controls for Emergency, previous/next saved message, Show Now, Return to Schedule, Blank Display and temporary 10/25/50/75/100% brightness. Selecting Auto brightness returns control to brightness schedules/default brightness. The remote uses the same named login/session and CSRF protection as the main app.

The database schema is v8. Existing messages, schedules, users and permissions are preserved. No privileged-helper migration is required.

## v0.4.18 – Reliable browser upgrade reconnect

The browser upgrader now uses the session-free `/health` endpoint as the authoritative post-restart check. As soon as the target version is online, the old page reports success and force-loads a fresh, cache-busted interface. Authenticated upgrade-status polling is supplemental only, so a service restart/session transition can no longer strand the browser on the old page. The root page and `/health` are explicitly non-cacheable.


The legacy **Editor mode** selector has been removed from the Messages screen. Pi Matrix Signage now uses **Designer – multiple layers** as the only visible message-authoring experience, which matches how the application is actually being used and removes the obsolete Quick editor from the workflow.

New messages open directly as a Designer scene. Existing older messages that were originally saved by the Quick editor remain compatible: when one is opened, its legacy text/background/logo/movement settings are converted into equivalent Designer layers automatically. Saving that message then stores it as a normal Designer message. The legacy renderer/data fields remain internally for backwards compatibility with old backups, but there is no Quick-editor UI anymore.

No database migration or privileged-helper change is required.

## v0.4.16 – shader backgrounds and heavy-shader performance

Shaders can be selected directly as a **Scene background** under **Scene appearance → Background style → Shader**. A background shader automatically fills the whole logical LED canvas and always renders behind the scene's text, images, video, widgets, icons and shapes. The same uploaded/built-in shader library and generated ISF parameter controls are available, together with render rate, time speed and a **Performance** selector. Colour 1 becomes the fallback colour while the asynchronous shader is compiling or wherever a shader returns transparency.

The old fixed 1.5-second shader timeout was removed. **Auto** performance gives a cold shader a longer first compile/render window and can fall back to **½ resolution** and then **¼ resolution** for heavy effects. Warm-frame deadlines adapt to measured render time instead of a single fixed timeout. Shader execution remains isolated from the main DDP renderer.

No database migration or privileged-helper change is required for v0.4.16.

## v0.4.15 – GPU/ISF shader layers

Designer now supports **Shader** layers for animated procedural graphics. Use **Add layer → Shader** and choose one of the built-in effects, or upload an ISF-style `.fs`, `.frag`, `.glsl`, or JSON shader export. Shader layers render at the layer's actual LED resolution and then pass through the normal Pi Matrix layer pipeline, so opacity, rotation, zones/hard clipping, grouping, components, entrance/exit effects and scene transitions continue to work.

The shader loader understands the common ISF generator conventions used by the supplied examples: `TIME`, `RENDERSIZE`, and metadata `INPUTS` including float, integer/long, boolean/event, point2D, colour and enumerated values. Parameter controls are generated automatically in Designer; colour inputs use the existing Preset/Custom colour picker. **Render rate** can be limited from 8–25fps and **Time speed** can be slowed, frozen at 0, accelerated or reversed.

Shader execution is deliberately separated from the main DDP renderer. An isolated persistent EGL/OpenGL helper produces frames asynchronously, while the LED loop keeps the most recently completed frame. A shader compile/runtime failure is surfaced in the Shader inspector rather than blocking the LED output. Live-panel rendering and browser timeline preview use separate shader caches, so scrubbing the Designer cannot alter the shader time being shown on the physical display.

Three original built-in effects are included: **LED Plasma**, **Aurora**, and **Pixel Waves**. Uploaded shader files are stored persistently and are therefore included by the existing Backup & restore feature. The release does **not** bundle third-party sample shaders; operators are responsible for the licence terms of shaders they upload. The currently supported target is generator-style fragment shaders; texture/audio/image-channel shaders may require future compatibility work.

For a full-display shader on the current 256×32 canvas, set the Shader layer to X=0, Y=0, W=256, H=32, then place text/logo layers above it. Shader layers can also be assigned to a Zone to create effects in only part of the display.

No database migration or privileged-helper change is required for v0.4.15. Falcon Player's Bookworm image already carries Mesa development/runtime dependencies; the manual installer additionally ensures EGL/OpenGL runtime libraries are present.


## v0.4.13 backup reliability fix

Backup creation no longer depends on sudo/systemd scheduling. **Create backup** runs asynchronously inside Pi Matrix Signage, while the privileged helper is reserved for restore operations. New backups always include a raw FPP configuration snapshot and also include FPP's supported full JSON export when that endpoint is healthy. If FPP's own export fails, the backup still completes with the raw snapshot and records the FPP error for diagnostics. Restore prefers the official FPP data and can fall back to the raw snapshot while respecting the keep-network and keep-mode options.

## Backup & Restore

v0.4.12 adds a dedicated **Backup & restore** tab with its own user permission. A full backup ZIP contains:

- the complete Pi Matrix Signage SQLite database (messages, scenes, playlists, schedules, components, users and permissions)
- all persistent Pi Matrix Signage uploads/media, including images, fonts, source videos and processed LED video frames
- session/application persistent data
- an **FPP full configuration backup** created using FPP's supported `backup.php` backup mechanism when available
- a raw FPP configuration/show-setup snapshot (`settings`, `config`, playlists, scripts, schedule, timezone and related files) as a disaster-recovery fallback

Backups can be created on the Pi, downloaded, deleted, restored from the saved list, or restored from an uploaded backup ZIP. Every restore first creates an automatic **pre-restore safety backup**. By default restore keeps the current Pi's FPP network settings and Player/Remote mode so the unit remains reachable; these options can be unticked when a full FPP network/mode restore is intentionally required.

Full backups may contain sensitive FPP information such as Wi-Fi/email credentials, so downloaded backup ZIPs should be stored securely. The backup does not contain the Raspberry Pi OS image or the FPP application binaries themselves; install FPP and Pi Matrix Signage first on replacement hardware, then restore the backup.

## v0.4.11 – wind-aware weather animation

Weather animation now uses live wind speed and direction: clouds drift continuously and wrap rather than reversing, stronger wind produces faster movement, rain slants with the wind, snow drifts/flutters, fog uses moving parallax bands, and thunder clouds drift independently of their lightning flashes. Calm conditions remain nearly still.

No database migration or privileged-helper change is required for 0.4.11.

## v0.4.10 – enhanced animated weather widget

The Weather live widget now has an **Animated weather panel** mode designed specifically for low-resolution LED matrices. Open-Meteo WMO weather codes automatically select a crisp built-in animation for clear sun, partly cloudy/sun, cloud, drizzle/rain/showers, snow/snow showers, fog and thunder. Clear conditions also distinguish day/night. The animation is drawn directly on the LED grid and does not require uploaded artwork.

Weather can now retrieve and display **temperature, feels-like temperature, wind speed, compass wind direction, gusts, relative humidity, precipitation, rain, showers, snowfall and cloud cover**. Celsius/Fahrenheit and mph/km/h are selectable. Animated panels let the operator independently show/hide the graphic, condition, feels-like, wind, gusts, humidity and precipitation. When several extra readings are enabled, **Cycle extra readings** rotates compact pairs on the second line so a 32-pixel-high sign remains readable.

The original **Text / template** weather mode remains available for existing layouts and now supports the extended tokens `{TEMP}`, `{TEMP_UNIT}`, `{FEELS}`, `{CONDITION}`, `{WIND}`, `{WIND_UNIT}`, `{WIND_DIR}`, `{WIND_DEG}`, `{GUST}`, `{HUMIDITY}`, `{PRECIP}`, `{RAIN}`, `{SHOWERS}`, `{SNOW}`, `{CLOUD}` and `{CODE}`. Existing saved weather widgets remain in text mode until changed, while newly created Weather widgets/templates default to the animated panel.

No database migration or privileged-helper change is required for 0.4.10.

## v0.4.9 – template library and built-in animated LED icons

This release expands Designer with a grouped template library and a new self-contained **Icon** layer type. Built-in pictograms are rendered directly on the LED pixel grid, so no image uploads or icon fonts are required.

### Template library

The existing Headline, Ticker and Notice shortcuts remain on the Designer toolbar. **More templates…** adds ready-to-edit scenes for:

- Welcome, opening hours, information, queue / please wait, thank-you and contact/staff assistance.
- Left/right/up/down directions, parking, Wi-Fi and accessibility.
- Sale, price, event, birthday and Christmas.
- Emergency warning.
- Digital clock/date, analogue clock, countdown and weather + clock.
- Two-zone split-screen layout.

Templates are ordinary Designer scenes after insertion: every layer, colour, timing, zone and effect can be edited normally.

### Built-in LED icons

Use **Add layer → Icon** for crisp built-in pictograms including directional arrows, walking/queue, information, warning, wheelchair, toilets, parking, Wi-Fi, telephone, tick, cross, heart, smile, bell, star, gift, snowflake and sale tag.

Icon layers support the normal layer animations/entrance/exit effects plus an independent icon effect: **Native animation, Flash, Pulse, Spin, Wiggle, or Arrow chase**. Native animation gives suitable movement to walking, Wi-Fi, bell and heart icons. Primary and secondary colours use the same Preset/Custom colour picker as the rest of Designer.

No database migration is required for 0.4.9. Existing scenes are unchanged.

## v0.4.8 – system diagnostics and automatic recovery

Display Setup now includes a live **System diagnostics & recovery** panel covering Pi CPU/load/temperature, RAM, storage, uptime and IP addresses; renderer FPS/frame timing/dropped frames/restarts; FPPD service state; DDP listener state; internet/DNS availability; and live-widget fetch health. Recovery actions are recorded in a persistent history.

Automatic recovery is conservative and configurable. The in-process LED renderer is restarted if it stops making frame progress, FPPD can be restarted if `fppd.service` is genuinely inactive on consecutive checks, and the systemd unit now uses `Restart=always` so the web/signage process is restored after an unexpected exit. The watchdog deliberately **never reboots or powers off the Raspberry Pi automatically**. High temperature, low storage, missing DDP input and network/widget problems are surfaced as warnings/errors rather than causing unsafe automatic actions. Manual **Restart renderer now** and **Restart FPPD now** controls are also provided to users with Display setup permission.

The recovery defaults are enabled, with a 5-second renderer stall threshold and 60-second recovery cooldown. They can be changed from Display Setup.

## v0.4.7 – reliable browser upgrade reconnect

The Upgrade page no longer treats the expected service restart as an installation failure. If the upload request is interrupted because Pi Matrix Signage restarts before the old web process can flush its final response, the browser switches to **Restarting / verifying** state, polls the returning service, reads the persisted upgrade status, confirms the newly installed version, then reloads automatically. Genuine HTTP validation, permission and package errors still report as failures.

The privileged upgrade worker now gives the accepting HTTP request additional time to finish before stopping the service, and `/health` reports the application version for diagnostics. No database changes are required.

**When installing 0.4.7 from 0.4.6, the old page can still show the old false error once because its JavaScript is 0.4.6 until the upgrade has completed. Refresh once after about 10 seconds if that happens. Subsequent upgrades use the corrected behaviour.**


## v0.4.6 – named users and tab permissions

Pi Matrix Signage now uses named user accounts and signed browser sessions instead of the old single shared Web password. **Dashboard is always available** to every enabled account. Administrators can separately grant **Messages, Playlists, Schedules, Display setup, Upgrade and Users** rights. Permissions are enforced by the server API as well as by hiding inaccessible tabs.

On the first start after upgrading to 0.4.6, sign in with **username `admin` / password `pimatrix`**. The application immediately requires that default password to be changed. The initial Administrator account has full rights. New users can be Dashboard-only or receive any combination of tab permissions. Users can be disabled without deleting them, passwords can be reset, and at least one enabled account must retain Users permission.

The top bar now shows the signed-in user, provides **Password** and **Sign out** controls, and the old Web password fields have been removed from Display setup. Pi shutdown requires Display setup permission; software installation requires Upgrade permission.


## v0.4.5 – Custom colour picker fix

- Custom colour mode now has a large explicit **Choose custom colour…** button.
- Uses the browser/system colour picker via `showPicker()` where available, with a click fallback.
- Hex and RGB entry are always available as reliable alternatives.
- Preset colours remain unchanged.

## v0.4.4 – Preset + custom colour picker

Every colour field now opens a two-mode picker. **Preset colours** contains the five colours sampled from the supplied Fledglings logo (orange `#B84921`, pink `#E1B2C2`, green `#B5D889`, blue `#91CAD6`, deep teal `#003748`). **Custom colour** retains the normal full colour picker and also accepts an exact hex value. The last-used mode is remembered in the browser. The preset system is deliberately generic so the palette can be changed/expanded in a later release without changing the editor model.


## v0.4.3 – cleaner Messages / Designer workspace

The Messages screen has been reorganised to make the increasingly capable Designer much easier to use without removing existing controls. Saved messages now have a search box and a narrower, cleaner sidebar. The editor header, preview and Designer toolbars use less vertical space.

Designer now uses a clearer inspector hierarchy: layer content appears first, followed by **Layout & position**, **Motion & animation**, and **Entrance & exit**. Scene Appearance, Scene Timing, Timeline, Zones, Components, Animation, Entrance/Exit and Custom Fonts are collapsible, and the browser remembers which panels you prefer open. Zones and Components no longer permanently occupy the layer sidebar.

Widget controls are context-sensitive: the analogue clock no longer shows irrelevant text-style, format or remote-refresh controls, while weather/JSON/RSS retain their data refresh controls. The Timeline remains fully functional but is collapsed until needed. The layer panel stays available while scrolling on wide desktop displays.


## v0.4.2 – live weather/widget preview reliability

Designer now refreshes live widget layers even when **Animate preview** is off. This fixes the weather widget appearing to remain on **Loading…** after the asynchronous weather request has already completed. Digital/analogue clocks, countdowns, JSON and RSS widgets also stay live in a static Designer preview.

Live-data requests now have a render-thread watchdog. If DNS/network access stalls beyond the request limit, the placeholder changes to **Weather unavailable** / **Data unavailable** rather than remaining on Loading indefinitely; late responses from an expired request are safely ignored.


A browser-operated LED matrix signage controller for a Raspberry Pi 4 fitted with the **Hanson Electronics rPI-MFC** and HUB75 LED panels such as P5/P10 panels.

Pi Matrix Signage renders the RGB canvas and streams it locally to Falcon Player (FPP) by DDP. FPP remains responsible for the timing-critical rPI-MFC/HUB75 output.

## What's new in 0.4.1

### Video upload progress

Large video uploads now show a real staged progress display in Designer. The browser reports the actual network upload percentage and transferred MB, then the Pi switches to background FFmpeg preprocessing with conversion progress while LED-sized frames are created. The stages are **Uploading → Processing video → Creating LED frames → Finalising → Complete**. The web interface stays responsive and the physical display continues running throughout.


Version 0.4.1 concentrates on making Designer feel like a real signage/layout application while keeping the physical panel output unchanged.

### Timeline and message transitions

The existing scene timeline is expanded with a dedicated **SCENE** lane so whole-message entrance and exit transitions are visible alongside individual layer timing.

- Click the timeline to move the playhead.
- Drag layer bars to change their start time.
- Resize the end of a layer bar to set its exit point.
- Grouped/multi-selected layers can be moved together on the timeline.
- The scene lane visualises the complete message entrance and exit transition windows.
- Existing fade, crossfade, wipe, push, dissolve, pixel-scatter, blinds, checkerboard, zoom and roll transitions are retained.
- When a message change is requested, the outgoing exit effect still takes precedence before the next message starts.

### Multi-select and grouping

Designer now supports real multi-selection.

- Shift-click, Ctrl-click or Cmd-click layers to add/remove them from the selection.
- Drag selected layers together on the canvas.
- Arrow keys move all selected layers (Shift = 5 pixels).
- **Group** makes several selected layers behave as one selection.
- **Ungroup** separates them again.
- Duplicate and delete work on the whole selection.

### Snap, alignment and distribution

Designer has a new layout command bar.

- Snap to 1, 2, 4 or 8 pixel grid.
- Optional object snapping to the canvas, other layer edges/centres and zone edges/centres.
- Align left, centre, right, top, middle or bottom.
- Distribute three or more selected items horizontally or vertically.
- A single selected item aligns against the entire LED canvas; multiple selected items align within their collective bounds.

### Undo and redo

Designer now has multi-step undo/redo, including keyboard shortcuts:

- Ctrl/Cmd + Z = Undo
- Ctrl/Cmd + Shift + Z = Redo
- Ctrl/Cmd + Y = Redo

Geometry, layer settings, zones, grouping and other Designer edits participate in the history stack.

### Expanded LED font library

The hard-edged LED choices are now treated as proper LED faces rather than merely normal computer fonts with smoothing disabled.

Built-in choices include:

- LED 3×5
- LED 4×6
- LED 5×7
- LED 6×8
- LED 7×9
- LED 8×8
- LED 8×12
- LED 8×16
- LED condensed
- LED bold
- LED digital
- LED scoreboard
- LED dot matrix

The compact faces use dedicated small bitmap glyphs and the digital/scoreboard faces use seven-segment-style numerals. Rendering stays on integer LED pixels without anti-aliased half-lit edges. **Pixel sharp** remains available for uploaded/installed TTF/OTF fonts.

### Reusable zones

A message can contain named zones such as **Logo**, **Ticker**, **Clock** or **Main message**.

Each zone has exact X/Y/W/H geometry. Layers can be assigned to a zone and are then **hard-clipped by the renderer** to that zone during static display, scrolling, bouncing, rotation and entrance/exit effects. Zones therefore prevent one animated area overwriting another.

The Designer shows zone guides and allows layer selection to be assigned/cleared from a zone.

### Reusable components

Any selected set of layers can be saved into the persistent **Components** library and inserted into other messages.

Typical components might be:

- company logo + clock
- footer ticker
- opening-hours block
- price panel
- warning badge
- standard header

The component stores the selected layers plus any zones used by those layers. On insertion, IDs and zones are remapped safely and the inserted layers arrive as a group. Components are reusable **templates/copies**: an already-inserted copy is intentionally not live-linked to later changes to the library component.

### Analogue clock widget

Widget layers now include a true graphical **Analogue clock** suitable for small P5 matrices.

Controls include:

- ring colour
- tick colour
- hour-hand colour
- minute-hand colour
- second-hand colour
- face colour
- show/hide second hand
- filled/transparent face

The hands use the Pi's current local time and are rendered directly as crisp integer-pixel graphics.

### Smoother Dashboard live display

The Dashboard preview no longer depends on the slower status refresh cycle.

- Independent live-preview loop.
- Choose 4, 8 or 12 preview frames per second.
- Prevents overlapping preview requests.
- Preloads the next image and swaps it atomically to reduce visible jerking/flicker.
- Automatically pauses browser preview work while the Dashboard tab/page is hidden.
- **Live Display ON/OFF** switch is remembered by the browser.

Turning Live Display off affects **only the browser preview**. The physical LED panels and DDP output continue to run normally.

## Other major features retained

- Quick editor plus multi-layer Designer
- Text, image, animated image, video, widget and shape layers
- GIF/WebP/APNG playback
- Video preprocessing through FFmpeg
- Digital clock/date/countdown/weather/JSON/RSS widgets
- Rich text effects, auto-marquee, typewriter, palettes, gradients, glow and crisp shadows/outlines
- Layer entrance/exit effects and full scene transitions
- Hard layer clipping for scrolling/bouncing
- Saved messages, playlists, schedules, priorities and manual overrides
- Dynamic text tokens such as `{TIME}`, `{DATE}` and `{DATETIME}`
- Browser Upgrade tab with backup, health-check and automatic rollback
- Safe permission-protected **Shut down Pi** control
- Panel tests, orientation, brightness, colour order and DDP configuration
- SQLite persistent storage and systemd startup at boot

## Upgrade from 0.4.5

If 0.4.5 is already running, **v0.4.6 can be installed directly from the Upgrade tab**.

1. Open **Upgrade**.
2. Drop `PiMatrixSignage-v0.4.6.zip` onto the upgrade area.
3. Let the updater validate, back up, install, restart and health-check the service.
4. When it reconnects, the new sign-in page appears. Use `admin` / `pimatrix`, then choose a new password when prompted.

The existing database, messages, playlists, schedules, images, videos, fonts and settings are preserved. The database migration adds the Users table; future upgrades preserve the users and their permissions.

Manual SSH installation remains available:

```bash
cd /home/fpp/media/upload
unzip -o PiMatrixSignage-v0.4.6.zip
cd PiMatrixSignage
sudo ./install.sh
```

## Recommended platform

Typical architecture:

```text
Phone / PC browser
        |
        | HTTP :8090
        v
Pi Matrix Signage (Flask + Pillow + SQLite)
        |
        | RGB888 DDP, UDP 4048
        v
Falcon Player (FPP)
        |
        | HUB75 timing/GPIO
        v
Hanson rPI-MFC  --->  P5/P10 panels
```

Application code:

```text
/home/fpp/media/pi-matrix-signage
```

Persistent database/media/upgrades:

```text
/home/fpp/media/pi-matrix-signage-data
```

Useful service commands:

```bash
sudo systemctl status pi-matrix-signage
sudo systemctl restart pi-matrix-signage
sudo journalctl -u pi-matrix-signage -n 100 --no-pager
```

## Hardware warning

The rPI-MFC panel data connection does not replace proper panel power distribution. Use a PSU, wiring and fusing suitable for your panels and follow the current Hanson rPI-MFC power guidance.

See [INSTALL.md](INSTALL.md) for installation, upgrade and usage notes.

## GPIO / physical controls

On a Hanson rPi-MFC, Pi Matrix Signage can monitor the three dedicated user-input connectors directly using libgpiod: Input A (CN2/GPIO6/header pin 31), B (CN3/GPIO13/header pin 33), and C (CN4/GPIO26/header pin 37). Configure them under **Display setup → GPIO / physical controls** for Emergency, End Emergency, Next/Previous message, Blank, Return to Auto, or brightness cycling. Inputs default to pull-up operation with voltage-free switch/relay contacts to ground. Emergency can latch until cleared or remain active only while the physical input is active.


### v0.5.4
- Fixed persistent Message Version History UI refresh: opening the panel directly, changing messages, saving, and restoring now always reload the correct revision list. Stale async results from a previously selected message are ignored.
