"""ClickHouse clients used by the OnchainDivers executable examples.

Project and indexer documentation: https://onchaindivers.com
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import clickhouse_connect
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError
from dotenv import dotenv_values


# The shared read-only users are capped at a small number of simultaneous
# queries, so a documentation build that fires many queries against a busy
# cluster hits transient failures (ClickHouse code 202) or network blips. These
# are safe to retry with backoff; permanent errors (bad SQL, missing table,
# access denied) are not and surface immediately.
_TRANSIENT_CODES = {159, 201, 202, 209, 210}  # timeout / quota / too-many / network
_MAX_RETRIES = 6


def _is_transient(error: Exception) -> bool:
    if isinstance(error, OperationalError):
        return True
    if getattr(error, "code", None) in _TRANSIENT_CODES:
        return True
    message = str(error)
    return any(
        marker in message
        for marker in (
            "TOO_MANY_SIMULTANEOUS_QUERIES",
            "Too many simultaneous",
            "TIMEOUT_EXCEEDED",
            "SOCKET_TIMEOUT",
        )
    )


def _retry(operation):
    """Run ``operation`` with exponential backoff on transient ClickHouse errors."""
    last_error: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            return operation()
        except (DatabaseError, OperationalError) as error:
            last_error = error
            if not _is_transient(error) or attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(min(30.0, 2.0 * (2 ** attempt)))
    assert last_error is not None
    raise last_error


class ClickHouseAccessor:
    """Access the main ClickHouse database using values from an env file."""

    host_key = "CLICKHOUSE_HOST"
    port_key = "CLICKHOUSE_PORT"
    username_key = "CLICKHOUSE_USERNAME"
    password_key = "CLICKHOUSE_PASSWORD"

    def __init__(self, env_path: str):
        config = self._load_config(env_path)
        self.host = self._required(config, self.host_key)
        self.username = self._required(config, self.username_key)
        self.password = self._required(config, self.password_key)
        self.port = int(config.get(self.port_key) or "8123")
        self.client = None

    @staticmethod
    def _load_config(env_path: str) -> Dict[str, Optional[str]]:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f".env file not found at {path}")
        return dict(dotenv_values(path))

    @staticmethod
    def _required(config: Dict[str, Optional[str]], key: str) -> str:
        value = config.get(key)
        if not value:
            raise ValueError(f"Missing required configuration value: {key}")
        return value

    @staticmethod
    def _host_and_port(value: str, default_port: int = 8123) -> tuple[str, int]:
        if ":" not in value:
            return value, default_port
        host, port = value.rsplit(":", 1)
        return host, int(port)

    def connect(self) -> None:
        # get_client issues a "SELECT version()" probe that can itself hit the
        # concurrency cap, so retry the connect too.
        self.client = _retry(
            lambda: clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                # Disable HTTP response compression. clickhouse-connect's compressed
                # block streaming can raise "IndexError: list index out of range" on
                # large result sets (e.g. the 250k-row wallet-fingerprint query);
                # plain responses are slightly larger but decode reliably.
                compress=False,
            )
        )

    def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    def query(
        self,
        sql: str,
        parameters: Optional[Union[List[Any], Dict[str, Any]]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        def run() -> List[Dict[str, Any]]:
            if not self.client:
                self.connect()
            result = self.client.query(sql, parameters=parameters, settings=settings)
            return [dict(zip(result.column_names, row)) for row in result.result_rows]

        def attempt() -> List[Dict[str, Any]]:
            try:
                return run()
            except (DatabaseError, OperationalError) as error:
                # Drop a poisoned connection so the retry reconnects cleanly.
                if _is_transient(error):
                    self.disconnect()
                raise

        return _retry(attempt)


class HyperLiquidAccessor(ClickHouseAccessor):
    """Access HyperLiquid data using its dedicated credentials."""

    def __init__(self, env_path: str):
        config = self._load_config(env_path)
        url = self._required(config, "HL_CLICKHOUSE_URL")
        self.host, self.port = self._host_and_port(url)
        self.username = self._required(config, "HL_CLICKHOUSE_USER")
        self.password = self._required(config, "HL_CLICKHOUSE_PASSWORD")
        self.client = None


class PolymarketAccessor(ClickHouseAccessor):
    """Access Polymarket data using its dedicated credentials."""

    def __init__(self, env_path: str):
        config = self._load_config(env_path)
        url = self._required(config, "POLY_CLICKHOUSE_URL")
        self.host, self.port = self._host_and_port(url)
        self.username = self._required(config, "POLY_CLICKHOUSE_USER")
        self.password = self._required(config, "POLY_CLICKHOUSE_PASSWORD")
        self.client = None


class RobinhoodAccessor(ClickHouseAccessor):
    """Access the separate Robinhood database using dedicated credentials."""

    def __init__(self, env_path: str):
        config = self._load_config(env_path)
        url = self._required(config, "ROBINHOOD_CLICKHOUSE_URL")
        self.host, self.port = self._host_and_port(url)
        self.username = self._required(config, "ROBINHOOD_CLICKHOUSE_USER")
        self.password = self._required(config, "ROBINHOOD_CLICKHOUSE_PASSWORD")
        self.client = None
