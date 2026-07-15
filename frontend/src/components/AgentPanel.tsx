import { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ArrowRight, ChevronDown, FileText, MessageSquareText, Sparkles } from 'lucide-react';
import { askAgent } from '../lib/api';
import type { AgentResponse, SuggestedAction } from '../types';
import type { InvestigationScope } from '../map-tools/registry';

interface Props {
  investigationId: string;
  selectedClusterId: string | null;
  findingCount: number;
  scope: InvestigationScope;
  onWorkflowComplete: () => void;
  onGenerateReport: () => void;
  onRunStarted: (input: string) => void;
  onRunCompleted: (input: string, response: AgentResponse) => void;
  onRunningChange: (running: boolean) => void;
}

const starterPrompts = [
  'How many hectares burned in Greece in 2025?',
  'Compare the 2025 fire season with 2024',
  'How much tree-covered area burned in Greece in 2025?',
  'Which Natura 2000 sites overlapped mapped burned areas in 2025?',
  'Which Ramsar sites overlapped mapped burned areas in 2025?',
];

function suggestedPromptLabel(scope: InvestigationScope, selectedClusterId: string | null): string {
  if (selectedClusterId) return `Ask about selected cluster ${selectedClusterId}...`;
  if (scope === 'regional-result') return 'Ask about the regional burned-area result...';
  if (scope === 'period-result') return 'Ask about this investigation...';
  return 'Ask about burned areas in Greece...';
}

export default function AgentPanel({
  investigationId,
  selectedClusterId,
  findingCount,
  scope,
  onWorkflowComplete,
  onGenerateReport,
  onRunStarted,
  onRunCompleted,
  onRunningChange,
}: Props) {
  const [message, setMessage] = useState('');
  const [responses, setResponses] = useState<AgentResponse[]>([]);
  const [moreOpen, setMoreOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const askMutation = useMutation({
    mutationFn: (msg: string) => askAgent(investigationId, msg),
    onSuccess: (res, input) => {
      setResponses((prev) => [...prev, res]);
      setErrorMessage(null);
      onRunCompleted(input, res);
      onWorkflowComplete();
    },
    onError: (err) => setErrorMessage(err instanceof Error ? err.message : 'Could not run the workflow.'),
  });

  const latestActions = useMemo(() => responses[responses.length - 1]?.suggested_actions ?? [], [responses]);
  const visibleActions = latestActions.length ? latestActions.slice(0, 3) : starterPrompts.slice(0, 3);
  const moreActions = latestActions.length ? latestActions.slice(3) : starterPrompts.slice(3);
  const busy = askMutation.isPending;
  const placeholder = suggestedPromptLabel(scope, selectedClusterId);

  useEffect(() => {
    onRunningChange(busy);
  }, [busy, onRunningChange]);

  function submitText(text: string) {
    const value = text.trim();
    if (!value || busy) return;
    onRunStarted(value);
    askMutation.mutate(value);
    setMessage('');
    setMoreOpen(false);
  }

  function stageChip(item: string | SuggestedAction) {
    const label = typeof item === 'string' ? item : item.label;
    setMessage(label);
    setMoreOpen(false);
  }

  return (
    <section className="prompt-dock no-print" aria-label="Investigation prompt">
      <div className="prompt-card">
        <div className="flex items-center gap-2 text-[0.72rem] font-medium text-slate-500">
          <MessageSquareText size={14} />
          <span>{selectedClusterId ? `Cluster ${selectedClusterId}` : findingCount ? 'Investigation context loaded' : 'Ask a question about burned areas'}</span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <input
            className="prompt-input"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder={placeholder}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submitText(message);
            }}
          />
          <button className="primary-button prompt-run-button" onClick={() => submitText(message || placeholder)} disabled={busy}>
            {busy ? 'Running' : 'Run'} <ArrowRight size={15} />
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          {visibleActions.map((item) => {
            const label = typeof item === 'string' ? item : item.label;
            const key = typeof item === 'string' ? item : item.id;
            return (
              <button key={key} className="prompt-action" onClick={() => stageChip(item)} disabled={busy}>
                <Sparkles size={13} />
                {label}
              </button>
            );
          })}
          <button className="prompt-action" onClick={() => setMoreOpen((value) => !value)} disabled={busy}>
            <ChevronDown size={13} />
            More workflows
          </button>
          <button className="prompt-action" onClick={onGenerateReport} disabled={busy || findingCount === 0}>
            <FileText size={13} />
            Generate brief
          </button>
        </div>
        {moreOpen && (
          <div className="prompt-more">
            {moreActions.length ? moreActions.map((item) => {
              const label = typeof item === 'string' ? item : item.label;
              const key = typeof item === 'string' ? item : item.id;
              return (
                <button key={key} className="prompt-more-item" onClick={() => stageChip(item)}>
                  {label}
                </button>
              );
            }) : <div className="px-3 py-2 text-xs text-slate-500">No additional workflow actions yet.</div>}
          </div>
        )}
        {errorMessage && <div className="prompt-error">{errorMessage}</div>}
      </div>
    </section>
  );
}
