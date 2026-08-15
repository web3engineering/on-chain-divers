#!/usr/bin/env python3
"""
Generate MDX documentation for ClickHouse database tables.

Project and indexer documentation: https://onchaindivers.com

This script queries ClickHouse databases (Solana, Polymarket, HyperLiquid)
and generates MDX documentation pages with table metadata, row counts,
date ranges, TTL, partitioning, and column information.

Usage:
    npm run generate
    # or: python scripts/generate_table_docs.py

The script reads credentials from the project's local .env file and outputs
MDX files to docs/pages/{db}/tables.mdx.

Features:
- Validates all columns have descriptions (crashes if unknown columns found)
- Includes data sample with Solscan links for Solana tables
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from dotenv import dotenv_values

from clickhouse_accessors import ClickHouseAccessor, HyperLiquidAccessor, PolymarketAccessor

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DOCS_PAGES_DIR = PROJECT_ROOT / "docs" / "pages"
COLUMN_DESCRIPTIONS_FILE = SCRIPT_DIR / "column_descriptions.yaml"

# Environment file
ENV_PATH = PROJECT_ROOT / ".env"

# Tables to include in documentation (whitelist per database)
# Empty set means include all tables
SOLANA_TABLES_WHITELIST: Set[str] = {
    "jito_tips",
    "max_caps",
    "meteora_dynamic_bonding_swaps",
    "meteora_swaps",
    "pfamm_migrations",
    "pumpfun_v2_swaps",
    "pumpfun_all_swaps",
    "pumpfun_amm_admin_set_coin_creator",
    "pumpfun_creator_fee_distributions",
    "pumpfun_token_creation",
    "pumpswap_all_swaps",
    "raydium_all_swaps",
    "raydium_cpmm_swaps",
    "raydium_launchpad_cpmm_migrations",
    "raydium_launchpad_migrations",
    "raydium_launchpad_swaps",
    "raydium_launchpad_token_creation",
    "sol_top_ups",
    "solana_blocks",
    "token_transfers",
    "tx_timestamps",
}

POLYMARKET_TABLES_WHITELIST: Set[str] = {
    "polymarket_order_filled_v3",
    "raw_market_meta",
    "raw_event_meta",
}

HYPERLIQUID_TABLES_WHITELIST: Set[str] = {
    "raw_node_fills_by_block",
    "view_perpetual_wallet",
    "view_wallet_position",
    "agg_fulfilled_order",
}

# Existing internal, backup, or superseded tables that are intentionally not
# published. Keeping these explicit ensures any newly discovered table fails
# validation instead of being silently filtered out.
TABLE_EXCLUSIONS: Dict[str, Set[str]] = {
    "solana": set(),
    "polymarket": {
        "polymarket_order_filled",
        "polymarket_order_filled_v2",
        "positions_converted",
    },
    "hyperliquid": {
        "_backup_raw_node_fills_by_block",
        "agg_perpetual_wallet",
        "agg_wallet_position",
        "dxn_funding",
        "perp_asset_meta",
        "perp_asset_stats",
        "spot_asset_meta",
        "spot_pair_meta",
    },
}

# Published tables per database (empty = publish all tables)
TABLE_WHITELISTS: Dict[str, Set[str]] = {
    "solana": SOLANA_TABLES_WHITELIST,
    "polymarket": POLYMARKET_TABLES_WHITELIST,
    "hyperliquid": HYPERLIQUID_TABLES_WHITELIST,
}

# ClickHouse database names (the actual database to query, not the connection default)
DATABASE_NAMES: Dict[str, str] = {
    "solana": "default",  # Solana uses the default database
    "polymarket": "polymarket",
    "hyperliquid": "hyperliquid",
}


class TableCoverageError(RuntimeError):
    """The live database tables differ from the documented table set."""

    def __init__(self, undocumented: List[str], missing: List[str]):
        super().__init__("Live table coverage does not match the documentation whitelist")
        self.undocumented = undocumented
        self.missing = missing


def exception_label(error: Exception) -> str:
    """Return useful diagnostics without exposing hosts, URLs, or credentials."""
    error_code = getattr(error, "code", None)
    suffix = f" (code {error_code})" if error_code is not None else ""
    return f"{type(error).__name__}{suffix}"


def load_column_descriptions() -> Dict[str, Dict[str, Dict[str, str]]]:
    """Load column descriptions from YAML file."""
    if not COLUMN_DESCRIPTIONS_FILE.exists():
        return {}

    with open(COLUMN_DESCRIPTIONS_FILE, "r") as f:
        data = yaml.safe_load(f) or {}

    return data


def format_bytes(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_number(num: int) -> str:
    """Format number with commas."""
    return f"{num:,}"


def load_env_config() -> Dict[str, str]:
    """Load environment variables from .env file."""
    if ENV_PATH.exists():
        return dotenv_values(ENV_PATH)
    return {}


def validate_column_descriptions(
    table_name: str,
    columns: List[Dict[str, Any]],
    column_descriptions: Dict[str, str],
    database_name: str,
) -> List[str]:
    """
    Validate that all columns have descriptions.
    Returns list of undocumented column names.
    """
    undocumented = []
    for col in columns:
        col_name = col["name"]
        if col_name not in column_descriptions:
            # Check if it has a default expression (those can be auto-documented)
            if not (col.get("default_kind") and col.get("default_expression")):
                undocumented.append(col_name)
    return undocumented


def get_signature_from_helius(slot: int, tx_idx: int, rpc_url: str) -> Optional[str]:
    """
    Fetch block from Helius RPC and get transaction signature by index.
    """
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBlock",
            "params": [
                slot,
                {
                    "encoding": "json",
                    "transactionDetails": "signatures",
                    "rewards": False,
                    "maxSupportedTransactionVersion": 0,
                }
            ]
        }

        req = urllib.request.Request(
            rpc_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))

        if "result" in result and result["result"]:
            signatures = result["result"].get("signatures", [])
            if tx_idx < len(signatures):
                return signatures[tx_idx]
    except Exception as e:
        print(f"      Warning: Could not fetch block {slot}: {exception_label(e)}")

    return None


def get_latest_row_sample(
    accessor: ClickHouseAccessor,
    table_name: str,
    columns: List[Dict[str, Any]],
    db_name: str = "default",
    rpc_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent row from a table for display as a sample.
    Returns dict with row data and optional Solscan link.
    """
    full_table_name = f"{db_name}.{table_name}"
    col_names = [col["name"] for col in columns]

    has_slot = "slot" in col_names
    has_tx_idx = "tx_idx" in col_names
    has_signature = "signature" in col_names

    try:
        # Build query for latest row
        if has_slot:
            query = f"SELECT * FROM {full_table_name} ORDER BY slot DESC LIMIT 1"
        else:
            # Try common timestamp columns
            for ts_col in ["block_time", "timestamp", "utc_fill_dttm", "block_timestamp"]:
                if ts_col in col_names:
                    query = f"SELECT * FROM {full_table_name} ORDER BY {ts_col} DESC LIMIT 1"
                    break
            else:
                # No ordering column found
                query = f"SELECT * FROM {full_table_name} LIMIT 1"

        result = accessor.query(query)

        if not result:
            return None

        row = result[0]

        # Get Solscan link
        solscan_link = None
        signature = None

        if has_signature:
            sig_value = row.get("signature")
            if sig_value:
                # Handle FixedString - strip null bytes and whitespace
                signature = str(sig_value).rstrip('\x00').strip()
                if signature:
                    solscan_link = f"https://solscan.io/tx/{signature}"

        elif has_slot and has_tx_idx and rpc_url:
            # Fetch signature from RPC
            slot = row.get("slot")
            tx_idx = row.get("tx_idx")
            if slot is not None and tx_idx is not None:
                signature = get_signature_from_helius(int(slot), int(tx_idx), rpc_url)
                if signature:
                    solscan_link = f"https://solscan.io/tx/{signature}"

        return {
            "row": row,
            "signature": signature,
            "solscan_link": solscan_link,
        }

    except Exception as e:
        print(
            f"      Warning: Could not get sample row for {table_name}: "
            f"{exception_label(e)}"
        )
        return None


