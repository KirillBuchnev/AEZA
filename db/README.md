## Статус в проекте

- Рабочий бэкенд хранит данные в PostgreSQL (см. `README.md` в корне). Его схема создаётся кодом в `backend/app/database.py` (`_schema_statements`); эта папка описывает кейс и справочную схему.
- `001`–`003` — схема и тестовый набор из кейса (`accounts`, `services`, `transactions`), а также целевое описание для PostgreSQL. Из `002_seed.sql` собирается снимок кейса для приложения: `backend/scripts/build_case_snapshot.py`.
- Соответствие: `accounts` = клиент (`customers` в API), `services.ownerId` = владелец услуги, `services.paymentTerm` = срок оплаты.

# База данных «Анализатор рисков оттока»

PostgreSQL 16. Схема спроектирована по методологии книги
«Грокаем проектирование реляционных баз данных» (Цян Хао, Михаил Цикердекис, 2026).

## Состав

| Файл | Назначение |
|---|---|
| `001_schema.up.sql` / `001_schema.down.sql` | базовая схема (accounts, services, transactions) — дана кейсом |
| `002_seed.sql` | фикстуры 10 аккаунтов / 30 услуг / 100 транзакций + setval (дан кейсом) |
| `003_extend.sql` / `003_extend.down.sql` | расширение: таблицы `users` и `modelSettings`, 5 индексов |
| `Проектирование_БД.md` | полный проект БД по методологии книги: требования, ER, нормализация, безопасность |
| `Описание_БД.docx` | подробное описание всех таблиц и полей |

## Применение

```bash
psql -1 -d churn -f db/001_schema.up.sql
psql -1 -d churn -f db/002_seed.sql
psql -1 -d churn -f db/003_extend.sql
```

Обратный откат расширения: `psql -1 -d churn -f db/003_extend.down.sql`.

## Транзакции

`BEGIN`/`COMMIT` из SQL-файлов удалены: транзакцией управляет тот, кто запускает файл
(TRUNCATE сид не содержит, очистка выполняется снаружи). Приложение эти файлы не исполняет:
схему создаёт `backend/app/database.py`, а данные кейса приходят снимком из
`backend/scripts/build_case_snapshot.py`.
При прогоне через psql атомарность восстанавливается флагом `psql -1 -f`
(весь файл одной транзакцией). `LOCK TABLE` и защита «сид только на пустые
таблицы» сохранены.

## Снапшот «стереть и залить» (PUT /api/v1/source/snapshot)

```sql
TRUNCATE TABLE transactions, services, accounts RESTART IDENTITY CASCADE;
-- затем повторное исполнение 002_seed.sql (завершается setval по каждой таблице)
```

`users` и `modelSettings` не затрагиваются: операторы и коэффициенты переживают заливку нового среза.
Identity после перезаливки продолжается с 11 / 31 / 101 без коллизий.

## Проверено на живом PostgreSQL 16.4 (2026-10-25, после удаления BEGIN/COMMIT)

- миграции 001 → 002 → 003 применяются без ошибок; итог: 10/30/100 строк, singleton modelSettings (веса 1.000, пороги 40/70);
- негативные тесты 14/14: CHECK (amount 1001/-5, performed без даты, performedAt < createdAt, диапазоны весов и порогов), FK RESTRICT (чужой serviceId, DELETE аккаунта с услугами), UNIQUE (дубль username);
- гард сида: повторный запуск 002 отклоняется («Seed requires empty tables»);
- снапшот: перезаливка без сирот, целостность сохранена, users/modelSettings переживают;
- обратимость: down/up цикл 003 проходит.

## Ключевые решения

- деньги — `bigint`/`integer` в еврокопейках (€1 = 100), CHECK на неотрицательность;
- время — `timestamptz(3)`, UTC;
- `transactions.amount` — цена на момент операции (3НФ, аналог product_price из книги);
- коэффициенты риск-модели живут в БД (singleton `modelSettings`, CHECK id = 1) — persistence после перезапуска сервиса;
- пароли — только bcrypt-хэши в `char(60)`.
