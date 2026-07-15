import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, ClipboardCheck, Clock3, MessageSquareText, Radio, Route, TerminalSquare } from 'lucide-react';
import type { AgentRunTrace, ToolCallTrace } from '../types';

interface Props {
  run: AgentRunTrace | null;
  open: boolean;
  running: boolean;
  onOpenChange: (open: boolean) => void;
}

function StatusPill({ trace, running, hasRun }: { trace: ToolCallTrace[]; running: boolean; hasRun: boolean }) {
  if (running) return <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-sky-800">Running</span>;
  if (!hasRun) return <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">Idle</span>;
  const hasError = trace.some((item) => item.status === 'error');
  const skipped = trace.filter((item) => item.status === 'skipped').length;
  if (hasError) return <span className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-rose-700">Needs review</span>;
  if (skipped) return <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-amber-800">{skipped} skipped</span>;
  return <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700">Completed</span>;
}

function TraceToolCall({ item, index }: { item: ToolCallTrace; index: number }) {
  return (
    <article className="trace-row">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-400">Tool call {index + 1}</div>
          <div className="mt-1 truncate text-sm font-semibold text-slate-950">{item.step_id}</div>
          <div className="mt-0.5 truncate text-xs text-slate-500">{item.tool}</div>
        </div>
        <span className={`trace-status trace-status-${item.status}`}>{item.status}</span>
      </div>
      {item.message && <p className="mt-2 text-xs leading-relaxed text-slate-600">{item.message}</p>}
      <pre className="mt-2 max-h-36 overflow-auto rounded-xl bg-slate-50 p-2 text-[11px] leading-relaxed text-slate-500">{JSON.stringify(item.output_preview, null, 2)}</pre>
    </article>
  );
}

