import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CloudDownload, Database, RefreshCw, Search } from 'lucide-react';
import { discoverBa300, preprocessBa300, syncBa300 } from '../lib/api';
import type { Ba300OperationResponse, DatasetStatusEntry } from '../types';

interface Props {
  status?: DatasetStatusEntry;
}

function summarise(result: Ba300OperationResponse | null): string {
  if (!result) return '';
  const rows = result.results?.length ? result.results : result.imported;
  if (!rows?.length) return result.status ?? 'No BA300 products were found.';
  return rows
    .slice(0, 2)
    .map((row) => {
      const period = String(row.period ?? 'period');
      const status = String(row.status ?? (row.result ? 'processed' : 'updated'));
      const reason = row.reason ? `: ${String(row.reason)}` : '';
      return `${period} ${status}${reason}`;
    })
    .join(' · ');
}

export default function Ba300DataControl({ status }: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState('2024-01');
  const [end, setEnd] = useState('2025-12');
  const [lastResult, setLastResult] = useState<Ba300OperationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = async () => {
    await queryClient.invalidateQueries({ queryKey: ['analytics-datasets-status'] });
  };

  const discoverMutation = useMutation({
    mutationFn: () => discoverBa300(start, end),
    onSuccess: async (result) => {
      setLastResult(result);
      setError(null);
      await refreshStatus();
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'BA300 discovery failed.'),
  });

  const syncMutation = useMutation({
    mutationFn: () => syncBa300(start, end, { preprocess: true }),
    onSuccess: async (result) => {
      setLastResult(result);
      setError(null);
      await refreshStatus();
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'BA300 sync failed.'),
  });

  const preprocessMutation = useMutation({
    mutationFn: () => preprocessBa300(start, end),
    onSuccess: async (result) => {
      setLastResult(result);
      setError(null);
      await refreshStatus();
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'BA300 preprocessing failed.'),
  });

  const busy = discoverMutation.isPending || syncMutation.isPending || preprocessMutation.isPending;
  const queryable = Boolean(status?.queryable);
  const configured = Boolean(status?.configured);
  const stateLabel = queryable ? `${status?.months_cached ?? status?.ingested_months?.length ?? 0} month cache` : configured ? 'credentials set' : 'needs CDSE';

  return (
    <div className="ba300-control">
      <button className={`ba300-status-button ${queryable ? 'ba300-status-ready' : configured ? 'ba300-status-configured' : ''}`} onClick={() => setOpen((value) => !value)}>
        <Database size={15} />
        <span>BA300</span>
        <strong>{stateLabel}</strong>
      </button>
      {open && (
        <div className="ba300-popover">
          <div className="ba300-popover-header">
            <div>
              <div className="ba300-kicker">CLMS Burnt Area 300 m</div>
              <div className="ba300-title">Monthly v4 data pipeline</div>
            </div>
            <button className="ghost-icon-button" onClick={() => refreshStatus()} disabled={busy} title="Refresh dataset status">
              <RefreshCw size={14} />
            </button>
          </div>
          <div className="ba300-status-grid">
            <span>Credentials</span><strong>{configured ? 'Configured' : 'Missing'}</strong>
            <span>Processed</span><strong>{status?.queryable ? 'Queryable' : 'No cache'}</strong>
            <span>Months</span><strong>{status?.ingested_months?.length ? status.ingested_months.join(', ') : 'None'}</strong>
          </div>
          {status?.missing?.length ? <div className="ba300-warning">{status.missing.join(' · ')}</div> : null}
          <div className="ba300-month-row">
            <label>
              <span>Start</span>
              <input type="month" value={start} onChange={(event) => setStart(event.target.value)} />
            </label>
            <label>
              <span>End</span>
              <input type="month" value={end} onChange={(event) => setEnd(event.target.value)} />
            </label>
          </div>
          <div className="ba300-actions">
            <button className="ghost-button ba300-action-button" onClick={() => discoverMutation.mutate()} disabled={busy}>
              <Search size={14} /> Discover
            </button>
            <button className="primary-button ba300-action-button" onClick={() => syncMutation.mutate()} disabled={busy}>
              <CloudDownload size={14} /> Sync
            </button>
            <button className="ghost-button ba300-action-button" onClick={() => preprocessMutation.mutate()} disabled={busy}>
              <RefreshCw size={14} /> Preprocess
            </button>
          </div>
          {(lastResult || error) && <div className={error ? 'ba300-result ba300-result-error' : 'ba300-result'}>{error ?? summarise(lastResult)}</div>}
        </div>
      )}
    </div>
  );
}
