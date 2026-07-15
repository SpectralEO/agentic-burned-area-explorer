import ReactMarkdown from 'react-markdown';
import { Download, FileDown, Printer, X } from 'lucide-react';
import { imageryPreviewUrl, reportPdfUrl } from '../lib/api';
import type { SceneRole } from '../lib/api';
import type { FindingCard } from '../types';


function opticalFindingCards(finding: FindingCard[]): FindingCard[] {
  return finding.filter((card) => card.pinned && Boolean((card.payload as any)?.selected_pair || (card.payload as any)?.selected_scenes));
}

const SCENE_ROLES: { role: SceneRole; label: string }[] = [
  { role: 'before', label: 'Before' },
  { role: 'during', label: 'During' },
  { role: 'after', label: 'After' },
];

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

function dateOnly(value: unknown): string {
  if (!value || typeof value !== 'string') return 'n/a';
  return value.slice(0, 10);
}

function ReportImageryAppendix({ finding }: { finding: FindingCard[] }) {
  const opticalCards = opticalFindingCards(finding);
  if (!opticalCards.length) return null;
  return (
    <section className="mt-8 border-t border-slate-200 pt-6">
      <h2 className="text-base font-semibold tracking-[-0.02em] text-slate-950">Selected optical imagery</h2>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">These are the current pre/post or pre/event image selections stored in optical finding cards added to the report.</p>
      <div className="mt-4 space-y-5">
        {opticalCards.map((card) => {
          const payload = card.payload as any;
          const scenes = selectedScenesFromPayload(payload);
          const selectedRoles = SCENE_ROLES.filter(({ role }) => scenes[role]);
          return (
            <div key={card.id} className="rounded-2xl border border-slate-200 bg-slate-50/65 p-3">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-950">{payload.composite_label ?? card.title}</div>
                  <div className="text-xs text-slate-500">{payload.sensor_label ?? 'Optical imagery'} · {payload.search_status ?? 'stac'}</div>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {selectedRoles.map(({ role, label }) => {
                  const item = scenes[role] ?? {};
                  return (
                    <figure key={role} className="m-0">
                      <figcaption className="mb-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-400">{label} · {dateOnly(item.datetime)} · cloud {item.cloud_cover ?? 'n/a'}%</figcaption>
                      <img className="w-full rounded-xl border border-slate-200 bg-slate-100" src={`${imageryPreviewUrl(card.id, role, 900)}&v=${encodeURIComponent(item.item_id ?? role)}`} alt={`${role} optical image for ${card.title}`} />
                    </figure>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function downloadMarkdown(markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'wildfire-finding-brief.md';
  link.click();
  URL.revokeObjectURL(url);
}

export default function ReportModal({ investigationId, markdown, finding, onClose }: { investigationId: string; markdown: string; finding: FindingCard[]; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 p-6 backdrop-blur-xl">
      <div className="print-document flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[1.45rem] border border-slate-200 bg-white shadow-2xl">
        <div className="no-print flex items-center justify-between gap-4 border-b border-slate-200 p-4">
          <div>
            <div className="text-[0.68rem] uppercase tracking-[0.24em] text-slate-400">Generated document</div>
            <h2 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-slate-950">Wildfire finding brief</h2>
          </div>
          <div className="flex items-center gap-2">
            <button className="ghost-button inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm" onClick={() => downloadMarkdown(markdown)}><Download size={15} /> Markdown</button>
            <a className="primary-button inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold" href={reportPdfUrl(investigationId)} target="_blank" rel="noreferrer"><FileDown size={15} /> Export PDF</a>
            <button className="ghost-button inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm" onClick={() => window.print()}><Printer size={15} /> Print</button>
            <button className="ghost-button rounded-full p-2" onClick={onClose}><X size={16} /></button>
          </div>
        </div>
        <div className="overflow-auto bg-[#eef2f2] p-6">
          <article className="document-surface prose-doc mx-auto min-h-[72vh] max-w-3xl p-10">
            <ReactMarkdown>{markdown}</ReactMarkdown>
            <ReportImageryAppendix finding={finding} />
          </article>
        </div>
      </div>
    </div>
  );
}
