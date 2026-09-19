"""Snowflake sink: the same anonymous {machine_id, bay, event, ts} rows, batched into a table.

Table and daily-per-bay view: cloud/snowflake_schema.sql.
Env: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_WAREHOUSE,
     SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA (and optionally SNOWFLAKE_TABLE, default EVENTS).
"""

import re

from sinks.base import FIELDS, Sink

ENV_KEYS = ("ACCOUNT", "USER", "PASSWORD", "WAREHOUSE", "DATABASE", "SCHEMA")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def settings_from_env(env):
    """Returns (settings, missing_keys). env: callable like config.env."""
    settings = {k.lower(): env(f"SNOWFLAKE_{k}") for k in ENV_KEYS}
    missing = [f"SNOWFLAKE_{k}" for k in ENV_KEYS if not settings[k.lower()]]
    settings["table"] = env("SNOWFLAKE_TABLE", "EVENTS")
    return settings, missing


class SnowflakeSink(Sink):
    name = "snowflake"

    def __init__(self, settings, connect=None):
        table = settings.get("table") or "EVENTS"
        if not IDENTIFIER.match(table):
            raise ValueError(f"bad SNOWFLAKE_TABLE {table!r}")
        self.insert_sql = f"INSERT INTO {table} (MACHINE_ID, BAY, EVENT, TS) VALUES (%s, %s, %s, %s)"
        self.settings = {k: v for k, v in settings.items() if k != "table"}
        self._connect = connect
        self._conn = None

    def _connection(self):
        if self._conn is None:
            if self._connect is None:
                import snowflake.connector

                self._connect = lambda: snowflake.connector.connect(
                    **self.settings, login_timeout=15, network_timeout=30, client_session_keep_alive=False
                )
            self._conn = self._connect()
        return self._conn

    def send(self, batch):
        try:
            cur = self._connection().cursor()
            try:
                cur.executemany(self.insert_sql, [tuple(r[f] for f in FIELDS) for r in batch])
            finally:
                cur.close()
        except Exception:
            self.close()
            raise

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