def format_sample_value(value: Any) -> str:
    """Format a sample value for display in MDX."""
    if value is None:
        return "`NULL`"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"`{value:.6g}`"
        return f"`{value:,}`"
    if isinstance(value, datetime):
        return f"`{value.strftime('%Y-%m-%d %H:%M:%S')}`"
    if isinstance(value, str):
        # Handle FixedString null bytes
        value = value.rstrip('\x00').strip()
        if len(value) > 50:
            return f"`{value[:47]}...`"
        return f"`{value}`"
    return f"`{str(value)[:50]}`"


def get_table_list(
    accessor: ClickHouseAccessor,
    whitelist: Set[str],
    exclusions: Set[str],
    db_name: str = "default",
) -> List[str]:
    """Get tables and require complete coverage by the documentation whitelist."""
    result = accessor.query(
        f"SELECT name FROM system.tables WHERE database = '{db_name}' ORDER BY name"
    )
    all_tables = [row["name"] for row in result]

    if whitelist:
        live_tables = set(all_tables)
        undocumented = sorted(live_tables - whitelist - exclusions)
        missing = sorted(whitelist - live_tables)
        if undocumented or missing:
            raise TableCoverageError(undocumented, missing)
        return [table for table in all_tables if table in whitelist]
    return all_tables


