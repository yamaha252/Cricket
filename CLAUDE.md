# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Cricket is a hardware + firmware project: an ultra-light BLE crash beacon for drones (`cricket-tag`) and a receiver for a search drone (`cricket-seeker`). It was spun out of an analysis of the Epi_C3 ESP32-C3 board (sibling repo `../Epi_C3`); nothing from that board is reused except, possibly, as a Wi-Fi bridge on the seeker.

Read the docs before proposing parts, topology or behaviour changes. They record decisions agreed with the owner:

- `docs/requirements.md` — what the owner asked for (target drones, mass, loudness, factory assembly, phones).
- `docs/decisions.md` — numbered decision log (D-1…) with reasons. Add new entries on top; never silently reverse one.
- `docs/concept.md` — architecture, schematic notes, operating modes, radio, energy budget.
- `docs/components.md` — BOM source of truth until the schematic exists: LCSC codes, passive values, antenna keep-out geometry, mass.
- `docs/manufacturing.md` — JLCPCB full-assembly rules.
- `docs/cost.md` — production cost from live quotes (2026-11-10). The vendor for the first order is NOT chosen yet (D-31); options are being compared, and the recommended rev-0 batch is 3–4 boards (NextPCB 213–232 $ with promo, ~175 $ for one board; Seeed ~250–275 $ for 1–2 incl. module estimate, free shipping; NextPCB also holds a one-time −500 $ Rev0 SMT coupon whose stacking is unknown). NextPCB turnkey: 8 boards, 2 × 2 panel 44 × 74 mm, 322 $ with a −200 $ promo (522 $ without), shipping not included, quote under engineering review in the owner's NextPCB cart, unpaid. JLCPCB (D-30): ~250–285 $ but hides assembly for Kazakhstan by visitor IP and only offers V-cut panels; PCBWay blocks Kazakhstan entirely. Orders ship to a forwarder in Guangdong (address lives only in the vendor account, never in the repo).
- `docs/module-options.md` — radio modules from JLCPCB stock and bare nRF54L10 (rejected for rev A, D-19).
- `docs/app.md` — Find My / Find Hub and the Android app.
- `docs/protocol.md` — Cricket advertising payload, intervals per mode, GATT service and commands.

Priorities, in order: weight and size, power, range. Expected line-of-sight range on the small board: 150–250 m on 1M, 300–500 m on Coded PHY (D-17).

## Fixed decisions

