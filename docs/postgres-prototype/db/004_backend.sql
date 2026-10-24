-- db/004_backend.sql
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, email TEXT NOT NULL,
    balance_minor BIGINT NOT NULL DEFAULT 0 CHECK (balance_minor >= 0),
    withdraw_balance_minor BIGINT NOT NULL DEFAULT 0 CHECK (withdraw_balance_minor >= 0),
    bonus_balance_minor BIGINT NOT NULL DEFAULT 0 CHECK (bonus_balance_minor >= 0),
    bonus_spend_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    total_replenished_minor BIGINT NOT NULL DEFAULT 0 CHECK (total_replenished_minor >= 0)
);
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL, price_minor BIGINT NOT NULL CHECK (price_minor >= 0),
    auto_prolong BOOLEAN NOT NULL, payment_term TEXT,
    status TEXT NOT NULL CHECK (status IN ('active','suspended','prolong_wait','deleted','blocked')),
    expires_at TIMESTAMPTZ(3)
);
CREATE INDEX IF NOT EXISTS idx_services_customer ON services(customer_id);
CREATE INDEX IF NOT EXISTS idx_services_status   ON services(status);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    service_id TEXT, status TEXT NOT NULL CHECK (status IN ('performed','not_performed')),
    type TEXT NOT NULL CHECK (type IN ('prolong','order')),
    amount_minor BIGINT NOT NULL CHECK (amount_minor >= 0), created_at TIMESTAMPTZ(3)
);
CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_transactions_service  ON transactions(service_id);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
    expires_at TIMESTAMPTZ(3) NOT NULL, created_at TIMESTAMPTZ(3) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS login_attempts (
    client_key TEXT PRIMARY KEY, window_started_at TIMESTAMPTZ(3) NOT NULL,
    failures INTEGER NOT NULL CHECK (failures >= 1)
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
INSERT INTO app_state(key, value) VALUES
    ('model_settings', '{"prediction_horizon_days":30,"high_risk_min":70,"medium_risk_min":35,"weights":{"prolong_wait":55,"autoprolong_disabled":30,"insufficient_balance":45,"failed_prolong_payment":20}}'),
    ('source_kind', 'demo'),
    ('source_updated_at', to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"'))
ON CONFLICT (key) DO NOTHING;