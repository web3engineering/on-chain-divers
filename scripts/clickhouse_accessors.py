"""ClickHouse clients used by the OnchainDivers executable examples.

Project and indexer documentation: https://onchaindivers.com
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import clickhouse_connect
from dotenv import dotenv_values


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
        self.client = clickhouse_connect.get_client(
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
        if not self.client:
            self.connect()
        result = self.client.query(sql, parameters=parameters, settings=settings)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]


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