- MCU/radio (Ebyte E73 from JLCPCB stock was considered and rejected by the owner, D-19): **Insight SiP ISP2454-LX** (Nordic nRF54L15, 8 × 8 × 1 mm LGA-62, internal chip antenna, both crystals, DC/DC and decoupling inside, +8 dBm), bought by JLCPCB via Global Sourcing from Mouser (LCSC C44975104 pre-order; D-29, replaces u-blox ANNA-B402 of D-15 and the external crystal of D-16). The owner rejected consigning parts, so every part must come from JLCPCB stock or Global Sourcing. Antenna per datasheet section 4.3: module in the corner, antenna half towards the end edge, 1 mm from it and 1.3 mm from the side edge, a 14 × 5 mm no-copper strip on both layers. Signals only from the outer pad row (0.25 mm gaps) except UART_RX from inner pad 29 through a tented via under the module; nRF54L15 port rules (P2 has no interrupts or wake-up, ADC/PWM/I2C on P1, SCL only on clock pins) drive the pin map. Do not propose ESP32 or bare-chip RF for rev A.
- **Full factory assembly on JLCPCB**: every on-board part must be on LCSC or obtainable via Global Sourcing; all parts on the top side. No connectors (D-26, replaces the JST SH of D-6): battery and flight-controller wires (5V, GND, TX, RX) are hand-soldered to copper-only pads on the bottom (J1, J2), SWD is 4 bottom pads at 2.54 mm (J3) under the battery.
- Board 2 layers, 0.6 mm; module with antenna at the far end. 22 × 13 does not fit the parts; the floorplan (`hardware/cricket-tag/floorplan/`) plus routing give 17 × 32 mm (variant `isp_c`, D-29). Battery under the board, at most 15 mm long with its PCM (401012 / 401015), never under the module or antenna.
- Power: Li-Po 1S with built-in PCM, TP4054 (C32574) from the FC's 5 V, TPS7A0233 3.3 V LDO (D-14). Module never above 3.6 V. White LED and PAM8904E run from VBAT.
- Buzzer: Same Sky CPT-1117-83-SMT-TR (11 × 9 × 1.7 mm, tabs make it 15 × 9, pads 15.5 × 9 mm, ≥83 dB at 5 Vpp, broad 3–8 kHz response, LCSC C22359733 but bought via Global Sourcing) driven by PAM8904E (D-27, reverts D-25; CPT-9019A footprint kept as the fallback). The radio module and the buzzer go through Global Sourcing. Buzzer is event-driven, it dominates the energy budget.
- Crash detection: MSP armed status over UART, LIS2DH12 impact, escalating alarm as fallback. Battery swaps and storage must not trigger a loud alarm. A button is required.
- Firmware is our own, MIT (D-32): Everytag (GPLv3) is a reference only, never copy its code. Official Apple MFi Find My and Google-certified Find Hub (Fast Pair `locator_tag`) are out of reach and not considered. Order: own search mechanism (Cricket sets, modes, drivers) first, Apple/Google sets later.
- Radio: own Cricket sets on Coded PHY S8 (+8 dBm) and 1M, later Apple Find My (OpenHaystack format) + Google Find Hub (FHN format, static EID first); all sets advertise concurrently via extended advertising, each with its own identity address. Crowd-network locations are fetched by our own app under the user's accounts, no server of ours (D-33; Apple anisette generated on the phone from Apple Music libs, unproven). The owner's phone is a Pixel 7 Pro: scan with PHY_LE_ALL_SUPPORTED, not Coded only (Pixel bug). Radio is silent while the drone is armed (ELRS coexistence). Android app first.

## Layout

