[![GitHub Release](https://img.shields.io/github/v/release/akinin/wirenboard-discovery?style=flat&color=%23A349A4)](https://github.com/akinin/wirenboard-discovery)
[![Поддержать проект](https://img.shields.io/badge/Поддержать%20проект-spasibomir.ru-2ea44f?style=flat)](https://spasibomir.ru/pay/22699)


# Wiren Board Discovery for Home Assistant (unofficial)

> Данная интеграция не является официальной, не поддерживается и не аффилирована с компанией Wiren Board.

Кастомная интеграция Home Assistant для добавления устройств Wiren Board по MQTT-топикам `/devices/...`.

## Что делает

- подключается к MQTT-брокеру Wiren Board;
- читает retained-топики устройств и элементов;
- показывает найденные элементы в мастере настройки Home Assistant;
- создает сущности `sensor`, `binary_sensor`, `switch`, `number`, `button` и `text`;
- скрывает системные устройства в списке выбора по умолчанию;
- проставляет классы и единицы измерения для основных сенсоров;
- отправляет команды записи в стандартный топик Wiren Board `/devices/<device>/controls/<control>/on`.
- предоставляет действие `wirenboard_discovery.send_sms` для отправки SMS через `sms_sender` на Wiren Board.

## Установка через HACS

1. Откройте HACS.
2. Откройте `Custom repositories`.
3. Добавьте репозиторий:

`https://github.com/akinin/wirenboard-discovery`

4. Выберите тип `Integration`.
5. Установите `Wiren Board Discovery`.
6. Перезапустите Home Assistant.

## Ручная установка

Скопируйте папку `custom_components/wirenboard_discovery` в `config/custom_components/` Home Assistant и перезапустите Home Assistant.

## Настройка

После перезапуска откройте:

`Настройки -> Устройства и службы -> Добавить интеграцию -> Wiren Board Discovery`

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/add_integration.png" width="600" />

## Автообнаружение контроллера

Интеграция поддерживает автообнаружение Wiren Board через mDNS/Zeroconf. Home Assistant может сам показать найденный контроллер, если он публикуется в сети с именем вида `wirenboard-XXXX.local`.

После появления карточки найденного контроллера нажмите `Настроить` и выберите элементы, которые нужно добавить в Home Assistant.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/autodiscover.png" width="600" />

Если контроллер не появился автоматически, добавьте интеграцию вручную и укажите адрес контроллера.

Введите параметры подключения.
> Параметры подключения можно изменить позже через `Настроить -> Подключение`: адрес, порт, логин, пароль и префикс MQTT-топиков.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/add_integration_2.png" width="400" /> <img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/menu.png" width="400" />


В процессе будет запрос на выбор элементов, для автоматической группировке по устройствам.
<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/elements.png" width="400"/> <img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/elements_2.png" width="400"/>

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/add_integration_3.png" />

## Отправка SMS

Если на Wiren Board создано виртуальное устройство `sms_sender` с текстовым
контролом `send`, интеграция может отправлять SMS через уже настроенное MQTT-соединение.
Отдельная MQTT-интеграция Home Assistant или MQTT bridge для этого не нужны.

В автоматизации выберите действие `Wiren Board Discovery: Send SMS` и укажите
подключение Wiren Board, номер получателя и текст. YAML-вариант:

```yaml
action: wirenboard_discovery.send_sms
data:
  config_entry_id: YOUR_CONFIG_ENTRY_ID
  phone: "+79991234567"
  message: "Test message"
```

Номер передаётся при каждом вызове и не хранится в настройках интеграции.
Поддерживаются международные номера с `+`, а российские номера из 10 или 11 цифр
автоматически приводятся к формату `+7XXXXXXXXXX`.

Действие публикует строку `номер;сообщение` в
`/devices/sms_sender/controls/send/on`. На Wiren Board должен быть установлен
скрипт, который принимает этот контрол, вызывает `Notify.sendSMS()` и очищает
`sms_sender/send` после обработки.

После отправки интеграция ждёт, пока `send_sms.js` примет команду, и автоматически
записывает в командный контрол пробел. Скрипт игнорирует его после `trim()`, а
`wb-rules` запоминает новое значение команды. Поэтому следующее полностью
одинаковое SMS снова вызывает `whenChanged`. Вызовы выполняются последовательно,
чтобы отправка и автоматический сброс не пересекались.

## Логические устройства

Для создания логического устройства нужно добавить группу. Через интерфейс Home Assistant откройте интеграцию Wiren Board Discovery, нажмите `Настроить`, затем `Добавить или обновить группу`.
Группа может быть обычным HA-устройством или составной сущностью: ворота, шторы/роллеты, термостат, кондиционер. Для составных сущностей можно указать роли элементов: команда, позиция, состояние, препятствие, текущая и целевая температура, питание, режим, вентилятор.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/group.png" width="400"/>

Если элемент нужен и внутри составной сущности, и отдельно для автоматизаций, добавьте его в `Оставить отдельными сущностями`.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/roles.png" width="400"/>

В дальнейшем группу можно редактировать.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/group_edit.png" width="600"/>

Пример додавленных ворот:

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/gate.png" width="600"/>

Автоматическая группировка сама создает устройства на основе выбранных элементов.

<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/main_window.png" width="600"/>
<img src="https://raw.githubusercontent.com/akinin/wirenboard-discovery/refs/heads/main/images/auto_groups.png" width="600"/>

## Экспорт / импорт конфигурации интеграции

Конфигурацию можно перенести между установками через `Настроить -> Экспорт конфигурации` и `Настроить -> Импорт конфигурации`.

---
Также можно использовать файл `/config/wirenboard_discovery.yaml`:

```yaml
devices:
  kitchen_climate:
    name: "Кухня: климат"
    controls:
      - "wb-msw-v4_74/Current Temperature"
      - "wb-msw-v4_74/Humidity"
      - "R8C-963S_22/Power"
      - "R8C-963S_22/Temperature Setpoint"

  hallway_relays:
    name: "Прихожая: реле"
    controls:
      - "wb-mr6cu_63/K1"
      - "wb-mr6cu_63/K2"
      - "wb-mr6cu_63/K3"
```

В `controls` указывается ключ вида `<wb_device_id>/<control_id>`. Можно использовать `*`, например `"wb-mr6cu_63/K*"`. После изменения файла перезагрузите интеграцию или Home Assistant.
