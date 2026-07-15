import type { AnalyticsDatasetStatus, FindingCard } from '../types';

export type InvestigationScope =
  | 'landing'
  | 'regional-result'
  | 'period-result'
  | 'cluster-investigation';

export type MapToolId =
  | 'burned-area-timeline'
  | 'cluster-selection'
  | 'before-during-after'
  | 'before-after-swipe'
  | 'scene-candidate-browser'
  | 'natura-overlap'
  | 'ramsar-overlap'
  | 'land-cover-exposure'
  | 'legend'
  | 'fit-to-aoi';

export interface MapCapability {
  id: MapToolId;
  label: string;
  visible: boolean;
  enabled: boolean;
  reason?: string;
  status?: 'available' | 'active' | 'disabled';
}

export interface UiMapContext {
  scope: InvestigationScope;
  selectedClusterId: string | null;
  activeOpticalFindingId: string | null;
  capabilities: MapCapability[];
}

function isOpticalFinding(card: FindingCard): boolean {
  const payload = card.payload as Record<string, unknown>;
  return Boolean((payload.selected_pair || payload.selected_scenes) && payload.composite_label);
}

function hasComparableOpticalScenes(card: FindingCard): boolean {
  const payload = card.payload as Record<string, any>;
  const scenes = payload.selected_scenes ?? {};
  const pair = payload.selected_pair ?? {};
  const before = scenes.before ?? pair.pre;
  const comparison = scenes.after ?? scenes.during ?? pair.post;
  return Boolean(before && comparison);
}

function hasMonthlyBurnFinding(card: FindingCard): boolean {
  return Array.isArray(card.payload?.monthly);
}

export function getLatestOpticalFindingId(finding: FindingCard[]): string | null {
  const opticalCards = finding
    .filter(isOpticalFinding)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return opticalCards[0]?.id ?? null;
}

export function createUiMapContext({
  finding,
  selectedClusterId,
  datasetStatus,
}: {
  finding: FindingCard[];
  selectedClusterId: string | null;
  datasetStatus?: AnalyticsDatasetStatus | null;
}): UiMapContext {
  const hasFinding = finding.length > 0;
  const hasMonthly = finding.some(hasMonthlyBurnFinding);
  const activeOpticalFindingId = getLatestOpticalFindingId(finding);
  const activeOpticalFinding = activeOpticalFindingId
    ? finding.find((card) => card.id === activeOpticalFindingId)
    : null;
  const hasOptical = Boolean(activeOpticalFindingId);
  const canCompareOptical = Boolean(activeOpticalFinding && hasComparableOpticalScenes(activeOpticalFinding));
  const ba300Configured = Boolean(datasetStatus?.ba300_monthly_v4?.queryable ?? datasetStatus?.ba300_monthly_v4?.configured);
  const ba300Missing = datasetStatus?.ba300_monthly_v4?.missing ?? [];
  const scope: InvestigationScope = selectedClusterId
    ? 'cluster-investigation'
    : hasMonthly
      ? 'regional-result'
      : hasFinding
        ? 'period-result'
        : 'landing';

  const capabilities: MapCapability[] = [
    {
      id: 'burned-area-timeline',
      label: 'Burned-area timeline',
      visible: hasMonthly || scope === 'landing' || Boolean(datasetStatus),
      enabled: ba300Configured,
      status: ba300Configured ? 'available' : 'disabled',
      reason: ba300Configured
        ? 'CLMS BA300 monthly v4 cache is configured.'
        : `Real BA300 timeline is waiting for ingestion${ba300Missing.length ? `: ${ba300Missing.join(', ')}` : '.'}`,
    },
    {
      id: 'cluster-selection',
      label: 'Cluster selection',
      visible: true,
      enabled: true,
      status: selectedClusterId ? 'active' : 'available',
    },
    {
      id: 'before-during-after',
      label: 'Before / During / After',
      visible: hasOptical,
      enabled: hasOptical,
      status: hasOptical ? 'active' : 'disabled',
    },
    {
      id: 'before-after-swipe',
      label: 'Compare swipe',
      visible: hasOptical,
      enabled: canCompareOptical,
      status: canCompareOptical ? 'available' : 'disabled',
      reason: canCompareOptical ? undefined : 'Run an optical workflow with before plus during or after imagery before comparing.',
    },
    {
      id: 'land-cover-exposure',
      label: 'Land cover',
      visible: scope === 'cluster-investigation',
      enabled: false,
      status: 'disabled',
      reason: 'WorldCover exposure requires real-data ingestion.',
    },
    {
      id: 'natura-overlap',
      label: 'Natura 2000',
      visible: scope === 'cluster-investigation' || hasFinding,
      enabled: false,
      status: 'disabled',
      reason: 'Official Natura 2000 boundaries are not loaded yet.',
    },
    {
      id: 'ramsar-overlap',
      label: 'Ramsar',
      visible: scope === 'cluster-investigation' || hasFinding,
      enabled: false,
      status: 'disabled',
      reason: 'Official Ramsar boundaries are not loaded yet.',
    },
    {
      id: 'legend',
      label: 'Legend',
      visible: true,
      enabled: true,
      status: 'available',
    },
    {
      id: 'fit-to-aoi',
      label: selectedClusterId ? 'Fit selected AOI' : 'Fit Greece clusters',
      visible: true,
      enabled: true,
      status: selectedClusterId ? 'active' : 'available',
    },
  ];

  return {
    scope,
    selectedClusterId,
    activeOpticalFindingId,
    capabilities,
  };
}
