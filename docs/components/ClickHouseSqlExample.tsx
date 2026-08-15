import React, { useState, useCallback, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table';

type Database = 'solana' | 'polymarket' | 'hyperliquid' | 'robinhood';

interface Credentials {
  host: string;
  username: string;
  password: string;
}

interface ClickHouseSqlExampleProps {
  database: Database;
  children: string;
}

const DATABASE_DEFAULTS: Record<Database, { host: string; port: string }> = {
  solana: { host: '', port: '8443' },
  polymarket: { host: '', port: '8443' },
  hyperliquid: { host: '', port: '8443' },
  robinhood: { host: '', port: '8443' },
};

const CLICKHOUSE_DATABASES: Record<Database, string> = {
  solana: 'default',
  polymarket: 'polymarket',
  hyperliquid: 'hyperliquid',
  robinhood: 'robinhood',
};

const STORAGE_KEY_PREFIX = 'clickhouse_credentials_';

function getStoredCredentials(database: Database): Credentials | null {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY_PREFIX + database);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {
    // Ignore errors
  }
  return null;
}

function storeCredentials(database: Database, credentials: Credentials): void {
  try {
    sessionStorage.setItem(
      STORAGE_KEY_PREFIX + database,
      JSON.stringify(credentials)
    );
  } catch {
    // Ignore errors
  }
}

function clearCredentials(database: Database): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY_PREFIX + database);
  } catch {
    // Ignore errors
  }
}

interface CredentialModalProps {
  database: Database;
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (credentials: Credentials) => void;
  error?: string;
}

