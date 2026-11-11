# Поиск: сети и приложение

Решения D-10, D-32, D-33 в [decisions.md](decisions.md). Радиопакеты маячка описаны в [concept.md](concept.md#радио).

## Краудсорсинговые сети

Делается после своего механизма поиска (D-32, D-33). Всё идёт через приложение Cricket под аккаунтами пользователя: компьютер у пользователя не нужен, своего сервера нет.

| Сеть | Кто находит | Как владелец видит координаты | Что нужно пользователю |
|---|---|---|---|
| Apple Find My | любой проходящий iPhone, отчёт уже от одного телефона | приложение Cricket: вход в Apple ID, запрос отчётов по хэшам ключей, расшифровка в телефоне | Apple ID, хотя бы раз привязанный к Apple-устройству; на Android — библиотеки anisette (см. ниже) |
| Google Find Hub | проходящие Android-телефоны | приложение Cricket: вход в Google-аккаунт, регистрация маячка, опрос и расшифровка отчётов | Google-аккаунт |

Официальные пути закрыты (D-32): Apple Find My требует MFi, а Find Hub через Google Fast Pair работает для несертифицированных моделей только на аккаунтах из белого списка Google; сертификация в лаборатории Google проекту недоступна. Поэтому маячок не появляется в штатных приложениях «Локатор» и Find Hub, а координаты показывает своё приложение.

### Привязка и ключи

- Привязка (кнопка на маячке, удержание 3 с) делает всё за один сеанс по своему GATT-сервису.
- Apple: приложение генерирует пары ключей P-224, публичные записывает в маячок, приватные хранит у себя. Приватные ключи нужно резервировать (Android backup или экспорт), иначе со сменой телефона отчёты Apple для этого маячка не расшифровать.
- Google: приложение регистрирует маячок в Google-аккаунте пользователя и записывает в маячок ключ. Сначала постоянный EID, позже сменный по спецификации FHN (D-32).

### Apple: anisette

Apple отдаёт отчёты только с заголовками anisette, которые генерируют проприетарные библиотеки Apple.

- **Android.** Библиотеки — из Apple Music для Android (это родные Android-библиотеки). Приложение скачивает их при первом запуске, как FindMy.py (~2 МБ), или берёт из APK установленной Apple Music: APK других приложений читаются по пути из `PackageManager.getApplicationInfo(...).sourceDir` и `splitSourceDirs`, пакет `com.apple.android.music` объявляется в `<queries>`. В приложение библиотеки не встраиваются: это распространение кода Apple, из Google Play такое удалят. Загрузка библиотек в процессе Cricket не проверена — сначала прототип.
- **Запасные пути:** публичные anisette-серверы SideStore (SideStore предупреждает, что через перегруженные серверы Apple блокировала аккаунты) или контейнер `anisette-v3-server` дома у пользователя. Сервер anisette не видит ни логина, ни ключей, ни координат.
- **iOS.** Генерировать anisette в iOS-приложении нельзя: чужой код не загрузить, приватный AuthKit App Store отклоняет. Нужен удалённый anisette; решается вместе с iOS-приложением.
- **Риски:** условия Apple это нарушает, как и любой проект на основе OpenHaystack; обновление Apple может сломать вход. Ключи входа (passkey) на Apple ID должны быть выключены. Блокировка касается только аккаунта этого пользователя.
- **Проверка до разработки:** FindMy.py на компьютере со своим Apple ID получает отчёты; затем прототип anisette на Pixel.

### Google

Логика GoogleFindMyTools (вход в Google, регистрация маячка, получение отчётов) переносится в приложение (Dart, нативный код при необходимости). Перерегистрация, которую скрипт требует раз в 4 дня, — фоновая задача приложения. API неофициальный, Google может его изменить.

Похоже, что Android по умолчанию отправляет отчёты только «в людных местах» (настройка «With network in busy places only»), то есть когда маячок видят несколько телефонов сразу; на странице Google умолчание не названо, не проверено. Если так, в поле Find Hub почти ничего не даст, а Apple отправляет отчёт от одного iPhone.

### Ограничения

- Сети срабатывают, только если мимо маячка проходит чужой телефон. В поле и лесу это редкость. Основной инструмент поиска упавшего дрона: своё приложение.
- Пути неофициальные. Обновления Apple или Google могут их сломать, тогда нужно обновлять приложение.

## Своё приложение (Android, первым)

Flutter, свой BLE-слой на Kotlin, офлайн-карты OpenTopoMap (D-38). Что сделано — в [app/README.md](../app/README.md).

### Функции

1. **Сканер.** Ищет рекламу Cricket на Coded PHY, а если телефон её не принимает, на обычном 1M. Показывает список своих маячков с уровнем сигнала и зарядом.
2. **Тепло-холодно.** Крупный индикатор уровня сигнала со сглаживанием и звуком, как у металлоискателя.
3. **Карта.** Пока владелец ходит, приложение записывает пары «GPS телефона + уровень сигнала» и рисует область вероятного положения маячка (взвешенный метод наименьших квадратов по модели затухания).
4. **Команда «пищи».** Подключение к маячку и включение бипера и вспышек на нужное время.
5. **Последние координаты GPS**, если полётник их передавал. Показываются на карте сразу при обнаружении.
6. **Привязка маячка** (кнопка на маячке, удержание 3 с), настройка режимов, обновление прошивки по BLE.
7. **Координаты из Find My и Find Hub**, если маячок был замечен сетями.
8. **Найденный чужой маячок.** Если поблизости потерянный маячок (ESCALATE, ALARM, BEACON) не из своих, приложение показывает контакт владельца и даёт включить писк ([protocol.md](protocol.md#контакт-владельца)). Свой контакт задаётся в настройках маячка.

### Поддержка Coded PHY в телефонах

- Флаг поддержки в Android API ненадёжен: телефон может заявлять поддержку, но не принимать Coded-рекламу.
- По отзывам разработчиков приём работает у Samsung начиная с S10, OnePlus начиная с 7, у части Xiaomi. У некоторых Pixel не работает.
- Приложение должно проверять приём на практике, а не по флагу, и автоматически переходить на 1M.
- **Телефон владельца: Google Pixel 7 Pro.** Прямого подтверждения приёма Coded PHY для этой модели не найдено. У Pixel есть известная ошибка: при сканировании только на Coded PHY телефон возвращает лишь пакеты 1M. В баг-трекере Google сообщают обходной путь, проверенный на Pixel 6: сканировать сразу на 1M и Coded (PHY_LE_ALL_SUPPORTED, legacy выключен), тогда Coded-пакеты приходят. Приложение должно использовать именно этот режим.
- Как проверить заранее: в приложении nRF Connect for Mobile в сведениях об устройстве видно, заявлена ли поддержка LE Coded PHY и extended advertising. Реальный приём проверяется вторым Android-телефоном, который рекламирует на Coded PHY через вкладку Advertiser в nRF Connect, либо первой платой маячка.

### iPhone

iPhone не принимает Coded PHY. Приложение под iOS работает только на 1M с меньшей дальностью. Для владельцев iPhone основной путь: Apple Find My. Приложение под iOS делается после Android.

## Источники

- [Everytag](https://github.com/vasimv/Everytag) (GPLv3, только как справочник), [macless-haystack](https://github.com/dchristl/macless-haystack) и его [FAQ](https://github.com/dchristl/macless-haystack/blob/main/FAQ.md)
- [FindMy.py](https://github.com/malmeloo/FindMy.py) (MIT), [вход в аккаунт](https://docs.mikealmel.ooo/FindMy.py/getstarted/01-account.html); [anisette-v3-server](https://github.com/Dadoum/anisette-v3-server); [SideStore FAQ](https://docs.sidestore.io/docs/faq)
- [GoogleFindMyTools](https://github.com/leonboe1/GoogleFindMyTools), [обзор CNX Software](https://www.cnx-software.com/2025/02/12/googlefindmytools-locates-esp32-based-trackers-using-google-find-my-device-network/)
- [Find Hub Network Accessory Specification](https://developers.google.com/nearby/fast-pair/specifications/extensions/fmdn), [Partner Integration Guide for Find Hub](https://developers.google.com/nearby/fast-pair/landing-page-find-hub), [требования к Locator Tags](https://developers.google.com/nearby/fast-pair/specifications/devicefeaturerequirement/devicefeaturerequirement_locatortags), [Nordic: Fast Pair integration](https://nrfconnectdocs.nordicsemi.com/ncs/latest/nrf/external_comp/bt_fast_pair/core.html), [настройки сети Find Hub](https://support.google.com/android/answer/3265955)
- [Coded PHY на Android: Apple Developer Forums](https://developer.apple.com/forums/thread/131506), [Google Issue Tracker](https://issuetracker.google.com/issues/148487283), [DevZone: флаг поддержки](https://devzone.nordicsemi.com/f/nordic-q-a/70038/android-nrf-connect---proper-indication-of-coded-phy-support)
- [Тест дальности Coded PHY, Nordic](https://blog.nordicsemi.com/getconnected/tested-by-nordic-bluetooth-long-range)
