# Окружение разработки

Проверено на macOS (Apple Silicon), Homebrew.

## Плата (KiCad)

```bash
brew install --cask kicad          # KiCad 10.x, просит пароль администратора
brew install poppler               # pdftotext для чтения datasheet
```

Проекты в `hardware/` созданы в формате KiCad 8. KiCad 10 открывает их и при сохранении переводит в свой формат — это ожидаемо, коммитить после первого сохранения.

CLI для проверок без GUI (`kicad-cli` слинкован Homebrew в `/opt/homebrew/bin`):

```bash
KICAD_CLI=kicad-cli
$KICAD_CLI sch erc  hardware/cricket-tag/cricket-tag.kicad_sch -o /tmp/erc.rpt
$KICAD_CLI pcb drc  hardware/cricket-tag/cricket-tag.kicad_pcb -o /tmp/drc.rpt
$KICAD_CLI pcb export gerbers hardware/cricket-tag/cricket-tag.kicad_pcb -o hardware/cricket-tag/fab/gerbers/
$KICAD_CLI pcb export drill   hardware/cricket-tag/cricket-tag.kicad_pcb -o hardware/cricket-tag/fab/gerbers/
$KICAD_CLI pcb export pos     hardware/cricket-tag/cricket-tag.kicad_pcb -o hardware/cricket-tag/fab/cpl.csv --format csv --units mm --side front
$KICAD_CLI sch export bom     hardware/cricket-tag/cricket-tag.kicad_sch -o hardware/cricket-tag/fab/bom.csv \
  --fields "Value,Reference,Footprint,LCSC Part" --labels "Comment,Designator,Footprint,LCSC Part #" \
  --group-by "Value,Footprint,LCSC Part" --ref-range-delimiter "" --exclude-dnp
```

Плагины KiCad ставятся через Plugin and Content Manager в GUI: Interactive HTML BOM, Fabrication Toolkit (JLCPCB BOM/CPL), библиотека Espressif (для seeker, если понадобится ESP32).

## Прошивка (nRF Connect SDK, Zephyr)

```bash
brew install --cask nrfutil        # Nordic nrfutil
nrfutil install sdk-manager device
nrfutil sdk-manager install v3.4.2 # SDK + toolchain в /opt/nordic/ncs (несколько ГБ)
nrfutil sdk-manager install v2.8.0 # нужен для Everytag, на нём ведётся прошивка ревизии A
brew install dtc probe-rs-tools
brew install --cask segger-jlink   # просит пароль администратора
```

VS Code: расширение `nordic-semiconductor.nrf-connect-extension-pack` (ставится командой `code --install-extension`).

Сборка из командной строки идёт внутри toolchain-окружения, чтобы не зависеть от системного Python:

```bash
nrfutil sdk-manager toolchain launch --ncs-version v3.4.2 --shell
```

Внутри этого shell:

```bash
cd /opt/nordic/ncs/v3.4.2
west build -b nrf54l15dk/nrf54l15/cpuapp nrf/samples/bluetooth/peripheral_lbs -d /tmp/build-lbs
```

Проверено 2026-11-09: сборка проходит, образ `/tmp/build-lbs/peripheral_lbs/zephyr/zephyr.hex` (sysbuild кладёт артефакты в подпапку с именем приложения), FLASH 13 %, RAM 11 %.

Без интерактивного shell одной командой:

```bash
nrfutil sdk-manager toolchain launch --ncs-version v3.4.2 -- west build -b nrf54l15dk/nrf54l15/cpuapp <app> -d <build-dir>
```

Целевая плата для `firmware/` — свой board definition под ANNA-B402 (nRF52833), пока его нет, собирать под `nrf52833dk/nrf52833`. Toolchain тот же. Проверено 2026-11-09: `peripheral_lbs` под `nrf52833dk/nrf52833` собирается, FLASH 177 КБ из 512 (35 %), RAM 28 КБ из 128 (22 %).

## Прошивка на устройство

- J-Link (включая встроенный в nRF52833-DK): `west flash` или `nrfutil device program --firmware build/zephyr/zephyr.hex`.
- Любой CMSIS-DAP / J-Link через probe-rs: `probe-rs run --chip nRF52833_xxAA build/zephyr/zephyr.elf`.
- Разводка платы — Freerouting 2.5 (`freerouting-2.5.0.jar` из релизов github.com/freerouting/freerouting) под OpenJDK 27 из Homebrew (`brew install openjdk`, keg-only: вызывается как `/opt/homebrew/opt/openjdk/bin/java`, системная Java не меняется). Запуск — `hardware/cricket-tag/route.sh`, см. README платы.
- У cricket-tag площадки SWD J3 снизу под аккумулятором: 1 VDD, 2 SWDIO, 3 SWCLK, 4 GND, шаг 2,54 мм, без отверстий. Прошивать до пайки аккумулятора, подпружиненными контактами или временными проводами (D-26).

## Что установлено (проверено 2026-11-09)

| Инструмент | Версия | Где |
|---|---|---|
| KiCad | 10.0.8 | `/Applications/KiCad`, `kicad-cli` в PATH |
| nrfutil | 9.0.0 | `/opt/homebrew/bin/nrfutil`, плагины sdk-manager, device |
| nRF Connect SDK + toolchain | v3.4.2 и v2.8.0 | через `nrfutil sdk-manager`; прошивка на v2.8.0 из-за Everytag |
| SEGGER J-Link | 9.92 | `/Applications/SEGGER/JLink`, `JLinkExe` в `/usr/local/bin` |
| probe-rs | 0.32 | поддерживает nRF52833 и nRF54L15 |
| dtc, poppler | brew | |
| VS Code | nRF Connect extension pack | |

Casks `kicad` и `segger-jlink` вызывают `sudo` и требуют ввода пароля в терминале, автоматизировать это нельзя.
