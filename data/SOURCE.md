# Походження даних

Сирі таблиці (`buildings.json`, `troops.json`, …) — копія `assets/static_data`
з репозиторію [ClashKingInc/ClashKingAssets](https://github.com/ClashKingInc/ClashKingAssets),
ліцензія GNU GPL v3. Оновлює їх воркфлоу `.github/workflows/refresh-data.yml`.

`ref.min.json` — той самий довідник, з якого викинуто все, чого не читає
застосунок (описи, TID, бойова статистика). Саме його вантажить сайт: один
запит замість п'ятнадцяти.

`meta.json` — версія довідника, коміт і дата upstream, лічильники записів.
Клієнт звіряє за нею свій кеш, а в статус-рядку показує вік даних.
Дату останнього оновлення шукай там, а не тут.

Не афілійовано з Supercell. Supercell не несе відповідальності за цей контент.
Див. [Fan Content Policy](https://supercell.com/en/fan-content-policy/).