def get_table_metadata(accessor: ClickHouseAccessor, table_name: str, db_name: str = "default") -> Dict[str, Any]:
    """Get table metadata (row count, size, TTL, partitioning)."""
    result = accessor.query(
        f"""
        SELECT
            total_rows,
            total_bytes,
            engine_full,
            partition_key
        FROM system.tables
        WHERE database = '{db_name}' AND name = '{table_name}'
        """
    )

    if result:
        row = result[0]
        engine_full = row.get("engine_full", "") or ""

        # Extract TTL from engine_full (e.g., "MergeTree ... TTL block_time + INTERVAL 30 DAY")
        ttl = None
        if "TTL " in engine_full:
            ttl_start = engine_full.find("TTL ")
            if ttl_start != -1:
                # Extract TTL clause (until next keyword or end)
                ttl_part = engine_full[ttl_start + 4:]
                # TTL clause ends at SETTINGS or end of string
                for end_keyword in [" SETTINGS", " ORDER BY", " PARTITION BY"]:
                    if end_keyword in ttl_part:
                        ttl_part = ttl_part[:ttl_part.find(end_keyword)]
                ttl = ttl_part.strip()

        return {
            "total_rows": row.get("total_rows", 0) or 0,
            "total_bytes": row.get("total_bytes", 0) or 0,
            "ttl": ttl,
            "partition_key": row.get("partition_key", "") or "",
        }
    return {"total_rows": 0, "total_bytes": 0, "ttl": None, "partition_key": ""}


def get_column_info(accessor: ClickHouseAccessor, table_name: str, db_name: str = "default") -> List[Dict[str, Any]]:
    """Get column information for a table."""
    result = accessor.query(
        f"""
        SELECT
            name,
            type,
            default_kind,
            default_expression
        FROM system.columns
        WHERE database = '{db_name}' AND table = '{table_name}'
        ORDER BY position
        """
    )
    return result


def has_column(columns: List[Dict[str, Any]], column_name: str) -> bool:
    """Check if a table has a specific column."""
    return any(col["name"] == column_name for col in columns)


def get_first_non_default_date(
    accessor: ClickHouseAccessor,
    table_name: str,
    column_name: str,
    default_expression: str,
    has_slot: bool,
    db_name: str = "default",
) -> Optional[str]:
    """Get the date when a column first had a non-default value.

    For columns with defaults, this finds when the column started being populated.
    Uses slot ordering for efficiency on Solana tables.
    """
    full_table_name = f"{db_name}.{table_name}"
    try:
        # Build the WHERE clause based on default type
        # Handle common default expressions
        default_expr = default_expression.strip()

        # Determine the condition for non-default values
        if default_expr == "''":
            where_clause = f"{column_name} != ''"
        elif default_expr == "0":
            where_clause = f"{column_name} != 0"
        elif default_expr.startswith("'") and default_expr.endswith("'"):
            # String literal default
            where_clause = f"{column_name} != {default_expr}"
        elif default_expr.lower() in ("null", "nullable"):
            where_clause = f"{column_name} IS NOT NULL"
        else:
            # For complex expressions, check if not equal to the expression
            where_clause = f"{column_name} != ({default_expr})"

        if has_slot:
            # Use slot ordering for efficiency
            result = accessor.query(
                f"""
                SELECT block_time
                FROM {full_table_name}
                WHERE {where_clause}
                ORDER BY slot ASC
                LIMIT 1
                """
            )
        else:
            # Fall back to timestamp ordering
            result = accessor.query(
                f"""
                SELECT block_time
                FROM {full_table_name}
                WHERE {where_clause}
                ORDER BY block_time ASC
                LIMIT 1
                """
            )

        if result and result[0].get("block_time"):
            dt = result[0]["block_time"]
            if isinstance(dt, datetime):
                return dt.strftime("%Y-%m-%d")
            return str(dt)[:10]

    except Exception as e:
        # Silently fail - this is optional info
        pass

    return None


