import { ChevronDown } from 'lucide-react';
import type { ToolCallTrace } from '../types';

export default function AgentTrace({ trace }: { trace: ToolCallTrace[] }) {
  if (!trace.length) return null;
  return (
    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs text-slate-500">
      <summary className="flex cursor-pointer list-none items-center justify-between text-slate-600">
        <span>Workflow trace · {trace.length} tool call{trace.length === 1 ? '' : 's'}</span>
        <ChevronDown size={14} />
      </summary>
      <div className="mt-3 space-y-2">
        {trace.map((t) => (
          <div key={t.step_id} className="rounded-xl border border-slate-200 bg-white p-2.5">
            <div className="flex justify-between gap-2">
              <span className="font-medium text-slate-700">{t.step_id}</span>
              <span className={t.status === 'ok' ? 'text-emerald-700' : 'text-red-700'}>{t.status}</span>
            </div>
            <div className="mt-1 text-slate-500">{t.tool}</div>
            <pre className="mt-2 max-h-36 overflow-auto rounded-lg bg-slate-50 p-2 text-[11px] leading-relaxed text-slate-500">{JSON.stringify(t.output_preview, null, 2)}</pre>
          </div>
        ))}
      </div>
    </details>
  );
}
