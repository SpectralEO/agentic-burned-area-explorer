import { useEffect, useState } from 'react';
import { BarChart3, ChevronDown, FileMinus, FilePlus, FileText, Image, Map, Trash2, X } from 'lucide-react';
import { deleteFinding, imageryPreviewUrl } from '../lib/api';
import type { SceneRole } from '../lib/api';
import type { FindingCard } from '../types';
import MonthlyBurnChart from './MonthlyBurnChart';

interface Props {
  finding: FindingCard[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void;
  onGenerateReport: () => void;
  onFocusFinding: (findingId: string) => void;
  onToggleReportInclusion: (card: FindingCard) => void | Promise<void>;
}

const label: Record<string, string> = {
  primary_finding: 'Primary',
  supporting_finding: 'Supporting',
  contextual_finding: 'Contextual',
  validation_finding: 'Validation',
  caveat: 'Caveat',
  synthesis: 'Synthesis',
};

const tone: Record<string, string> = {
  primary_finding: 'border-amber-200 bg-amber-50 text-amber-800',
  supporting_finding: 'border-sky-200 bg-sky-50 text-sky-800',
  contextual_finding: 'border-violet-200 bg-violet-50 text-violet-800',
  validation_finding: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  caveat: 'border-orange-200 bg-orange-50 text-orange-800',
  synthesis: 'border-slate-200 bg-slate-50 text-slate-700',
};

const SCENE_ROLES: { role: SceneRole; label: string }[] = [
  { role: 'before', label: 'Before' },
  { role: 'during', label: 'During' },
  { role: 'after', label: 'After' },
];

function isMonthlyCard(card: FindingCard): boolean {
  return Array.isArray(card.payload?.monthly);
}

function isOpticalCard(card: FindingCard): boolean {
  return Array.isArray((card.payload as any)?.candidates) && Boolean((card.payload as any)?.composite_label);
}

function dateOnly(value: unknown): string {
  if (!value || typeof value !== 'string') return 'n/a';
  return value.slice(0, 10);
}

function selectedScenesFromPayload(payload: any): Partial<Record<SceneRole, any>> {
  const scenes = payload?.selected_scenes;
  if (scenes && typeof scenes === 'object') return scenes;
  const pair = payload?.selected_pair ?? {};
  const fallback: Partial<Record<SceneRole, any>> = {};
  if (pair.pre) fallback.before = pair.pre;
  if (pair.post?.role === 'during-window') fallback.during = pair.post;
  else if (pair.post) fallback.after = pair.post;
  return fallback;
}

function PreviewImage({ findingId, role, itemId }: { findingId: string; role: SceneRole; itemId?: string }) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = `${imageryPreviewUrl(findingId, role, 720)}${itemId ? `&v=${encodeURIComponent(itemId)}` : ''}`;

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setImageUrl(null);
    setError(null);
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          let message = `Preview request failed with HTTP ${response.status}`;
          try {
            const data = await response.json();
            if (typeof data?.detail === 'string') message = data.detail;
          } catch {
            // Keep generic message.
          }
          throw new Error(message);
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  if (error) {
    return (
      <div className="grid min-h-[150px] place-items-center overflow-auto rounded-xl border border-rose-200 bg-rose-50 p-3 text-center text-[0.72rem] leading-relaxed text-rose-800">
        {error}
      </div>
    );
  }
  if (!imageUrl) {
    return <div className="grid min-h-[150px] place-items-center rounded-xl border border-slate-200 bg-slate-50 text-xs text-slate-400">Rendering preview...</div>;
  }
  return (
    <img
      src={imageUrl}
      className="h-auto w-full rounded-xl border border-slate-200 bg-slate-100 object-cover shadow-sm"
      alt={`${role} fire optical preview`}
      loading="lazy"
    />
  );
}

