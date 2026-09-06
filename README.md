# Brady M211 for Home Assistant

Custom integration that prints to a [Brady M211](https://www.bradyid.com/) label maker over Bluetooth Low Energy, including through **ESPHome Bluetooth proxies**.

This is a Home Assistant **integration**, not an add-on. ESPHome Bluetooth proxies only expose GATT to Home Assistant Core, so an add-on container cannot use them.

## Install with HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JonBons&repository=hacs-brady&category=integration)

1. HACS → Integrations → ⋮ → Custom repositories
2. URL: `https://github.com/JonBons/hacs-brady`
3. Category: **Integration**
4. Download **Brady M211**, then restart Home Assistant
5. Settings → Devices & services → Add integration → **Brady M211**

Requires Home Assistant 2024.12+ and the built-in **Bluetooth** integration.

Manual install: copy `custom_components/brady_m211` into `/config/custom_components/brady_m211` and restart.

## ESPHome Bluetooth proxy

Active GATT is required. Passive scan-only proxies cannot print.

```yaml
esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: esp-idf

esp32_ble_tracker:
  scan_parameters:
    active: true

bluetooth_proxy:
  active: true
```

The M211 is a **single-owner** printer. By default the integration connects only when polling or printing, then releases ownership so the Brady phone app can still connect. Enable **Stay connected** only if you want live sensors and can spare a proxy connection slot.

If setup fails because another device owns the printer, hold the M211 power button for 5 seconds until the Bluetooth LED pulses.

## Entities and services

| Entity | Purpose |
|--------|---------|
| Sensors | Battery, media remaining, firmware, printable size, last job |
| Binary sensors | Connected, media out, errors, charging |
| Buttons | Feed, cut, refresh |
| `notify.*_print_label` | Print the notification message as a label |

Services (Developer tools → Actions):

- `brady_m211.print_text` — `device_id`, `message`, optional `copies`, `length_in`
- `brady_m211.print_image` — `device_id` plus `filename` (under `/config`) or `camera_entity_id`

Example:

```yaml
action: notify.m211_xxxx_print_label
data:
  message: "Rack 7  Port 24"
```

## Limitations

- First prints should be verified on hardware. Raster bit polarity and VGL framing were reconstructed from Brady’s app/SDK, not yet captured from a live M211.
- Output is 203 dpi monochrome only. The printer never receives fonts or `.BWS` files.
- Do not pair the printer in the phone/OS Bluetooth settings. Only this integration or the Brady app should own the GATT session.

## HACS publishing notes

Repository: [JonBons/hacs-brady](https://github.com/JonBons/hacs-brady)

1. Set a short GitHub **description** and **topics** (`home-assistant`, `hacs`, `hacs-integration`, `bluetooth`, `brady`, `m211`).
2. Keep **Issues** enabled.
3. Confirm `.github/workflows/validate.yml` is green (HACS action, hassfest, tests).
4. Publish a **GitHub Release** (not just a tag). HACS uses the release tag as the version.
5. Users can add it as a **custom repository** immediately. Default-store inclusion is a later PR to [hacs/default](https://github.com/hacs/default) and is not required to use the integration.
