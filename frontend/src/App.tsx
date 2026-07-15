import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, PanelRightOpen } from 'lucide-react';
import { createInvestigation, getAnalyticsDatasetStatus, getFinding, generateReport, setFindingReportInclusion } from './lib/api';
import AgentPanel from './components/AgentPanel';
import Ba300DataControl from './components/Ba300DataControl';
import MapPanel from './components/MapPanel';
import FindingBoard from './components/FindingBoard';
import ReportModal from './components/ReportModal';
import TraceDock from './components/TraceDock';
import { createUiMapContext } from './map-tools/registry';
import type { AgentResponse, AgentRunTrace, FindingCard } from './types';

function dedupeFinding(cards: FindingCard[]): FindingCard[] {
  const byKey = new Map<string, FindingCard>();
  for (const card of cards) {
    const payload = card.payload as Record<string, any>;
    const provenance = card.provenance as Record<string, any>;
    const clusterId = String(payload?.cluster_id ?? payload?.cluster?.properties?.cluster_id ?? '');
    const year = String(payload?.year ?? provenance?.parameters?.year ?? '');
    const sensor = String(payload?.sensor_request ?? provenance?.parameters?.sensor ?? '');
    const composite = String(payload?.composite ?? provenance?.parameters?.composite ?? '');
    const key = [card.investigation_id, card.type, card.title, card.source_dataset, clusterId, year, sensor, composite].join('|');
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, card);
      continue;
    }
    const keep = new Date(existing.created_at) > new Date(card.created_at) ? existing : card;
    keep.pinned = existing.pinned || card.pinned;
    byKey.set(key, keep);
  }
  return Array.from(byKey.values()).sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
}

export default function App() {
  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [mapFocusRequest, setMapFocusRequest] = useState<{ findingId: string; requestId: number } | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [findingDrawerOpen, setFindingDrawerOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [activeRunTrace, setActiveRunTrace] = useState<AgentRunTrace | null>(null);
  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: createInvestigation,
    onSuccess: (inv) => setInvestigationId(inv.id),
  });

  useEffect(() => {
    createMutation.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const findingQuery = useQuery({
    queryKey: ['finding', investigationId],
    enabled: Boolean(investigationId),
    queryFn: () => getFinding(investigationId!),
  });

  const datasetStatusQuery = useQuery({
    queryKey: ['analytics-datasets-status'],
    queryFn: getAnalyticsDatasetStatus,
  });

  const finding = useMemo(() => dedupeFinding(findingQuery.data ?? []), [findingQuery.data]);
  const uiMapContext = useMemo(
    () => createUiMapContext({ finding, selectedClusterId, datasetStatus: datasetStatusQuery.data ?? null }),
    [datasetStatusQuery.data, finding, selectedClusterId],
  );

  useEffect(() => {
    if (finding.length > 0) setFindingDrawerOpen(true);
  }, [finding.length]);

  async function onGenerateReport() {
    if (!investigationId) return;
    const res = await generateReport(investigationId);
    setReport(res.markdown);
  }

  async function refreshFinding() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['finding', investigationId] }),
      queryClient.invalidateQueries({ queryKey: ['investigation', investigationId] }),
    ]);
  }

  const handleClusterSelected = useCallback(async (clusterId?: string) => {
    if (clusterId) setSelectedClusterId(clusterId);
    await refreshFinding();
  }, [investigationId, queryClient]);

  const handleRunStarted = useCallback((input: string) => {
    setActiveRunTrace({ input, started_at: new Date().toISOString(), response: null });
  }, []);

  const handleRunCompleted = useCallback((input: string, response: AgentResponse) => {
    setActiveRunTrace((current) => ({
      input,
      started_at: current?.input === input ? current.started_at : new Date().toISOString(),
      completed_at: new Date().toISOString(),
      response,
    }));
  }, []);

  async function toggleReportInclusion(card: FindingCard) {
    await setFindingReportInclusion(card.id, !card.pinned);
    await refreshFinding();
  }

  function focusFindingOnMap(findingId: string) {
    setMapFocusRequest({ findingId, requestId: Date.now() });
  }

  if (createMutation.isError) {
    return (
      <div className="h-screen w-screen grid place-items-center bg-[#f7f5ef] p-6 text-slate-800">
        <div className="card max-w-xl p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-red-600">Backend not reachable</div>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-slate-950">Could not create an investigation</h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">
            Start the FastAPI backend first, then refresh the frontend. The map is mounted after an investigation ID is created.
          </p>
          <pre className="mt-4 rounded-xl bg-slate-100 p-3 text-xs text-slate-600">cd backend{`\n`}uv sync{`\n`}uv run uvicorn app.main:app --reload --port 8000</pre>
        </div>
      </div>
    );
  }

  if (!investigationId) {
    return <div className="h-screen grid place-items-center bg-[#f7f5ef] text-slate-600">Creating investigation…</div>;
  }

  return (
    <div className="app-shell">
      <header className="topbar no-print">
        <div className="flex items-center gap-3 min-w-0">
          <div className="brand-mark" />
          <h1 className="truncate text-[1.05rem] font-semibold tracking-[-0.03em] text-slate-950">Burned Area Explorer</h1>
        </div>
        <div className="topbar-actions">
          <Ba300DataControl status={datasetStatusQuery.data?.ba300_monthly_v4} />
          <button onClick={onGenerateReport} className="primary-button inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium">
            <FileText size={15} /> Create brief
          </button>
        </div>
      </header>

      <main className="map-first-main no-print">
        <MapPanel
          investigationId={investigationId}
          finding={finding}
          focusRequest={mapFocusRequest}
          uiContext={uiMapContext}
          datasetStatus={datasetStatusQuery.data ?? null}
          findingDrawerOpen={findingDrawerOpen}
          onClusterSelected={handleClusterSelected}
          onToggleReportInclusion={toggleReportInclusion}
        />
        {!findingDrawerOpen && finding.length > 0 && (
          <button className="finding-peek" onClick={() => setFindingDrawerOpen(true)}>
            <PanelRightOpen size={16} />
            Finding · {finding.length}
          </button>
        )}
        <FindingBoard
          finding={finding}
          open={findingDrawerOpen}
          onOpenChange={setFindingDrawerOpen}
          onChanged={refreshFinding}
          onGenerateReport={onGenerateReport}
          onFocusFinding={focusFindingOnMap}
          onToggleReportInclusion={toggleReportInclusion}
        />
        <AgentPanel
          investigationId={investigationId}
          selectedClusterId={selectedClusterId}
          findingCount={finding.length}
          scope={uiMapContext.scope}
          onWorkflowComplete={refreshFinding}
          onGenerateReport={onGenerateReport}
          onRunStarted={handleRunStarted}
          onRunCompleted={handleRunCompleted}
          onRunningChange={setAgentRunning}
        />
      </main>

      <TraceDock run={activeRunTrace} open={traceOpen} running={agentRunning} onOpenChange={setTraceOpen} />

      {report && <ReportModal investigationId={investigationId} markdown={report} finding={finding} onClose={() => setReport(null)} />}
    </div>
  );
}
