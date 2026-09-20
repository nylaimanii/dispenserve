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

-- Donor / organiser reporting: one row per day, in the language a funder cares about.
CREATE OR REPLACE VIEW IMPACT_DAILY AS
SELECT
    TO_DATE(TS)                                        AS DAY,
    COUNT_IF(EVENT = 'dispensed')                      AS PEOPLE_SERVED,   -- one item per person per day
    COUNT_IF(EVENT = 'dispensed')                      AS ITEMS_GIVEN,
    COUNT_IF(EVENT = 'already_served')                 AS REPEAT_VISITS_TURNED_AWAY,
    COUNT_IF(EVENT = 'restocked')                      AS RESTOCKS,
    COUNT(DISTINCT MACHINE_ID)                         AS MACHINES_ACTIVE,
    MIN(TS)                                            AS FIRST_EVENT,
    MAX(TS)                                            AS LAST_EVENT
FROM EVENTS
GROUP BY TO_DATE(TS);

-- Next-week demand, from the trailing 7-day average per weekday. Plain SQL, no ML credits
-- needed, so it keeps working on a free trial account.
CREATE OR REPLACE VIEW DEMAND_FORECAST AS
WITH daily AS (
    SELECT TO_DATE(TS) AS DAY, DAYNAME(TS) AS WEEKDAY, COUNT_IF(EVENT = 'dispensed') AS ITEMS
    FROM EVENTS
    WHERE TS >= DATEADD('day', -28, CURRENT_TIMESTAMP())
    GROUP BY 1, 2
)
SELECT
    WEEKDAY,
    ROUND(AVG(ITEMS), 1)  AS AVG_ITEMS,
    MAX(ITEMS)            AS BUSIEST_DAY,
    COUNT(*)              AS DAYS_OBSERVED,
    ROUND(AVG(ITEMS) * 1.2, 0) AS SUGGESTED_STOCK   -- 20% headroom so nobody leaves empty-handed
FROM daily
GROUP BY WEEKDAY;
