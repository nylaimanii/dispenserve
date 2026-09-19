-- dispenserve fleet telemetry on Tiger Data (TimescaleDB).
-- Every row is one anonymous event from one machine: no people, no faces, no ids.
--
-- Apply with:  psql "$TIGER_DATABASE_URL" -f cloud/schema.sql
-- Safe to re-run.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS events (
    ts          timestamptz NOT NULL,
    machine_id  text        NOT NULL,
    bay         text        NOT NULL,
    event       text        NOT NULL CHECK (event IN ('dispensed', 'already_served', 'restocked'))
);

SELECT create_hypertable('events', by_range('ts', INTERVAL '1 day'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS events_machine_bay_ts ON events (machine_id, bay, ts DESC);

-- Items dispensed per bay per hour. The forecast reads its recent dispense rate from here.
CREATE MATERIALIZED VIEW IF NOT EXISTS dispensed_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket(INTERVAL '1 hour', ts) AS bucket,
    machine_id,
    bay,
    count(*) AS dispensed
FROM events
WHERE event = 'dispensed'
GROUP BY bucket, machine_id, bay
WITH NO DATA;

SELECT add_continuous_aggregate_policy('dispensed_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists     => TRUE);

-- Raw events are kept 30 days; the hourly rollup is kept a year for trends.
SELECT add_retention_policy('events', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('dispensed_hourly', INTERVAL '365 days', if_not_exists => TRUE);
