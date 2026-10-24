-- Destructive rollback: removes these tables and all their rows.
-- BEGIN/COMMIT removed for driver-managed transactions: wrap in your own transaction,
-- or run atomically via `psql -1 -f`.
DROP TABLE public.transactions;
DROP TABLE public.services;
DROP TABLE public.accounts;
