-- Разрушительный откат: удаляет эти таблицы и все их строки.
-- BEGIN/COMMIT удалены: транзакциями управляет драйвер — оберните файл в свою транзакцию,
-- или выполните атомарно через `psql -1 -f`.
DROP TABLE public.transactions;
DROP TABLE public.services;
DROP TABLE public.accounts;
