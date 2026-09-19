-- dispenserve anonymous telemetry in Snowflake.
-- Every row is one event from one machine: no people, no faces, no ids.
--
-- Run in a Snowflake worksheet (or snowsql) with the database and schema from your .env:
--   USE DATABASE <SNOWFLAKE_DATABASE>; USE SCHEMA <SNOWFLAKE_SCHEMA>;
-- Safe to re-run.

CREATE TABLE IF NOT EXISTS EVENTS (
    MACHINE_ID  STRING        NOT NULL,
    BAY         STRING        NOT NULL,
    EVENT       STRING        NOT NULL,  -- dispensed | already_served | restocked
    TS          TIMESTAMP_TZ  NOT NULL
);

-- One row per machine, bay and day.
CREATE OR REPLACE VIEW DAILY_BAY_SUMMARY AS
SELECT
    MACHINE_ID,
    BAY,
    TO_DATE(TS)                        AS DAY,
    COUNT_IF(EVENT = 'dispensed')      AS DISPENSED,
    COUNT_IF(EVENT = 'already_served') AS ALREADY_SERVED,
    COUNT_IF(EVENT = 'restocked')      AS RESTOCKS,
    MIN(TS)                            AS FIRST_EVENT,
    MAX(TS)                            AS LAST_EVENT
FROM EVENTS
GROUP BY MACHINE_ID, BAY, TO_DATE(TS);
