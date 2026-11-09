# Поиск: сети и приложение

Решение D-10 в [decisions.md](decisions.md). Радиопакеты маячка описаны в [concept.md](concept.md#радио).

## Краудсорсинговые сети

| Сеть | Кто находит | Как владелец видит координаты | Прошивка |
|---|---|---|---|
| Apple Find My | любой проходящий iPhone | macless-haystack: веб-интерфейс и сервер, работает с Android, нужен Apple ID | Everytag |
| Google Find Hub | проходящие Android-телефоны | GoogleFindMyTools: Python-скрипт, нужен Google-аккаунт | Everytag, GoogleFindMyTools |

Ограничения:

- Координаты самодельного маячка не видны в штатных приложениях Apple и Google. Их показывают сторонние инструменты, их можно встроить в своё приложение или сервер.
- Сети срабатывают, только если мимо маячка проходит чужой телефон. В поле и лесу это редкость. Основной инструмент поиска упавшего дрона: своё приложение.
- Проекты экспериментальные и неофициальные. Апдейты Apple или Google могут их сломать.

## Своё приложение (Android, первым)

### Функции

1. **Сканер.** Ищет рекламу Cricket на Coded PHY, а если телефон её не принимает, на обычном 1M. Показывает список своих маячков с уровнем сигнала и зарядом.
2. **Тепло-холодно.** Крупный индикатор уровня сигнала со сглаживанием и звуком, как у металлоискателя.
3. **Карта.** Пока владелец ходит, приложение записывает пары «GPS телефона + уровень сигнала» и рисует область вероятного положения маячка (взвешенный метод наименьших квадратов по модели затухания).
4. **Команда «пищи».** Подключение к маячку и включение бипера и вспышек на нужное время.
5. **Последние координаты GPS**, если полётник их передавал. Показываются на карте сразу при обнаружении.
6. **Привязка маячка** (кнопка на маячке, удержание 3 с), настройка режимов, обновление прошивки по BLE.
7. **Координаты из Find My и Find Hub**, если маячок был замечен сетями.

### Поддержка Coded PHY в телефонах

- Флаг поддержки в Android API ненадёжен: телефон может заявлять поддержку, но не принимать Coded-рекламу.
- По отзывам разработчиков приём работает у Samsung начиная с S10, OnePlus начиная с 7, у части Xiaomi. У некоторых Pixel не работает.
- Приложение должно проверять приём на практике, а не по флагу, и автоматически переходить на 1M.
- **Телефон владельца: Google Pixel 7 Pro.** Прямого подтверждения приёма Coded PHY для этой модели не найдено. У Pixel есть известная ошибка: при сканировании только на Coded PHY телефон возвращает лишь пакеты 1M. В баг-трекере Google сообщают обходной путь, проверенный на Pixel 6: сканировать сразу на 1M и Coded (PHY_LE_ALL_SUPPORTED, legacy выключен), тогда Coded-пакеты приходят. Приложение должно использовать именно этот режим.
- Как проверить заранее: в приложении nRF Connect for Mobile в сведениях об устройстве видно, заявлена ли поддержка LE Coded PHY и extended advertising. Реальный приём проверяется вторым Android-телефоном, который рекламирует на Coded PHY через вкладку Advertiser в nRF Connect, либо первой платой маячка.

### iPhone

iPhone не принимает Coded PHY. Приложение под iOS работает только на 1M с меньшей дальностью. Для владельцев iPhone основной путь: Apple Find My. Приложение под iOS делается после Android.

## Источники

- [Everytag](https://github.blesdmm.dns-dynamic.net/vasimv/Everytag), [macless-haystack](https://github.com/dchristl/macless-haystack)
- [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools), [обзор CNX Software](https://www.cnx-software.com/2025/02/12/googlefindmytools-locates-esp32-based-trackers-using-google-find-my-device-network/)
- [Coded PHY на Android: Apple Developer Forums](https://developer.apple.com/forums/thread/131506), [Google Issue Tracker](https://issuetracker.google.com/issues/148487283), [DevZone: флаг поддержки](https://devzone.nordicsemi.com/f/nordic-q-a/70038/android-nrf-connect---proper-indication-of-coded-phy-support)
- [Тест дальности Coded PHY, Nordic](https://blog.nordicsemi.com/getconnected/tested-by-nordic-bluetooth-long-range)
