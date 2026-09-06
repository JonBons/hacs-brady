# Brady M211 Bluetooth Protocol

Wire-level notes for talking to a Brady M211 over BLE so a local web service or Home Assistant integration can print labels.

This is an interoperability spec reconstructed from:

- Brady Express Labels 3.3.0 Android APK in this workspace (`com.bradycorp.expresslabels`)
- Brady Web SDK 3.2.2 (`@bradycorporation/brady-web-sdk`, published GATT client)
- Cross-check against [pybrady](https://gitlab.com/ggiesen/pybrady) `docs/brady_specification.md` (same Android app, v3.1.0 assemblies)

Observed facts vs inferences are marked. Do not redistribute Brady binaries, fonts, `.BWS` templates, or decompiled assemblies.

---

## 1. What this printer actually is

The M211 is **BLE-only**. USB-C is charging. There is no Windows driver, no TCP port, and no Bluetooth Classic SPP. Pairing is not done in the OS Bluetooth settings; the host app owns a GATT session.

| Item | Value |
|------|--------|
| Radio | Bluetooth Low Energy 5.0 (manual); app requires BLE 4.2+ |
| Print language | VGL/STX variant 6 (“Apollo”) |
| Status/control | Compact PICL JSON over GATT |
| Resolution | 203 × 203 dpi |
| Max tape width | 0.75 in (printable ~0.63 in) |
| Header / trailer | 0.435 in each |
| Cut | End-of-label only |
| Media | M21-series cartridges with an ID chip |
| Ownership | Single host. Hold power 5 s to release. |

Internal Brady names seen in the app: **Edison** (mobile app), **Apollo** (BLE chipset), **PICL** (property protocol), **VGL** (print stream).

The host always renders a 1-bit bitmap and sends raster. The printer does not accept text, fonts, or a design file over BLE.

---

## 2. Where the protocol lives in Express Labels 3.3.0

This APK is a **.NET MAUI** app. Java/smali is only Android bindings. Protocol code is in managed DLLs:

| Assembly | Role |
|----------|------|
| `PE.Ble.dll` | BLE discovery, GATT session, Apollo characteristics (`PE.Ble.Droid.BleDiscoveryProvider`, `BleDeviceConnection`) |
| `PE.Printing.dll` | VGL generators (`VglRlePrintDataGenerator5` / `6`) |
| `PE.PrinterServices.dll` | Classic BT / Wi-Fi printer services (not used by M211) |
| `EdisonMobile.Full.dll` | Printer model DB / parts |

Those DLLs ship inside `lib/armeabi-v7a/libassemblies.armeabi-v7a.blob.so` (XABA + XALZ). **This workspace APK is the base split only** — it has no `lib/` directory. To re-extract 3.3.0 assemblies you need the ABI split (`config.armeabi_v7a.apk` / `config.arm64_v8a.apk`) or a universal/XAPK.

Bindings still present in 3.3.0 smali confirm the same package names as 3.1.0:

- `PE.Ble.Droid.BleDiscoveryProvider+BleScanCallback`
- `PE.Ble.Droid.BleDeviceConnection+BluetoothBroadcastReceiver`
- `PE.PrinterServices.Droid.BluetoothPrinterServices`

Brady Web SDK 3.2.2 independently hard-codes the same Apollo GATT UUIDs, so the 3.3.0 on-wire protocol has not moved.

---

## 3. BLE discovery

Scan filter: advertised service UUID

```
0000fd1c-0000-1000-8000-00805f9b34fb
```

The Web SDK additionally filters `requestDevice` by **name prefix**. M211 devices advertise a name containing `M211`.

Web Bluetooth filters use `optionalServices: ["0000fd1c-0000-1000-8000-00805f9b34fb", "generic_access"]`. If the advertised name is missing, the client reads Generic Access device name (characteristic `0x2A00`) and maps prefixes such as `S370` → S3700.

Model routing (from device name substring):

| Name contains | Print payload | Session ownership write |
|---------------|---------------|-------------------------|
| `M211` | VGL/STX v6 | Required |
| `M511` | VGL/STX v6 | Not required |
| `M610` | ESC/BMP | Required |
| `M611`, `S3700`, `i7500`, `i4311` | JSON/PICL | Not required |

M211 is the only model this document implements.

---

## 4. Apollo GATT map

Primary service `0000fd1c-0000-1000-8000-00805f9b34fb`:

| Characteristic | UUID | Host use |
|----------------|------|----------|
| Session ID | `fc0018d8-cf12-46be-87b1-cce29b1e6c34` | Write ownership GUID |
| Print Job | `7d9d9a4d-b530-4d13-8d61-e0ff445add19` | Write VGL6 job bytes |
| PICL Request | `a61ae408-3273-420c-a9db-0669f4f23b69` | Write Compact PICL packets |
| PICL Response | `786af345-1b68-c594-c643-e2867da117e3` | Indicate / notify JSON replies |
| CCCD | `00002902-0000-1000-8000-00805f9b34fb` | Enable indications/notifications |

Confirmed in Web SDK class fields `APOLLO_SERVICE_*` and in pybrady §2.3.

---

## 5. Connection sequence (M211)

```
1. Scan for service 0000fd1c-... or name prefix "M211"
2. Connect GATT (LE, autoConnect=false)
3. Discover Apollo service + four characteristics
4. Enable PICL Response:
     Android app: CCCD = 0x02 0x00 (indication)
     Web SDK:     startNotifications() (notification)
5. Request MTU 517 if the stack allows it (Android). Browsers cannot.
     Usable minimum ~50. Payload per chunk = MTU - 8 on Android.
6. Write Session ID (17 bytes). See §6.
7. Subscribe to Compact PICL properties on PICL Request. See §8.
8. Wait for PropertyGetResponses (media size, battery, errors).
9. Print: chunk VGL6 bytes onto Print Job. See §7 and §9.
10. Watch PrintJobIdAndStatus (0029) for "Successful" / "Failed".
```

If the write to Session ID fails with GATT status 19 (Android) or DOMException code 9 (Web Bluetooth), another client owns the printer. Hold the M211 power button 5 seconds until the Bluetooth LED pulses.

---

## 6. Session ownership

M211 (and M610 / MM100BT) require a 17-byte write:

```
[16-byte GUID in .NET Guid byte order] [1 flag byte]
```

.NET `Guid` on the wire is **not** RFC 4122 big-endian. The first three groups are little-endian:

| String form | Bytes |
|-------------|--------|
| `aabbccdd-eeff-gghh-iijj-kkllmmnnoopp` | `dd cc bb aa ff ee hh gg ii jj kk ll mm nn oo pp` |

The Web SDK encodes it exactly that way, then appends `0x00`.

Flag byte:

| Source | First connect | Reconnect | Disconnect |
|--------|---------------|-----------|------------|
| Express Labels (pybrady) | `0x01` | `0x00` | (GATT disconnect) |
| Web SDK 3.2.2 | always `0x00` | always `0x00` | 36 zero bytes written to Session ID, then disconnect |

Save the GUID string (Web SDK calls this `ownershipID` / `localStorage`). Reuse it on later connections while the printer LED is solid.

**Inference:** `0x01` means “claim”; `0x00` means “I am the existing owner.” If you generate a new GUID every time while the LED is solid, the write will fail.

---

## 7. GATT write chunking

Every write to Print Job or PICL Request is a 3-byte header plus payload:

```
[flags: u8] [seq: u16 LE] [payload]
```

| flags | Meaning |
|-------|---------|
| 1 | Continuation; more chunks follow |
| 2 | Flush staged data (checkpoint) |
| 3 | Last chunk of this message |

Sequence starts at 0 and increments per chunk.

**Android app (pybrady):**

- Chunk payload size = `MTU - 8`
- First, flush, and last chunks: write-with-response
- Other chunks: write-without-response
- Flush every 16 chunks **or** every 4096 bytes of payload (M211 uses the 4096-byte rule)
- 10 ms pause after flush
- Retry up to 10× / 100 ms; GATT status 17 → 5 s backoff and rewind to last flush

**Web SDK 3.2.2:**

- Fixed payload size **148** bytes (browsers do not expose MTU)
- Always `characteristic.writeValue()` (with response)
- M211 flush when bytes since last flush ≥ 4096
- Other models flush every 16 chunks
- Last chunk always flag 3

For a Python/`bleak` client, prefer the Android rule: negotiate MTU, chunk `mtu-8`, mix write types, flush at 4096 bytes on M211.

---

## 8. Compact PICL (status and buttons)

Not the GUID-property PICL used by M611-class printers. M211 packets are:

```
[16-byte Compact PICL GUID] [u32 LE JSON length] [UTF-8 JSON]
```

GUID bytes (confirmed Web SDK `buildJsonPiclPacketFromString`):

```
96 C2 F7 4A 1D 21 42 32 86 78 20 EF E9 7B C2 D3
```

Then wrap that whole packet in the §7 chunk header when writing to **PICL Request**.

### 8.1 Subscribe (after connect)

```json
{"PropertySubscribeRequests":[
  {"ID":"0006"},{"ID":"0005"},{"ID":"000A"},{"ID":"001C"},
  {"ID":"0021"},{"ID":"0027"},{"ID":"0025"},{"ID":"0009"},
  {"ID":"0029"},{"ID":"0001"},{"ID":"0024"},{"ID":"0026"},
  {"ID":"000C"},{"ID":"000D"},{"ID":"000E"},{"ID":"000F"},
  {"ID":"0012"},{"ID":"0013"},{"ID":"0014"},{"ID":"0015"},
  {"ID":"002A"},{"ID":"0016"},{"ID":"001F"},{"ID":"0020"}
]}
```

Express Labels also subscribes `009D` (knockoff/counterfeit count). The Web SDK omits it. Both work.

IDs are **4-character hex strings**, not integers.

### 8.2 Notifications

PICL Response indicates packets. Compact replies look like:

```json
{"PropertyGetResponses":[
  {"ID":"000C","Value":"50","Status":"Successful"}
]}
```

The Web SDK unpacker is tolerant of a binary prefix: it splits the decoded buffer on `":["` and rebuilds `{"PropertyGetResponses":[...]}`.

### 8.3 Set commands

```json
{"PropertySetRequests":[{"ID":"0004","Value":"True"}]}
```

| ID | Name | Use |
|----|------|-----|
| 0004 | CutButton | Cut (M211 / M511) |
| 0007 | FeedButton | Feed one blank label |
| 0025 | SubstrateOutError | Write `"False"` to clear |
| 0026 | ShutdownTimeoutInMins | Auto-off minutes |

### 8.4 Property map (M211-relevant)

| ID | Type | Meaning |
|----|------|---------|
| 0001 | string | Battery charge |
| 0005 | bool | Cutter error |
| 0006 | bool | Fatal error |
| 0009 | bool | Print job error |
| 000A | bool | Media invalid |
| 000C | int | Printable width, dots |
| 000D | int | Left liner offset, dots |
| 000E | int | Printable height, dots (`0` = continuous) |
| 000F | int | Vertical offset, dots |
| 0012 | int | Black-mark / striped liner |
| 0013 | bool | Die-cut |
| 0014 | bool | Permasleeve |
| 0015 | bool | Self-laminating |
| 0016 | int | Media remaining % |
| 001C | bool | Media nearly out |
| 001F | bool | Job printing complete |
| 0020 | string | Firmware version |
| 0021 | bool | Low battery |
| 0024 | bool | AC connected |
| 0025 | bool | Media out |
| 0026 | int | Shutdown timeout (minutes) |
| 0027 | bool | Dismissible error |
| 0029 | string | `"<jobId>: Successful"` or `"<jobId>: Failed"` |
| 002A | int | Cartridge unique ID (chip) |

Use `000C`/`000D`/`000E`/`000F` at runtime to size the bitmap. Do not hard-code a tape size except as a fallback.

`002A` maps through Brady’s Apollo chip table to a Y-number / SKU. The Web SDK embeds that table (`ApolloMapping`). For printing you only need the printable rectangle from 000C–000F.

---

## 9. VGL/STX v6 print job

Written to **Print Job**, chunked per §7. Raster-only.

### 9.1 Outer frame (variant 6)

```
u32 LE  total_page_count          // once at start of the job
u32 LE  total_payload_size        // size of everything after this field; backfilled
u32 LE  job_name_offset           // offset of the job-name command inside the payload; backfilled
... VGL STX command stream ...
```

Generators write zeros for the two size/offset fields, emit commands, then patch them.

### 9.2 Command bytes

Numbers are ASCII decimal, optionally sign-prefixed, zero-padded (`0150`, `+00`, `+01`).

| Command | Bytes |
|---------|--------|
| Job name | `02 4B 00 0A` + ASCII + `0D` |
| Job name end | `02 4B 00 0B` |
| Part name | `02 4B 00 09` + ASCII (max 10) + `0D` |
| Page size | `02 4B 00 0C` + 4-digit W + 4-digit H |
| Printable size | `02 4B 00 0D` + 4-digit W + 4-digit H |
| Printable offset | `02 4B 00 0E` + 4-digit X + 4-digit Y |
| STXp / o / O / b | `02 70` / `6F` / `4F` / `62` + signed 3-byte (`+00`) |
| STXA / Q / a / G | `02 41` / `51` / `61` / `47` |
| Image start | `02 49 42 55 6C 62 6C` (`IBUlbl`) + page# ASCII + `0D` |
| Image end | `FF FF 0D` |
| Cut mode | `02 4D` + `00` EndOfJob, `01` EndOfLabel, `02` Never. M211: EndOfLabel only |
| Trailing whitespace | `02 57 01` |
| Document count | `02 44` + signed ASCII |
| Copy count | `02 43` + signed ASCII |
| Collate | `02 63` + `00`/`01` |
| X cursor | `58` + u16 LE |
| Y cursor | `59` + u16 LE |
| Raw row | `80` + u8 bytecount + packed bits |
| RLE row | `81` + u8 bytecount + RLE bytes |
| Repeat previous row | `00 00 FF` + u8 count (max 255) |

### 9.3 Page skeleton

```
STXa
STXp +00
STXo +00
STXO +00
STXb +00
STXA
STXa
STXQ
PageSize / PrintableArea / Offset / PartName
STXa
StxM 01          # EndOfLabel on M211
StxW 01
StxD +01
StxC +<copies>
JobName / JobNameEnd
STXa
STXa
STXI IBUlbl<page>
XCURS 0
YCURS 0
<raster rows>
STXI terminator
STXA
STXG
```

### 9.4 Raster

- 1 bit per pixel, MSB first (confirm on hardware; treat a printed black pixel as 1 in RLE colour bit).
- Width padded to a whole number of bytes.
- Prefer RLE when it is smaller than raw; otherwise `SendDotRow`.
- Identical consecutive rows → `SendLineRepeat` (count is extra copies, max 255).

**RLE byte:**

- bit 7 = colour (`1` black, `0` white)
- bits 6–0 = run length minus 1 (1…128 pixels)

Split runs longer than 128.

Bitmap geometry: **203 dpi**. Height `0` from PICL means continuous tape — you choose length (min 1.0 in, max 36 in mono). Always include the 0.435 in header/trailer in the page height the printer expects, or the image will sit in the wrong place. Prefer the live PICL printable rectangle over the catalog.

---

## 10. Minimal print recipe

1. Connect and take ownership (§5–6).
2. Subscribe; read `000C`–`000F`.
3. Render a 1-bit image sized to printable width × desired length (dots).
4. Build one VGL6 page (§9) with cut mode EndOfLabel, copies = 1.
5. Chunk onto Print Job (§7).
6. Wait for `0029` (`<id>: Successful`) or timeout (~60 s in the Web SDK).
7. Optional: `0007` feed, `0004` cut.

Until the VGL encoder is proven on hardware, the **fastest working print path** is Brady’s own Web SDK `printBitmap(img)` — it already performs steps 3–6. A Home Assistant backend cannot call that (no Web Bluetooth on the server). See §12.

---

## 11. Observed requirements (M211)

**OBS-BLE-001**: WHEN a host scans for Brady Apollo printers, THE scanner SHALL filter on service UUID `0000fd1c-0000-1000-8000-00805f9b34fb`.

**OBS-BLE-002**: WHEN the advertised name contains `M211`, THE host SHALL treat the device as VGL/STX v6 with Compact PICL and a required session-ownership write.

**OBS-OWN-001**: WHEN the Bluetooth LED is pulsing, THE host SHALL write a new 16-byte GUID plus flag to Session ID. WHEN the LED is solid, THE host SHALL reuse the previous GUID.

**OBS-OWN-002**: IF Session ID write fails (Android GATT 19 / Web Bluetooth code 9), THE host SHALL tell the user to hold power 5 seconds.

**OBS-PICL-001**: THE host SHALL subscribe to Compact PICL property IDs as 4-character hex strings and SHALL parse `PropertyGetResponses`.

**OBS-PRINT-001**: THE host SHALL send print payloads only on characteristic `7d9d9a4d-b530-4d13-8d61-e0ff445add19`, chunked with the 3-byte flag/seq header.

**OBS-PRINT-002**: THE host SHALL size raster to PICL printable width/height in dots at 203 dpi, not to the physical cartridge width.

**OBS-MEDIA-001**: IF `000A` or `0005`/`0006`/`0025` is true, THE host SHALL refuse or abort the job and surface the error.

---

## 12. Home Assistant / web server architecture

Web Bluetooth **only runs in a user-gesture browser tab** (Chrome, Edge, Bluefy on iOS). Home Assistant Core, a Python web server, and Safari cannot be the GATT client.

| Approach | Prints from HA automations | Designs labels | Notes |
|----------|----------------------------|----------------|-------|
| **A. Official Web SDK in a companion page** | No (needs a phone/PC browser next to the printer) | Bitmap only (`printBitmap`) | Least protocol work. Good for a “print this PNG” PWA. |
| **B. Python GATT client (`bleak`) as an HA add-on** | Yes, if the HA host (or a Bluetooth proxy machine) is in range | You render bitmaps (Pillow / SVG / template) | Correct long-term architecture for automations. |
| **C. Brady commercial SDK** | Depends on platform | Bitmap | [sdk.bradyid.com](https://sdk.bradyid.com) — Android / iOS / Web. Still BLE underneath. |
| **D. ESPHome BLE proxy** | Not by itself | — | Proxying GATT writes of this shape is painful; use a Python add-on on a Pi instead. |

Recommended split:

```
HA automations / dashboard
        │ REST or MQTT
        ▼
brady-m211 service  (Python, bleak, on a Bluetooth-capable host)
        │ Apollo GATT
        ▼
M211 printer
```

API sketch for that service:

```
POST /print          body: { "png_base64": "...", "copies": 1 }
POST /feed
POST /cut
GET  /status         battery, media %, errors, firmware
GET  /media          printable W/H/offsets from PICL
```

Design-later: keep design on the server (Pillow, or decode `.BWS` — pybrady already has a UDF v2 parser). The printer never sees the design file.

Existing library: [pybrady](https://pypi.org/project/pybrady/) has the byte-level spec and USB ESC/BMP working; **VGL/BLE is specified but not implemented** as of v0.1.x. Implementing `AsyncTransport` + VGL6 there (MPL-2.0) is better than starting from zero.

---

## 13. How to finish reverse-engineering 3.3.0 (optional)

This tree cannot yield `PE.Printing.dll` until the ABI split is present.

1. Obtain the full XAPK / universal APK (APKMirror “universal”, or `bundletool` from a Play backup).
2. Extract `lib/*/libassemblies.*.blob.so`.
3. Parse XABA (`XABA` magic) and XALZ (`XALZ` + LZ4 **block**, not frame).
4. Decompile `PE.Ble.dll` and `PE.Printing.dll` with ILSpy.
5. Diff `VglRlePrintDataGenerator6` and Apollo characteristic constants against this document.
6. On hardware: nRF Connect or `bluetoothctl` to dump services; then a first `bleak` script that only does ownership + subscribe + feed.

Live capture (Wireshark + Android HCI snoop, or a BLE sniffer) of one official-app print is the fastest way to lock raster polarity and header/trailer padding.

---

## 14. Uncertainties

- [ ] Raster bit polarity (0 = black vs 1 = black) — confirm with a 1-pixel test print.
- [ ] Whether page W/H in STX `4B 00 0C` is full liner size or printable area.
- [ ] Exact header/trailer inclusion in the bitmap vs in VGL offsets (`000D`/`000F`).
- [ ] Ownership flag `0x01` vs `0x00` on a factory-reset M211.
- [ ] Disconnect zero-buffer length (Web SDK writes 36 zeros; 17 should be enough).
- [ ] Indication vs notification on PICL Response — support both CCCD 0x01 and 0x02.
- [ ] 3.3.0 VGL generator vs 3.1.0 — UUIDs match; command stream not re-dumped from this APK.
- [ ] Continuous-tape length encoding when `000E` is 0.

---

## 15. Recommendations

1. For a **weekend print-from-HA** path: Python + bleak implementing §5–8 first (`feed` / `cut` / status). Add VGL6 after a captured reference job.
2. For a **browser UI** on a laptop next to the printer: `@bradycorporation/brady-web-sdk` `printBitmap` and skip the wire protocol.
3. Do not try to drive the M211 from HA’s built-in Bluetooth integration; it has no Apollo profile.
4. Keep the printer unpaired in Windows/Android system settings; only your client should hold the GATT session.
5. When adding design later, render to PNG at 203 dpi and reuse the same print path. `.BWS` parsing is a separate layer (pybrady `templates.brady_bws`).