function CredentialModal({
  database,
  isOpen,
  onClose,
  onSubmit,
  error,
}: CredentialModalProps) {
  const defaults = DATABASE_DEFAULTS[database];
  const [host, setHost] = useState(defaults.host);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({ host, username, password });
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: 'var(--vocs-color_background)',
          borderRadius: '8px',
          padding: '24px',
          minWidth: '400px',
          maxWidth: '90%',
          border: '1px solid var(--vocs-color_border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ marginTop: 0, marginBottom: '16px' }}>
          ClickHouse Credentials ({database})
        </h3>

        {error && (
          <div
            style={{
              backgroundColor: 'var(--vocs-color_dangerBackground)',
              color: 'var(--vocs-color_danger)',
              padding: '12px',
              borderRadius: '4px',
              marginBottom: '16px',
              fontSize: '14px',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '16px' }}>
            <label
              style={{
                display: 'block',
                marginBottom: '4px',
                fontSize: '14px',
              }}
            >
              Host (with port, e.g., host:8443)
            </label>
            <input
              type="text"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="clickhouse.example.com:8443"
              required
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '4px',
                border: '1px solid var(--vocs-color_border)',
                backgroundColor: 'var(--vocs-color_backgroundDark)',
                color: 'var(--vocs-color_text)',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label
              style={{
                display: 'block',
                marginBottom: '4px',
                fontSize: '14px',
              }}
            >
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '4px',
                border: '1px solid var(--vocs-color_border)',
                backgroundColor: 'var(--vocs-color_backgroundDark)',
                color: 'var(--vocs-color_text)',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: '24px' }}>
            <label
              style={{
                display: 'block',
                marginBottom: '4px',
                fontSize: '14px',
              }}
            >
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '4px',
                border: '1px solid var(--vocs-color_border)',
                backgroundColor: 'var(--vocs-color_backgroundDark)',
                color: 'var(--vocs-color_text)',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 16px',
                borderRadius: '4px',
                border: '1px solid var(--vocs-color_border)',
                backgroundColor: 'transparent',
                color: 'var(--vocs-color_text)',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              style={{
                padding: '8px 16px',
                borderRadius: '4px',
                border: 'none',
                backgroundColor: 'var(--vocs-color_accent)',
                color: 'white',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              Connect & Run
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface ResultTableProps {
  data: Record<string, unknown>[];
}

function ResultTable({ data }: ResultTableProps) {
  const columnHelper = createColumnHelper<Record<string, unknown>>();

  const columns = useMemo(() => {
    if (data.length === 0) return [];
    const keys = Object.keys(data[0]);
    return keys.map((key) =>
      columnHelper.accessor(key, {
        header: key,
        cell: (info) => {
          const value = info.getValue();
          if (value === null || value === undefined) return 'NULL';
          if (typeof value === 'object') return JSON.stringify(value);
          return String(value);
        },
      })
    );
  }, [data, columnHelper]);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (data.length === 0) {
    return <div style={{ padding: '12px', fontStyle: 'italic' }}>No results</div>;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: '13px',
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  style={{
                    textAlign: 'left',
                    padding: '8px 12px',
                    borderBottom: '2px solid var(--vocs-color_border)',
                    backgroundColor: 'var(--vocs-color_backgroundDark)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  style={{
                    padding: '8px 12px',
                    borderBottom: '1px solid var(--vocs-color_border)',
                    whiteSpace: 'nowrap',
                    maxWidth: '300px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ClickHouseSqlExample({ database, children }: ClickHouseSqlExampleProps) {
  const query = typeof children === 'string' ? children.trim() : '';

  const [showModal, setShowModal] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [results, setResults] = useState<Record<string, unknown>[] | null>(null);
  const [hasCredentials, setHasCredentials] = useState(
    () => getStoredCredentials(database) !== null
  );

  const executeQuery = useCallback(
    async (credentials: Credentials) => {
      setIsLoading(true);
      setError(undefined);
      setResults(null);

      try {
        // Parse host and port
        let host = credentials.host;
        let port = '8443';
        if (host.includes(':')) {
          const parts = host.split(':');
          host = parts[0];
          port = parts[1];
        }

        const protocol = port === '8443' ? 'https' : 'http';
        const databaseName = encodeURIComponent(CLICKHOUSE_DATABASES[database]);
        const url = `${protocol}://${host}:${port}/?default_format=JSON&database=${databaseName}`;

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'text/plain',
            'X-ClickHouse-User': credentials.username,
            'X-ClickHouse-Key': credentials.password,
          },
          body: query,
        });

        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `HTTP ${response.status}`);
        }

        const json = await response.json();
        storeCredentials(database, credentials);
        setHasCredentials(true);
        setResults(json.data || []);
        setShowModal(false);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        if (message.includes('Authentication') || message.includes('401')) {
          setError('Authentication failed. Please check your credentials.');
          clearCredentials(database);
          setHasCredentials(false);
        } else {
          setError(message);
        }
      } finally {
        setIsLoading(false);
      }
    },
    [database, query]
  );

  const handleRun = useCallback(() => {
    const stored = getStoredCredentials(database);
    if (stored) {
      executeQuery(stored);
    } else {
      setShowModal(true);
    }
  }, [database, executeQuery]);

  const handleClearCredentials = useCallback(() => {
    clearCredentials(database);
    setHasCredentials(false);
    setResults(null);
  }, [database]);

  return (
    <div
      style={{
        border: '1px solid var(--vocs-color_border)',
        borderRadius: '8px',
        overflow: 'hidden',
        marginBottom: '16px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          backgroundColor: 'var(--vocs-color_backgroundDark)',
          borderBottom: '1px solid var(--vocs-color_border)',
        }}
      >
        <span style={{ fontSize: '12px', color: 'var(--vocs-color_text2)' }}>
          ClickHouse ({database})
        </span>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {hasCredentials && (
            <button
              onClick={handleClearCredentials}
              style={{
                padding: '4px 8px',
                borderRadius: '4px',
                border: '1px solid var(--vocs-color_border)',
                backgroundColor: 'transparent',
                color: 'var(--vocs-color_text2)',
                cursor: 'pointer',
                fontSize: '12px',
              }}
            >
              Clear Credentials
            </button>
          )}
          <button
            onClick={handleRun}
            disabled={isLoading}
            style={{
              padding: '4px 12px',
              borderRadius: '4px',
              border: 'none',
              backgroundColor: isLoading
                ? 'var(--vocs-color_border)'
                : 'var(--vocs-color_accent)',
              color: 'white',
              cursor: isLoading ? 'wait' : 'pointer',
              fontSize: '12px',
            }}
          >
            {isLoading ? 'Running...' : 'Run'}
          </button>
        </div>
      </div>

      <pre
        style={{
          margin: 0,
          padding: '16px',
          backgroundColor: 'var(--vocs-color_codeTitleBackground)',
          overflow: 'auto',
          fontSize: '14px',
        }}
      >
        <code>{query}</code>
      </pre>

      {error && !showModal && (
        <div
          style={{
            padding: '12px',
            backgroundColor: 'var(--vocs-color_dangerBackground)',
            color: 'var(--vocs-color_danger)',
            borderTop: '1px solid var(--vocs-color_border)',
            fontSize: '14px',
          }}
        >
          {error}
        </div>
      )}

      {results !== null && (
        <div
          style={{
            borderTop: '1px solid var(--vocs-color_border)',
            maxHeight: '400px',
            overflow: 'auto',
          }}
        >
          <div
            style={{
              padding: '8px 12px',
              backgroundColor: 'var(--vocs-color_backgroundDark)',
              fontSize: '12px',
              color: 'var(--vocs-color_text2)',
              borderBottom: '1px solid var(--vocs-color_border)',
            }}
          >
            {results.length} row{results.length !== 1 ? 's' : ''} returned
          </div>
          <ResultTable data={results} />
        </div>
      )}

      <CredentialModal
        database={database}
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onSubmit={executeQuery}
        error={error}
      />
    </div>
  );
}

export default ClickHouseSqlExample;
