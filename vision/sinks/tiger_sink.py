"""Tiger Data (TimescaleDB / Postgres) sink: inserts into the events hypertable (cloud/schema.sql)."""

from sinks.base import FIELDS, Sink

INSERT_SQL = "INSERT INTO events (machine_id, bay, event, ts) VALUES (%s, %s, %s, %s)"


class TigerSink(Sink):
    name = "tiger"

    def __init__(self, database_url, connect=None):
        self.database_url = database_url
        self._connect = connect
        self._conn = None

    def _connection(self):
        if self._conn is None or getattr(self._conn, "closed", False):
            if self._connect is None:
                import psycopg

                self._connect = lambda: psycopg.connect(self.database_url, connect_timeout=5, autocommit=True)
            self._conn = self._connect()
        return self._conn

    def send(self, batch):
        try:
            with self._connection().cursor() as cur:
                cur.executemany(INSERT_SQL, [tuple(r[f] for f in FIELDS) for r in batch])
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