- `hardware/cricket-tag/` — KiCad project for the beacon. Project library `lib/` (`cricket` symbols and footprints) holds the ISP2454-LX symbol and footprints with the antenna keepout built in, generated by `lib/gen_isp2454.py` (the former ANNA-B402 by `lib/gen_anna_b402.py`) (simple symbols by `lib/gen_symbols.py`, other footprints including the wire and SWD pads by `lib/gen_footprints.py`), so edit the scripts, not the files. `floorplan/floorplan.py` checks part placement and board size by courtyard DRC on a test board. The schematic is built step by step by `gen_schematic.py`; until the owner starts editing it in KiCad, change the script and regenerate. Schematic steps 1–8 are done: ERC 0 errors, 0 warnings, with one intentional exclusion (LIS2DH12 SA0 tied to +3V3) that `gen_schematic.py` writes into `cricket-tag.kicad_pro` itself. Pin map in `hardware/cricket-tag/README.md` (D-29; PAM8904E EN2 tied to VBAT, D-28). The PCB is generated and routed by `route.sh` (gen_pcb.py with pre-routed module escapes → Freerouting 2.5 with GND routed as a normal net, no `--planes` since D-29 → DRC-driven fixes with maze.py/fanout.py → GND stitching); see the board README, section «Разводка». Running it rewrites `cricket-tag.kicad_pcb`; Freerouting is not deterministic. The PAM8904E charge-pump wiring cannot be found by Freerouting, so it is pre-routed and locked in `gen_pcb.py` (`DRIVER_TRACKS`/`DRIVER_VIAS`; C13/C14 sit 0.15 mm further right to make room for the CP2 via). The committed ISP2454-LX board (D-29) is the best of ~25 runs, finished by `finish_driver.py` (applies that driver wiring to the routed board, routes BUZ_P with maze.py allowed to cut GND tracks at a cost) plus `stitch.py`: DRC with schematic parity 0 violations, 0 unconnected, GND fully connected. Prefer small edits in KiCad over re-running route.sh.
- `hardware/cricket-seeker/` — receiver for a search drone (not started).
- `firmware/` — Zephyr / nRF Connect SDK v3.4.2. `app/` is the step-1 skeleton of our own search mechanism (D-32): Cricket Coded S8 + 1M connectable sets, GATT status/control, buzzer patterns, button, mode state machine; DK buttons simulate 5 V / armed / impact. Board definition `firmware/boards/cricket/cricket_tag` (target `cricket_tag/nrf54l15/cpuapp`: pin map, LFXO 18 pF because the SDK caps it below the datasheet's 19 pF, `board.c` frees the NFC pads for I2C, RTT logs). Both it and `nrf54l15dk/nrf54l15/cpuapp` build via `firmware/build.sh [board]`, not yet run on hardware. Protocol in `docs/protocol.md`; what is implemented and missing in `firmware/README.md`.
- `app/` — Android app (not started).
- `docs/` — see above.

## Working with KiCad files

KiCad 10 is installed (`kicad-cli` on PATH via Homebrew). The project files were created in KiCad 8 format; KiCad 10 opens them and rewrites them in its own format on first save, which is expected. Run checks headless after any edit:

```bash
kicad-cli sch erc hardware/cricket-tag/cricket-tag.kicad_sch -o /tmp/erc.rpt
kicad-cli pcb drc hardware/cricket-tag/cricket-tag.kicad_pcb -o /tmp/drc.rpt
```

Both must report 0 violations before fabrication outputs are generated. On the empty skeleton DRC reports one `invalid_outline` until the board edge is drawn. Fabrication outputs are generated by `hardware/cricket-tag/make_fab.sh` into `hardware/cricket-tag/fab/`, never edited by hand: gerber zip; `bom.csv`/`cpl.csv` for JLCPCB (rotation corrections keyed by LCSC part, checked in the JLCPCB preview except U1 and BZ1; ASCII Comment because JLCPCB misreads UTF-8); `bom-mpn.csv` and `cpl-kicad.csv`/`.zip` for NextPCB and others (manufacturer part numbers mapped from LCSC in the script, raw KiCad rotations). Gerbers differ between runs only by the timestamp header. Copper is 0.2–0.4 mm from the board edge in places, so panels must be routed with mouse bites, not V-cut. Ordering steps in `docs/manufacturing.md`.

## Firmware toolchain

nRF Connect SDK v3.4.2 and v2.8.0 are installed through `nrfutil sdk-manager` (under `/opt/nordic/ncs`). Firmware targets **v3.4.2** (D-32); v2.8.0 was only needed for Everytag and is unused. See `firmware/README.md`. Build inside the toolchain shell so the system Python is never used:

```bash
nrfutil sdk-manager toolchain launch --ncs-version v3.4.2 -- west build -b <board> --sysbuild firmware/app -d firmware/build
```

Flash with `west flash` (J-Link, installed) or `probe-rs run --chip nRF54L15_xxAA ...`. Targets: `cricket_tag/nrf54l15/cpuapp` (own board, needs `-DBOARD_ROOT=firmware`, which `firmware/build.sh` passes) and `nrf54l15dk/nrf54l15/cpuapp` (the nRF54L15 DK, DK buttons simulate inputs).

## Conventions

- Values in metric SI with unit symbols (`4,7µF`, `10kΩ`), consistent with the Epi_C3 style.
- Any new footprint or 3D model goes into `hardware/<board>/lib/` and is referenced via `${KIPRJMOD}`.
- Keep `docs/components.md` and `docs/decisions.md` in sync when a part or behaviour changes.
- Fill the `LCSC Part` field on every schematic symbol so the JLCPCB BOM is generated, not hand-written.
- Docs are written in Russian; keep that.
