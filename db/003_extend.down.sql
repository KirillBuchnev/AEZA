BEGIN;

DROP INDEX IF EXISTS public.transactions_service_performed_idx;
DROP INDEX IF EXISTS public.transactions_performed_idx;
DROP INDEX IF EXISTS public.services_status_expires_idx;
DROP INDEX IF EXISTS public.services_expires_at_idx;
DROP INDEX IF EXISTS public.services_status_idx;

DROP TABLE IF EXISTS public."modelSettings";
DROP TABLE IF EXISTS public.users;

COMMIT;
