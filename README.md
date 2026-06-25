# WirenBoard Discovery for Home Assistant

Кастомная интеграция Home Assistant для добавления устройств Wiren Board по MQTT-топикам `/devices/...`.

## Что делает

- подключается к MQTT-брокеру Wiren Board;
- читает retained-топики устройств и элементов;
- показывает найденные элементы в мастере настройки Home Assistant;
- создает сущности `sensor`, `binary_sensor`, `switch`, `number`, `button` и `text`;
- скрывает системные устройства в списке выбора по умолчанию;
- проставляет классы и единицы измерения для основных сенсоров;
- отправляет команды записи в стандартный топик Wiren Board `/devices/<device>/controls/<control>/on`.

## Установка через HACS

1. Откройте HACS.
2. Откройте `Custom repositories`.
3. Добавьте репозиторий:

`https://git.akinin.su/akininav/wiren-board-discovery`

4. Выберите тип `Integration`.
5. Установите `Wiren Board Discovery`.
6. Перезапустите Home Assistant.

## Ручная установка

Скопируйте папку `custom_components/wirenboard_discovery` в `config/custom_components/` Home Assistant и перезапустите Home Assistant.

## Настройка

После перезапуска откройте:

`Настройки -> Устройства и службы -> Добавить интеграцию -> WirenBoard Discovery`

<img src="/images/add_integration.png" />

Введите параметры подключения.
> Параметры подключения можно изменить позже через `Настроить -> Подключение`: адрес, порт, логин, пароль и префикс MQTT-топиков.

<img src="/images/menu.png" width="400" /> <img src="/images/add_integration_2.png" width="400" />


В процессе будет запрос на выбор элементов, для автоматической группировке по устройствам.
<img src="/images/elements.png" width="400"/> <img src="/images/elements_2.png" width="400"/>

<img src="/images/add_integration_3.png" />

## Логические устройства

Для создания логического устройства нужно добавить группу. Через интерфейс Home Assistant откройте интеграцию WirenBoard Discovery, нажмите `Настроить`, затем `Добавить или обновить группу`.
Группа может быть обычным HA-устройством или составной сущностью: ворота, шторы/роллеты, термостат, кондиционер. Для составных сущностей можно указать роли элементов: команда, позиция, состояние, препятствие, текущая и целевая температура, питание, режим, вентилятор.

<img src="/images/group.png" width="400"/>

Если элемент нужен и внутри составной сущности, и отдельно для автоматизаций, добавьте его в `Оставить отдельными сущностями`.

<img src="/images/roles.png" width="400"/>

В дальнейшем группу можно редактировать.

<img src="/images/group_edit.png" width="600"/>

Пример додавленных ворот:

<img src="/images/gate.png" width="600"/>

Автоматическая группировка сама создает устройства на основе выбранных элементов.

<img src="/images/main_window.png" width="600"/>
<img src="/images/auto_groups.png" width="600"/>

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
