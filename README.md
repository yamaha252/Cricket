# Cricket

Лёгкий BLE-маячок для поиска упавшего FPV-дрона, своё приложение для поиска и, на следующем этапе, приёмник для поискового дрона.

Маячок спроектирован с нуля на модуле Insight SiP ISP2454-LX (Nordic nRF54L15, D-29; до этого был u-blox ANNA-B402).

## Что умеет cricket-tag

- Ставится на дроны от BetaFPV Pavo Pico II (80 мм) и крупнее, весит около 3 г с аккумулятором.
- Заряжается от 5 В полётника, при падении работает от своего Li-Po: бипер часами, BLE 2–4 недели.
- Сам отличает падение от замены аккумулятора: статус armed по MSP, удар по акселерометру, нарастающая тревога.
- Виден своему Android-приложению на сотни метров (Coded PHY, ориентир 300–500 м при прямой видимости) и сетям Apple Find My и Google Find Hub.
- Громкий бипер уровня Flywoo Finder V1.0 и белый светодиод.
- Собирается на заводе JLCPCB целиком, руками только прошивка и пайка проводов аккумулятора и полётника к площадкам (D-26).

## Схема и плата

Ревизия A: 17 × 32 мм, 2 слоя, 0,6 мм, все детали сверху. Подробности — в [hardware/cricket-tag/README.md](hardware/cricket-tag/README.md).

[![Схема cricket-tag, ревизия A](hardware/cricket-tag/render/schematic.png)](hardware/cricket-tag/render/schematic.png)

<p>
  <img src="hardware/cricket-tag/render/3d-top.png" alt="Плата сверху" width="260">
  <img src="hardware/cricket-tag/render/3d-bottom.png" alt="Плата снизу" width="260">
  <img src="hardware/cricket-tag/render/copper-top-bottom.png" alt="Медь: верхний и нижний слой" width="440">
</p>

Слева направо: верх, низ с площадками проводов и SWD, медь обоих слоёв. Модуль ISP2454-LX (вверху слева, у антенны) и излучатель (большой прямоугольник внизу) на рендере не показаны: у них нет 3D-моделей, видны только площадки.

## Документация

| Документ | Содержание |
|---|---|
| [docs/requirements.md](docs/requirements.md) | требования |
| [docs/decisions.md](docs/decisions.md) | журнал решений с причинами |
| [docs/concept.md](docs/concept.md) | архитектура, режимы, радио, энергобюджет |
| [docs/components.md](docs/components.md) | компоненты, коды LCSC, номиналы, требования к антенне, масса |
| [docs/manufacturing.md](docs/manufacturing.md) | заводская сборка на JLCPCB |
| [docs/cost.md](docs/cost.md) | себестоимость по тиражам |
| [docs/module-options.md](docs/module-options.md) | радиомодули со склада JLCPCB и голый nRF54L10 |
| [docs/app.md](docs/app.md) | сети Find My и Find Hub, своё приложение |
| [docs/setup.md](docs/setup.md) | окружение разработки |

## Состав репозитория

| Папка | Назначение | Статус |
|---|---|---|
| `hardware/cricket-tag/` | KiCad-проект маячка | схема ревизии A (ERC 0) и разведённая плата 17 × 32 мм (DRC 0) готовы; выходных файлов для завода ещё нет |
| `hardware/cricket-seeker/` | приёмник для поискового дрона | не начат |
| `firmware/` | прошивка, Zephyr / nRF Connect SDK | не начата |
| `app/` | Android-приложение | не начато |
| `docs/` | документация | актуальна |

## Статус

Требования и компоненты ревизии A согласованы 2026-11-09:

- радиомодуль Insight SiP ISP2454-LX (nRF54L15, D-29) через JLCPCB Global Sourcing, излучатель Same Sky CPT-1117-83 тоже через Global Sourcing (D-27), сборка Standard PCBA;
- себестоимость ~17 $ за плату при 24 шт., ~12 $ при 120 шт.;
- первый заказ — тестовая партия 8 плат примерно за 222 $.

Схема и плата 17 × 32 мм с ANNA-B402 были готовы 2026-11-10 (D-28). В тот же день модуль заменён на ISP2454-LX (D-29): схема готова (ERC 0), плата разведена полностью (DRC 0, схема и плата совпадают). Затем — проверка разводки глазами, выходные файлы для JLCPCB, прошивка. Картинки выше — текущая плата D-29.

## Лицензия

[MIT](LICENSE): схема, плата, скрипты, прошивка и документация.
