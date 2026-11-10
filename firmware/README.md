# Прошивка

Не начата. Поведение описано в [docs/concept.md](../docs/concept.md#режимы-работы).

План:

- Zephyr / nRF Connect SDK v2.8.0 (см. раздел «Версия SDK»), модуль u-blox ANNA-B402 (nRF52833, 512 КБ флеш, 128 КБ ОЗУ). Пока нет своего board definition, сборка под `nrf52833dk/nrf52833`.
- Выводы модуля: карта в [hardware/cricket-tag/README.md](../hardware/cricket-tag/README.md#схема) (D-24). NFC-выводы перевести в GPIO (`CONFIG_NFCT_PINS_AS_GPIOS`).
- Apple Find My и Google Find Hub: интеграция Everytag.
- Свои наборы рекламы: Cricket Coded (Coded PHY S8, +8 dBm, подключаемый) и Cricket 1M для телефонов без Coded PHY.
- Режимы ON_DRONE, ESCALATE, ALARM, BEACON, STANDBY, LOW_BAT, SHIP.
- Признаки падения: MSP_STATUS (armed) по UART, удар по LIS2DH12, нарастание тревоги как запасной вариант.
- LIS2DH12 на I2C по адресу 0x19 (SA0 на VDD_IO), прерывание по удару на INT1 (ACC_INT1).
- Пищалка: ШИМ на BUZ_DIN, режим PAM8904E выводом BUZ_EN1 (0 — 1x, 1 — 3x; EN2 на VBAT, D-28). У CPT-1117-83 (D-27) громкость высокая широкой полосой 3–8 кГц: частоту или качание частоты подобрать замером.
- Без 5 В от полётника вывод UART_TX перевести во вход, чтобы не питать полётник через его защитные диоды, и выключить UART целиком: включённый приёмник UARTE держит HFCLK (сотни мкА), а UART_RX через 1 кОм висит на обесточенном полётнике.
- Режим 3x PAM8904E (BUZ_EN1 = 1) на полном аккумуляторе даёт размах до 25 В — ровно предел CPT-1117-83. Пока идёт заряд (VBAT до 4,24 В), использовать 1x или не пищать.
- Радио выключено, пока дрон armed: не мешать ELRS 2,4 ГГц.
- Чтение GPS с полётника по MSP, последние координаты в рекламе Cricket.
- Кнопка: выключение тревоги, привязка, режим хранения, загрузчик.
- Обновление прошивки по BLE (MCUboot + SMP).
- Источник LFCLK: внешний кварц 32,768 кГц (LFXO).
- Сканирование в приложении на Pixel: режим PHY_LE_ALL_SUPPORTED, не только Coded. Подробности в [docs/app.md](../docs/app.md).

## Объём флеш-памяти

Проверено 2026-11-09: Everytag (коммит из `main`, конфигурация `prj-smpsvr-lowpower.conf`, MCUboot с двумя слотами, OTA через mcumgr) собран для платы KKM K4P на nRF52833 — это тот же чип, что в ANNA-B402.

| Часть | Занято | Доступно | % |
|---|---|---|---|
| MCUboot | 32,9 КБ | 48 КБ | 67 % |
| Приложение (слот) | 185,1 КБ | 219,5 КБ | 82 % |
| ОЗУ приложения | 51,6 КБ | 128 КБ | 40 % |

Вывод: всё помещается, запас под наш код около 34 КБ. Наши добавления: набор рекламы на Coded PHY, драйвер LIS2DH12, MSP по UART, управление PAM8904E и светодиодом, режимы. Если запаса не хватит:

- убрать из mcumgr статистику и taskstat (`CONFIG_STATS`, `CONFIG_MCUMGR_GRP_OS_TASKSTAT`, `CONFIG_MCUMGR_GRP_STAT`);
- уменьшить раздел настроек NVS;
- перейти на MCUboot с одним слотом и обновлением по последовательному каналу (теряется OTA по BLE).

## Порт Everytag на SDK 3.4.2

Проверено 2026-11-09: Everytag собирается на SDK 3.4.2 после правки трёх строк — `bt_hci_cmd_create(...)` → `bt_hci_cmd_alloc(K_FOREVER)` в `src/main.c`, `BT_LE_ADV_OPT_CONNECTABLE` → `BT_LE_ADV_OPT_CONN` и `&auth_uuid` → `&auth_uuid.uuid` в `src/settings.c`; из конфигурации убран `CONFIG_RAM_POWER_ADJUST_ON_HEAP_RESIZE`. Под `nrf54l15dk/nrf54l10/cpuapp` с MCUboot: приложение 186 КБ из 444 КБ, MCUboot 40 КБ из 62 КБ, ОЗУ 56 КБ из 192 КБ. Работа на железе не проверена.

## Версия SDK

Everytag собирается только на nRF Connect SDK **v2.8.0**: в v3.4.2 изменился Bluetooth-API (`bt_hci_cmd_create`, `BT_LE_ADV_OPT_CONNECTABLE`, `bt_uuid_cmp`) и формат описания плат. Обе версии установлены. Ревизия A прошивки ведётся на v2.8.0, перенос на 3.x — отдельная задача.

```bash
nrfutil sdk-manager toolchain launch --ncs-version v2.8.0 -- west build -b nrf52833dk/nrf52833 --sysbuild <app> -d <build-dir>
```