def get_date_range_by_slot(
    accessor: ClickHouseAccessor, table_name: str, db_name: str = "default"
) -> Optional[Dict[str, Any]]:
    """Get date range for a table using block_time, ordered by slot (optimized for index)."""
    full_table_name = f"{db_name}.{table_name}"
    try:
        # Get first record by slot (ascending)
        first_result = accessor.query(
            f"""
            SELECT block_time as first_record
            FROM {full_table_name}
            ORDER BY slot ASC
            LIMIT 1
            """
        )

        # Get last record by slot (descending)
        last_result = accessor.query(
            f"""
            SELECT block_time as last_record
            FROM {full_table_name}
            ORDER BY slot DESC
            LIMIT 1
            """
        )

        if first_result and last_result:
            return {
                "first_record": first_result[0]["first_record"],
                "last_record": last_result[0]["last_record"],
            }
    except Exception as e:
        print(
            f"    Warning: Could not get date range for {table_name}: "
            f"{exception_label(e)}"
        )
    return None


def get_date_range_generic(
    accessor: ClickHouseAccessor, table_name: str, timestamp_columns: List[str], db_name: str = "default"
) -> Optional[Dict[str, Any]]:
    """Get date range using MIN/MAX on timestamp columns (fallback method)."""
    full_table_name = f"{db_name}.{table_name}"
    for col in timestamp_columns:
        try:
            result = accessor.query(
                f"""
                SELECT
                    MIN({col}) as first_record,
                    MAX({col}) as last_record
                FROM {full_table_name}
                """
            )
            if result and result[0].get("first_record"):
                return {
                    "first_record": result[0]["first_record"],
                    "last_record": result[0]["last_record"],
                }
        except Exception:
            continue
    return None


def get_date_range(
    accessor: ClickHouseAccessor,
    table_name: str,
    columns: List[Dict[str, Any]],
    use_slot_optimization: bool = True,
    db_name: str = "default",
) -> Optional[Dict[str, Any]]:
    """Get date range for a table."""
    # Check if table has block_time and slot columns
    has_block_time = has_column(columns, "block_time")
    has_slot = has_column(columns, "slot")

    # Use slot-optimized query for Solana tables with both columns
    if use_slot_optimization and has_block_time and has_slot:
        return get_date_range_by_slot(accessor, table_name, db_name)

    # Fallback to generic timestamp columns
    timestamp_columns = ["block_time", "timestamp", "time", "created_at", "event_time"]
    return get_date_range_generic(accessor, table_name, timestamp_columns, db_name)


