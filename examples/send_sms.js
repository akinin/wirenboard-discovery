// send_sms.js

defineVirtualDevice("sms_sender", {
    title: {
        en: "SMS Sender",
        ru: "Отправка SMS"
    },

    cells: {
        send: {
            title: {
                en: "Send",
                ru: "Отправить"
            },
            type: "text",
            readonly: false,
            value: ""
        },

        last_sent_time: {
            title: {
                en: "Last Sent Time",
                ru: "Время последней отправки"
            },
            type: "text",
            readonly: true,
            value: ""
        },

        last_message_text: {
            title: {
                en: "Last Message",
                ru: "Последнее сообщение"
            },
            type: "text",
            readonly: true,
            value: ""
        },

        last_recipient_number: {
            title: {
                en: "Last Recipient Number",
                ru: "Последний номер получателя"
            },
            type: "text",
            readonly: true,
            value: ""
        },

        last_result: {
            title: {
                en: "Last Result",
                ru: "Результат последней отправки"
            },
            type: "text",
            readonly: true,
            value: ""
        }
    }
});


function trimText(value) {
    return String(value).replace(/^\s+|\s+$/g, "");
}


function normalizePhoneNumber(value) {
    var phoneNumber = trimText(value);

    /*
     * Допустимые российские форматы:
     *
     * +79991234567
     * 79991234567
     * 89991234567
     * 9991234567
     *
     * Результат всегда:
     *
     * +79991234567
     */

    if (/^\+7[0-9]{10}$/.test(phoneNumber)) {
        return phoneNumber;
    }

    if (/^7[0-9]{10}$/.test(phoneNumber)) {
        return "+" + phoneNumber;
    }

    if (/^8[0-9]{10}$/.test(phoneNumber)) {
        return "+7" + phoneNumber.substring(1);
    }

    if (/^[0-9]{10}$/.test(phoneNumber)) {
        return "+7" + phoneNumber;
    }

    /*
     * Остальные международные номера:
     * от 7 до 15 цифр после плюса.
     */

    if (/^\+[0-9]{7,15}$/.test(phoneNumber)) {
        return phoneNumber;
    }

    return "";
}


function setLastResult(value) {
    dev["sms_sender"]["last_result"] = value;
}


defineRule("send_sms_via_notify", {
    whenChanged: "sms_sender/send",

    then: function (newValue) {
        /*
         * Значение от wb-rules может быть не обычной JS-строкой,
         * поэтому сначала явно преобразуем его.
         */

        if (newValue === null || newValue === undefined) {
            return;
        }

        var smsData = trimText(newValue);

        /*
         * После обработки контрол очищается, что повторно запускает
         * правило с пустым значением. Его просто игнорируем.
         */

        if (smsData === "") {
            return;
        }

        log("SMS: получена команда отправки");

        /*
         * Формат:
         *
         * номер;текст сообщения
         *
         * Разделяем только по первой точке с запятой.
         * Остальные точки с запятой остаются в сообщении.
         */

        var separatorPosition = smsData.indexOf(";");

        if (separatorPosition < 0) {
            setLastResult("Ошибка: ожидается формат Номер;Сообщение");
            log("SMS: неверный формат команды");
            return;
        }

        var rawPhoneNumber = trimText(
            smsData.substring(0, separatorPosition)
        );

        var messageText = trimText(
            smsData.substring(separatorPosition + 1)
        );

        if (rawPhoneNumber === "") {
            setLastResult("Ошибка: не указан номер");
            log("SMS: не указан номер получателя");
            return;
        }

        if (messageText === "") {
            setLastResult("Ошибка: сообщение пустое");
            log("SMS: текст сообщения пуст");
            return;
        }

        var phoneNumber = normalizePhoneNumber(
            rawPhoneNumber
        );

        if (phoneNumber === "") {
            setLastResult("Ошибка: некорректный номер");
            log(
                "SMS: некорректный номер получателя: " +
                rawPhoneNumber
            );
            return;
        }

        /*
         * Команда уже скопирована в локальные переменные.
         * Очищаем контрол до вызова Notify.sendSMS().
         *
         * Это позволяет повторно отправлять одинаковые сообщения
         * и не оставляет в MQTT старую команду.
         */

        dev["sms_sender"]["send"] = "";

        /*
         * Публикуем данные попытки до вызова модема. Приложение SMS Gateway
         * подписано на эти контролы и записывает подтверждённый результат
         * независимо от того, кто создал команду: Home Assistant, портал
         * или тестовая форма.
         */

        dev["sms_sender"]["last_sent_time"] =
            new Date().toISOString();

        dev["sms_sender"]["last_message_text"] =
            messageText;

        dev["sms_sender"]["last_recipient_number"] =
            phoneNumber;

        try {
            log(
                "SMS: передаём команду для номера " +
                phoneNumber
            );

            Notify.sendSMS(
                phoneNumber,
                messageText
            );

            setLastResult(
                "Команда отправки передана"
            );

            log(
                "SMS: команда отправки передана для номера " +
                phoneNumber
            );

        } catch (error) {
            var errorText = String(error);

            setLastResult(
                "Ошибка: " + errorText
            );

            log(
                "SMS: ошибка Notify.sendSMS: " +
                errorText
            );
        }
    }
});