function ProvenanceBlock({ card }: { card: FindingCard }) {
  const provenance = card.provenance as Record<string, any>;
  const parameters = provenance?.parameters && typeof provenance.parameters === 'object' ? provenance.parameters : {};
  const parameterEntries = Object.entries(parameters).slice(0, 8);
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70 p-2.5 text-[0.72rem] leading-relaxed text-slate-500">
      <div className="grid gap-2 sm:grid-cols-2">
        <div><span className="text-slate-400">Source</span><br />{card.source_dataset}</div>
        <div><span className="text-slate-400">Method</span><br />{String(provenance?.method ?? provenance?.workflow_skill ?? 'Workflow skill output')}</div>
      </div>
      {parameterEntries.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-slate-600">Parameters and provenance</summary>
          <div className="mt-2 grid gap-1.5">
            {parameterEntries.map(([key, value]) => (
              <div key={key} className="rounded-lg bg-white/80 p-2">
                <span className="text-slate-400">{key}</span><br />{typeof value === 'string' || typeof value === 'number' ? String(value) : JSON.stringify(value)}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function OpticalFinding({ card }: { card: FindingCard }) {
  const payload = card.payload as any;
  const scenes = selectedScenesFromPayload(payload);
  const selectedRoles = SCENE_ROLES.filter(({ role }) => scenes[role]);
  const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
  return (
    <div className="mt-3 space-y-3">
      <p className="text-sm leading-relaxed text-slate-600">{card.summary}</p>
      <div className="rounded-xl border border-sky-100 bg-sky-50/60 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-sky-900"><Image size={14} /> {payload.composite_label ?? 'Optical composite'}</div>
        <p className="mt-1 text-xs leading-relaxed text-sky-800/85">{payload.composite_description}</p>
        <div className="mt-2 grid grid-cols-2 gap-2 text-[0.72rem] text-slate-600">
          <div className="rounded-lg bg-white/80 p-2"><span className="text-slate-400">Sensor request</span><br />{payload.sensor_label}</div>
          <div className="rounded-lg bg-white/80 p-2"><span className="text-slate-400">Search mode</span><br />{payload.search_status}</div>
          <div className="rounded-lg bg-white/80 p-2"><span className="text-slate-400">Burn window</span><br />{payload.burn_window?.start}{' -> '}{payload.burn_window?.end}</div>
          <div className="rounded-lg bg-white/80 p-2"><span className="text-slate-400">Max cloud</span><br />{payload.max_cloud}%</div>
        </div>
      </div>

      {selectedRoles.length ? (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            {selectedRoles.map(({ role, label: roleLabel }) => {
              const item = scenes[role] ?? {};
              return (
                <div key={role}>
                  <div className="mb-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-400">{roleLabel}</div>
                  <PreviewImage findingId={card.id} role={role} itemId={item.item_id} />
                </div>
              );
            })}
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr><th className="px-3 py-2">Role</th><th className="px-3 py-2">Sensor</th><th className="px-3 py-2">Date</th><th className="px-3 py-2 text-right">Cloud</th><th className="px-3 py-2 text-right">Coverage</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white/70 text-slate-700">
                {selectedRoles.map(({ role, label: roleLabel }) => {
                  const item = scenes[role] ?? {};
                  return <tr key={role}><td className="px-3 py-2 font-medium">{roleLabel}</td><td className="px-3 py-2">{item.sensor ?? 'n/a'}</td><td className="px-3 py-2">{dateOnly(item.datetime)}</td><td className="px-3 py-2 text-right">{item.cloud_cover ?? 'n/a'}%</td><td className="px-3 py-2 text-right">{item.coverage_percent ?? 'n/a'}%</td></tr>;
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-3 text-xs leading-relaxed text-orange-800">No clean pre/post pair was selected. Try a wider window, Landsat fallback, or a higher cloud threshold.</div>
      )}

      <details className="text-xs text-slate-500">
        <summary className="cursor-pointer text-slate-600">{candidates.length} candidate scene(s)</summary>
        <div className="mt-2 space-y-1.5">
          {candidates.slice(0, 8).map((candidate: any) => <div key={`${candidate.item_id}-${candidate.role}`} className="rounded-xl border border-slate-100 bg-white/70 p-2"><span className="font-medium text-slate-700">{candidate.role}</span> · {candidate.sensor} · {dateOnly(candidate.datetime)} · cloud {candidate.cloud_cover ?? 'n/a'}% · coverage {candidate.coverage_percent ?? 'n/a'}%</div>)}
        </div>
      </details>
    </div>
  );
}

export default function FindingBoard({
  finding,
  open,
  onOpenChange,
  onChanged,
  onGenerateReport,
  onFocusFinding,
  onToggleReportInclusion,
}: Props) {
  const reportCount = finding.filter((card) => card.pinned).length;
  const [busyFindingId, setBusyFindingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !finding.length) return;
    const newest = [...finding].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
    if (!expandedId || !finding.some((card) => card.id === expandedId)) setExpandedId(newest.id);
  }, [finding, expandedId, open]);

  async function toggle(card: FindingCard) {
    if (busyFindingId) return;
    setBusyFindingId(card.id);
    try {
      await onToggleReportInclusion(card);
    } finally {
      setBusyFindingId(null);
    }
  }

  async function remove(card: FindingCard) {
    if (busyFindingId) return;
    setBusyFindingId(card.id);
    try {
      await deleteFinding(card.id);
      if (expandedId === card.id) setExpandedId(null);
      onChanged();
    } finally {
      setBusyFindingId(null);
    }
  }

  if (!open) return null;

  return (
    <aside className="finding-drawer no-print" aria-label="Finding drawer">
      <div className="finding-drawer-header">
        <div className="min-w-0">
          <div className="text-[0.68rem] uppercase tracking-[0.24em] text-emerald-700">Finding</div>
          <h2 className="mt-1 truncate text-lg font-semibold tracking-[-0.035em] text-slate-950">Investigation file</h2>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">Reviewed finding can be added to the brief. Explorations stay reusable from their cards.</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button className="primary-button inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-semibold" onClick={onGenerateReport}>
            <FileText size={15} /> Brief
          </button>
          <button className="ghost-button grid h-9 w-9 place-items-center rounded-full" aria-label="Close finding drawer" onClick={() => onOpenChange(false)}>
            <X size={16} />
          </button>
        </div>
        <div className="col-span-full mt-3 flex gap-2">
          <span className="badge"><FileText size={13} /> {reportCount} in report</span>
          <span className="badge"><BarChart3 size={13} /> {finding.length} unique</span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto space-y-3 p-4 pr-2">
        {finding.length === 0 && <div className="card p-4 text-sm leading-relaxed text-slate-500">No finding yet. Run an investigation step from the prompt.</div>}
        {finding.map((card) => {
          const optical = isOpticalCard(card);
          const expanded = expandedId === card.id;
          return (
            <article key={card.id} className={`finding-card ${card.pinned ? 'finding-card-in-report' : ''}`}>
              <div className="flex items-start justify-between gap-3">
                <button className="min-w-0 flex-1 text-left" onClick={() => setExpandedId(expanded ? null : card.id)}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[0.68rem] ${tone[card.type] ?? tone.synthesis}`}>{label[card.type] ?? card.type}</span>
                    {card.pinned && <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[0.68rem] text-emerald-700">In brief</span>}
                  </div>
                  <h3 className="mt-3 text-[0.96rem] font-semibold leading-snug tracking-[-0.015em] text-slate-950">{card.title}</h3>
                  {!expanded && <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-slate-600">{card.summary}</p>}
                </button>
                <button className="ghost-button grid h-8 w-8 shrink-0 place-items-center rounded-full" aria-label={expanded ? 'Collapse card' : 'Expand card'} onClick={() => setExpandedId(expanded ? null : card.id)}>
                  <ChevronDown size={15} className={`transition ${expanded ? 'rotate-180' : ''}`} />
                </button>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {optical && (
                  <button
                    className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-800 hover:bg-sky-100"
                    onClick={() => onFocusFinding(card.id)}
                  >
                    <Map size={13} /> Revisit on map
                  </button>
                )}
                <button
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${card.pinned ? 'border border-slate-200 bg-white text-slate-600 hover:text-slate-900' : 'bg-slate-950 text-white'}`}
                  disabled={busyFindingId === card.id}
                  onClick={() => toggle(card)}
                >
                  {card.pinned ? <FileMinus size={13} /> : <FilePlus size={13} />}{card.pinned ? 'Remove from brief' : 'Add to brief'}
                </button>
                <button
                  className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50"
                  disabled={busyFindingId === card.id}
                  title="Delete finding card"
                  onClick={() => remove(card)}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>

              {expanded && (
                <div className="mt-3">
                  {isMonthlyCard(card) ? (
                    <MonthlyBurnChart data={card.payload.monthly as any[]} />
                  ) : optical ? (
                    <OpticalFinding card={card} />
                  ) : (
                    <p className="text-sm leading-relaxed text-slate-600">{card.summary}</p>
                  )}
                  <ProvenanceBlock card={card} />
                  {card.caveats?.length > 0 && (
                    <details className="mt-3 text-xs text-slate-500">
                      <summary className="cursor-pointer text-slate-600">Caveats and interpretation limits</summary>
                      <ul className="mt-2 list-disc space-y-1.5 pl-4 leading-relaxed">
                        {card.caveats.map((caveat, index) => <li key={index}>{caveat}</li>)}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </aside>
  );
}