function formatClock(value?: string): string {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function elapsedSeconds(startedAt?: string, now = Date.now()): number {
  if (!startedAt) return 0;
  const started = new Date(startedAt).getTime();
  if (!Number.isFinite(started)) return 0;
  return Math.max(0, Math.floor((now - started) / 1000));
}

export default function TraceDock({ run, open, running, onOpenChange }: Props) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const response = run?.response ?? null;
  const trace = response?.trace ?? [];
  const selectedSkill = response?.selected_skill_id ?? (response ? 'no skill selected' : 'pending');
  const elapsed = elapsedSeconds(run?.started_at, now);
  const summary = running
    ? `Running ${elapsed}s · ${run?.input ?? 'workflow'}`
    : run
      ? `${selectedSkill} · ${trace.length} tool call${trace.length === 1 ? '' : 's'}`
      : 'No run trace yet';
  const liveEvents = useMemo(() => {
    if (!run) return [];
    if (response) {
      return [
        { label: 'Prompt captured', detail: run.input, status: 'done', time: formatClock(run.started_at) },
        { label: 'Backend response received', detail: `Selected ${selectedSkill}; returned ${trace.length} trace record${trace.length === 1 ? '' : 's'}.`, status: 'done', time: formatClock(run.completed_at) },
        { label: 'Finding refresh requested', detail: `${response.finding_cards.length} finding card${response.finding_cards.length === 1 ? '' : 's'} returned by the run.`, status: 'done', time: formatClock(run.completed_at) },
      ];
    }
    return [
      { label: 'Prompt captured', detail: run.input, status: 'done', time: formatClock(run.started_at) },
      { label: 'Request sent to agent API', detail: 'POST /agent/query is running for this investigation.', status: 'done', time: formatClock(run.started_at) },
      {
        label: 'Backend orchestration in progress',
        detail: 'The backend is selecting a workflow skill and executing deterministic tools. This endpoint is synchronous, so exact per-tool records appear when the response returns.',
        status: 'active',
        time: `${elapsed}s`,
      },
      {
        label: 'Waiting for tool trace',
        detail: 'Returned trace will include the selected workflow, tool call chain, messages, and output previews.',
        status: 'waiting',
        time: 'live',
      },
    ];
  }, [elapsed, response, run, selectedSkill, trace.length]);

  return (
    <section className={`trace-dock no-print ${open ? 'trace-dock-open' : ''}`} aria-label="Run trace">
      {open && (
        <div className="trace-drawer">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200/80 px-4 py-3">
            <div className="min-w-0">
              <div className="text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-slate-400">Run trace</div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-950">{summary}</div>
            </div>
            <button className="ghost-button rounded-full px-3 py-1.5 text-xs" onClick={() => onOpenChange(false)}>
              Collapse
            </button>
          </div>

          <div className="trace-timeline">
            <section className="trace-stage">
              <div className="trace-stage-icon trace-stage-icon-live"><Radio size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">Live activity</div>
                <div className="mt-3 space-y-2">
                  {liveEvents.length ? liveEvents.map((event) => (
                    <div key={`${event.label}-${event.time}`} className={`trace-live-event trace-live-${event.status}`}>
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-slate-900">{event.label}</div>
                          <div className="mt-1 text-xs leading-relaxed text-slate-600">{event.detail}</div>
                        </div>
                        <span className="trace-live-time">{event.time}</span>
                      </div>
                    </div>
                  )) : (
                    <p className="trace-stage-body">Live events will appear when a run starts.</p>
                  )}
                </div>
              </div>
            </section>

            <section className="trace-stage">
              <div className="trace-stage-icon"><MessageSquareText size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">User input</div>
                <p className="trace-stage-body">{run?.input ?? 'No prompt has been run yet.'}</p>
              </div>
            </section>

            <section className="trace-stage">
              <div className="trace-stage-icon"><Route size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">Visible routing and decision record</div>
                {response ? (
                  <div className="trace-stage-body space-y-2">
                    <p>Selected workflow skill: <span className="font-semibold text-slate-800">{selectedSkill}</span></p>
                    <p>The app exposes the selected skill, deterministic tool chain, messages, output previews, and finding produced.</p>
                    {response.answer && <p className="rounded-xl border border-slate-200 bg-white p-3">{response.answer}</p>}
                  </div>
                ) : (
                  <p className="trace-stage-body">Waiting for the agent response and tool plan.</p>
                )}
              </div>
            </section>

            <section className="trace-stage">
              <div className="trace-stage-icon"><TerminalSquare size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">Tool chaining and outputs</div>
                {trace.length ? (
                  <div className="mt-3 space-y-2">
                    {trace.map((item, index) => <TraceToolCall key={item.step_id} item={item} index={index} />)}
                  </div>
                ) : (
                  <p className="trace-stage-body">No tool calls recorded yet.</p>
                )}
              </div>
            </section>

            <section className="trace-stage">
              <div className="trace-stage-icon"><Clock3 size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">Timing</div>
                <div className="trace-stage-body grid gap-2 md:grid-cols-3">
                  <div className="rounded-xl border border-slate-200 bg-white p-3"><span className="font-semibold text-slate-800">Started</span><br />{formatClock(run?.started_at)}</div>
                  <div className="rounded-xl border border-slate-200 bg-white p-3"><span className="font-semibold text-slate-800">Elapsed</span><br />{elapsed}s</div>
                  <div className="rounded-xl border border-slate-200 bg-white p-3"><span className="font-semibold text-slate-800">Completed</span><br />{formatClock(run?.completed_at)}</div>
                </div>
              </div>
            </section>

            <section className="trace-stage">
              <div className="trace-stage-icon"><ClipboardCheck size={15} /></div>
              <div className="min-w-0">
                <div className="trace-stage-title">Produced finding and next actions</div>
                {response ? (
                  <div className="trace-stage-body grid gap-2 md:grid-cols-2">
                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                      <span className="font-semibold text-slate-800">{response.finding_cards.length}</span> finding card{response.finding_cards.length === 1 ? '' : 's'} returned
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                      <span className="font-semibold text-slate-800">{response.suggested_actions.length}</span> suggested next action{response.suggested_actions.length === 1 ? '' : 's'}
                    </div>
                  </div>
                ) : (
                  <p className="trace-stage-body">Outputs will appear after the workflow completes.</p>
                )}
              </div>
            </section>
          </div>
        </div>
      )}

      <button className="trace-bar" onClick={() => onOpenChange(!open)} aria-expanded={open}>
        <span className="inline-flex min-w-0 items-center gap-2">
          {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          <span className="truncate font-medium">{summary}</span>
        </span>
        <span className="hidden items-center gap-2 text-xs text-slate-500 sm:inline-flex">
          <StatusPill trace={trace} running={running} hasRun={Boolean(run)} />
          <span>{open ? 'Hide trace' : 'View trace'}</span>
        </span>
      </button>
    </section>
  );
}