def generate_table_mdx(
    table_name: str,
    metadata: Dict[str, Any],
    columns: List[Dict[str, Any]],
    date_range: Optional[Dict[str, Any]],
    column_descriptions: Dict[str, str],
    database_name: str,
    accessor: Optional[ClickHouseAccessor] = None,
    use_slot_optimization: bool = False,
    db_name: str = "default",
    sample_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate MDX content for a single table."""
    lines = []

    lines.append(f"### {table_name}")
    lines.append("")

    # Stats
    lines.append("| Statistic | Value |")
    lines.append("|-----------|-------|")
    lines.append(f"| **Rows** | {format_number(metadata['total_rows'])} |")
    lines.append(f"| **Size** | {format_bytes(metadata['total_bytes'])} |")

    if date_range:
        first = date_range["first_record"]
        last = date_range["last_record"]
        if isinstance(first, datetime):
            first_str = first.strftime("%Y-%m-%d")
        else:
            first_str = str(first)[:10]
        if isinstance(last, datetime):
            last_str = last.strftime("%Y-%m-%d")
        else:
            last_str = str(last)[:10]
        lines.append(f"| **First Record** | {first_str} |")
        lines.append(f"| **Last Record** | {last_str} |")

    # Add partitioning info if available
    if metadata.get("partition_key"):
        lines.append(f"| **Partition Key** | `{metadata['partition_key']}` |")

    # Add TTL info if available
    if metadata.get("ttl"):
        lines.append(f"| **TTL** | `{metadata['ttl']}` |")

    lines.append("")

    # Check if table has slot column for optimization
    has_slot = has_column(columns, "slot")

    # Columns
    lines.append("**Columns:**")
    lines.append("")
    lines.append("| Column | Type | Description |")
    lines.append("|--------|------|-------------|")

    for col in columns:
        col_name = col["name"]
        col_type = col["type"]
        description = column_descriptions.get(col_name, "")

        # Add default info and first populated date if column has default
        if col.get("default_kind") and col.get("default_expression"):
            default_expr = col["default_expression"]

            # Try to find when column first got populated (non-default value)
            first_populated = None
            if accessor:
                first_populated = get_first_non_default_date(
                    accessor, table_name, col_name, default_expr, has_slot, db_name
                )

            if description:
                # Append default/populated info to existing description
                if first_populated:
                    description += f" *(populated since {first_populated})*"
            else:
                # No manual description, show default and populated date
                if first_populated:
                    description = f"Default: `{default_expr}` *(populated since {first_populated})*"
                else:
                    description = f"Default: `{default_expr}`"

        # Escape pipe characters in type
        col_type = col_type.replace("|", "\\|")

        lines.append(f"| `{col_name}` | `{col_type}` | {description} |")

    lines.append("")

    # Add sample data section
    if sample_data and sample_data.get("row"):
        row = sample_data["row"]
        solscan_link = sample_data.get("solscan_link")

        lines.append("**Latest Record Sample:**")
        lines.append("")

        if solscan_link:
            lines.append(f"[View on Solscan]({solscan_link})")
            lines.append("")

        # Show a subset of interesting columns (first 8 non-null values)
        lines.append("| Column | Value |")
        lines.append("|--------|-------|")

        shown = 0
        for col in columns:
            if shown >= 8:
                break
            col_name = col["name"]
            value = row.get(col_name)
            if value is not None:
                formatted = format_sample_value(value)
                lines.append(f"| `{col_name}` | {formatted} |")
                shown += 1

        lines.append("")

    return "\n".join(lines)


def generate_database_mdx(
    database_name: str,
    display_name: str,
    description: str,
    accessor: ClickHouseAccessor,
    column_descriptions: Dict[str, Dict[str, str]],
    table_whitelist: Set[str],
    table_exclusions: Set[str],
    use_slot_optimization: bool = False,
    db_name: str = "default",
    rpc_url: Optional[str] = None,
) -> tuple[str, Dict[str, List[str]]]:
    """Generate complete MDX file for a database.

    Returns:
        tuple: (mdx_content, undocumented_columns_dict)
        undocumented_columns_dict maps table_name -> list of undocumented column names
    """
    lines = []
    undocumented_columns: Dict[str, List[str]] = {}

    lines.append(f"# {display_name}")
    lines.append("")
    lines.append(description)
    lines.append("")
    lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("")

    # Import ClickHouse component (relative path from pages/{db}/tables.mdx)
    lines.append("import { ClickHouseSqlExample } from '../../components/ClickHouseSqlExample'")
    lines.append("")

    tables = get_table_list(accessor, table_whitelist, table_exclusions, db_name)

    if not tables:
        lines.append("*No tables found in this database.*")
        return "\n".join(lines), undocumented_columns

    # Validate the live schema before running expensive metadata, date-range,
    # and sample queries. A schema with missing descriptions must never produce
    # publishable output.
    common_descriptions = column_descriptions.get("_common", {})
    columns_by_table: Dict[str, List[Dict[str, Any]]] = {}
    descriptions_by_table: Dict[str, Dict[str, str]] = {}

    for table_name in tables:
        print(f"    Validating schema for {table_name}...")
        columns = get_column_info(accessor, table_name, db_name)
        table_descriptions = column_descriptions.get(table_name, {})
        merged_descriptions = {**common_descriptions, **table_descriptions}

        columns_by_table[table_name] = columns
        descriptions_by_table[table_name] = merged_descriptions

        undocumented = validate_column_descriptions(
            table_name,
            columns,
            merged_descriptions,
            database_name,
        )
        if undocumented:
            undocumented_columns[table_name] = undocumented

    if undocumented_columns:
        return "", undocumented_columns

    lines.append(f"## Tables ({len(tables)})")
    lines.append("")

    # Table of contents
    lines.append("| Table | Rows | Size |")
    lines.append("|-------|------|------|")

    table_data = []
    for table_name in tables:
        print(f"    Getting metadata for {table_name}...")
        metadata = get_table_metadata(accessor, table_name, db_name)
        table_data.append((table_name, metadata))
        lines.append(
            # Vocs preserves underscores in heading IDs. Keep the fragment
            # byte-for-byte aligned with the generated ``### table_name``.
            f"| [{table_name}](#{table_name.lower()}) | "
            f"{format_number(metadata['total_rows'])} | "
            f"{format_bytes(metadata['total_bytes'])} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed table documentation
    for table_name, metadata in table_data:
        print(f"    Documenting {table_name}...")
        columns = columns_by_table[table_name]
        date_range = get_date_range(accessor, table_name, columns, use_slot_optimization, db_name)
        merged_descriptions = descriptions_by_table[table_name]

        # Get sample data (only for Solana tables with RPC access)
        sample_data = None
        if database_name == "solana":
            print(f"      Getting sample row...")
            sample_data = get_latest_row_sample(accessor, table_name, columns, db_name, rpc_url)

        table_mdx = generate_table_mdx(
            table_name,
            metadata,
            columns,
            date_range,
            merged_descriptions,
            database_name,
            accessor=accessor,
            use_slot_optimization=use_slot_optimization,
            db_name=db_name,
            sample_data=sample_data,
        )
        lines.append(table_mdx)

        # Add example query
        lines.append("**Example Query:**")
        lines.append("")
        lines.append(f"<ClickHouseSqlExample database=\"{database_name}\">")
        lines.append(f"SELECT * FROM {table_name} LIMIT 10")
        lines.append("</ClickHouseSqlExample>")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines), undocumented_columns


def main():
    """Main function to generate all table documentation."""
    strict_generation = os.environ.get("DOCS_STRICT_GENERATION") == "1"
    generation_errors: List[str] = []

    print("Loading column descriptions...")
    all_descriptions = load_column_descriptions()
    print(f"Using environment file: {ENV_PATH}")

    # Load env config for RPC_URL
    env_config = load_env_config()
    rpc_url = env_config.get("RPC_URL")
    if rpc_url:
        print("RPC URL configured")
    else:
        print("Warning: RPC_URL not found in .env - will skip signature lookups for tables without signature column")

    # Check for .env file
    if not ENV_PATH.exists():
        print(f"Error: .env file not found at {ENV_PATH}")
        if strict_generation:
            sys.exit(1)
        print("Creating placeholder documentation files...")
        create_placeholder_docs()
        return

    # Track all undocumented columns across all databases
    all_undocumented: Dict[str, Dict[str, List[str]]] = {}

    databases = [
        {
            "name": "solana",
            "display_name": "Solana Tables",
            "description": "Tables containing Solana blockchain data including DEX swaps, token trades, and transaction information.",
            "accessor_class": ClickHouseAccessor,
            "use_slot_optimization": True,  # Solana tables have slot index
        },
        {
            "name": "polymarket",
            "display_name": "Polymarket Tables",
            "description": "Tables containing Polymarket prediction market data including order books, trades, and market information.",
            "accessor_class": PolymarketAccessor,
            "use_slot_optimization": False,
        },
        {
            "name": "hyperliquid",
            "display_name": "HyperLiquid Tables",
            "description": "Tables containing HyperLiquid perpetual exchange data including trades, orders, and funding rates.",
            "accessor_class": HyperLiquidAccessor,
            "use_slot_optimization": False,
        },
    ]

    for db in databases:
        db_name = db["name"]
        # Output to docs/pages/{db_name}/tables.mdx to match existing structure
        output_dir = DOCS_PAGES_DIR / db_name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "tables.mdx"

        print(f"\nProcessing {db['display_name']}...")

        accessor = None
        try:
            accessor = db["accessor_class"](env_path=str(ENV_PATH))
            accessor.connect()

            column_descriptions = all_descriptions.get(db_name, {})
            table_whitelist = TABLE_WHITELISTS.get(db_name, set())
            table_exclusions = TABLE_EXCLUSIONS.get(db_name, set())
            clickhouse_db_name = DATABASE_NAMES.get(db_name, "default")

            mdx_content, undocumented = generate_database_mdx(
                db_name,
                db["display_name"],
                db["description"],
                accessor,
                column_descriptions,
                table_whitelist,
                table_exclusions,
                db.get("use_slot_optimization", False),
                clickhouse_db_name,
                rpc_url=rpc_url,
            )

            if undocumented:
                all_undocumented[db_name] = undocumented
                continue

            with open(output_file, "w") as f:
                f.write(mdx_content)

            print(f"  Generated: {output_file}")
        except Exception as e:
            generation_errors.append(db_name)
            print(f"  Error generating {db_name}: {exception_label(e)}")
            if isinstance(e, TableCoverageError):
                for table_name in e.undocumented:
                    print(f"    Undocumented live table: {table_name}")
                for table_name in e.missing:
                    print(f"    Documented table missing from database: {table_name}")
            if not strict_generation:
                print(f"  Creating placeholder for {db_name}...")
                create_placeholder_file(
                    db_name,
                    db["display_name"],
                    db["description"],
                    "Data source unavailable.",
                )
        finally:
            if accessor:
                accessor.disconnect()

    if generation_errors and strict_generation:
        print("\nERROR: Documentation generation failed for:")
        for db_name in generation_errors:
            print(f"  - {db_name}")
        sys.exit(1)

    # Check for undocumented columns and crash if any found
    if all_undocumented:
        print("\n" + "=" * 70)
        print("ERROR: Undocumented columns found!")
        print("=" * 70)
        print("\nAdd descriptions to scripts/column_descriptions.yaml for these columns:\n")

        for db_name, tables in all_undocumented.items():
            print(f"{db_name}:")
            for table_name, columns in tables.items():
                print(f"  {table_name}:")
                for col in columns:
                    print(f"    {col}: \"\"")
            print()

        print("=" * 70)
        sys.exit(1)

    print("\nDone!")


def create_placeholder_docs():
    """Create placeholder documentation files when database is unavailable."""
    databases = [
        ("solana", "Solana Tables", "Tables containing Solana blockchain data."),
        ("polymarket", "Polymarket Tables", "Tables containing Polymarket prediction market data."),
        ("hyperliquid", "HyperLiquid Tables", "Tables containing HyperLiquid perpetual trading data."),
    ]

    for db_name, display_name, description in databases:
        create_placeholder_file(db_name, display_name, description)


def create_placeholder_file(
    db_name: str, display_name: str, description: str, error: str = ""
):
    """Create a placeholder MDX file for a database."""
    output_dir = DOCS_PAGES_DIR / db_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "tables.mdx"

    lines = [
        f"# {display_name}",
        "",
        description,
        "",
        "import { ClickHouseSqlExample } from '../../components/ClickHouseSqlExample'",
        "",
        ":::note",
        "Table documentation is auto-generated. Run `npm run generate` to update.",
        ":::",
        "",
    ]

    if error:
        lines.extend([
            ":::warning",
            f"Could not connect to database: {error}",
            ":::",
            "",
        ])

    lines.extend([
        "## Example Query",
        "",
        f"<ClickHouseSqlExample database=\"{db_name}\">",
        "SELECT * FROM system.tables LIMIT 10",
        "</ClickHouseSqlExample>",
    ])

    with open(output_file, "w") as f:
        f.write("\n".join(lines))

    print(f"  Created placeholder: {output_file}")


if __name__ == "__main__":
    main()
