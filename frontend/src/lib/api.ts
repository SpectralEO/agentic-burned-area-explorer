import type { AgentResponse, AnalyticsDatasetStatus, Ba300OperationResponse, BurnedAreaTimelineResponse, FindingCard, Investigation, SuggestedAction } from '../types';

const DEFAULT_API_BASE = typeof window === 'undefined'
  ? 'http://localhost:8000/api'
  : `${window.location.protocol}//${window.location.hostname}:8000/api`;

export const API_BASE = import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const payload = JSON.parse(text);
      const detail = payload?.detail;
      if (typeof detail === 'string') throw new Error(detail);
      if (detail?.message) throw new Error(detail.message);
      if (detail?.missing_period) throw new Error(`BA300 data is not ingested for ${detail.missing_period}.`);
    } catch (err) {
      if (err instanceof Error && err.name !== 'SyntaxError') throw err;
    }
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export function createInvestigation(): Promise<Investigation> {
  return request('/investigations', { method: 'POST', body: JSON.stringify({ aoi: 'greece', year: 2025 }) });
}

export function getInvestigation(id: string): Promise<Investigation> {
  return request(`/investigations/${id}`);
}

export function getFinding(id: string): Promise<FindingCard[]> {
  return request(`/investigations/${id}/finding`);
}

export function getClusters(year = 2025): Promise<GeoJSON.FeatureCollection> {
  return request(`/clusters?year=${year}`);
}

export function getAnalyticsDatasetStatus(): Promise<AnalyticsDatasetStatus> {
  return request('/analytics/datasets/status');
}

export function discoverBa300(start: string, end: string): Promise<Ba300OperationResponse> {
  return request('/analytics/ba300/discover', {
    method: 'POST',
    body: JSON.stringify({ start, end }),
  });
}

export function syncBa300(start: string, end: string, options: { dryRun?: boolean; preprocess?: boolean; force?: boolean } = {}): Promise<Ba300OperationResponse> {
  return request('/analytics/ba300/sync', {
    method: 'POST',
    body: JSON.stringify({
      start,
      end,
      dry_run: options.dryRun ?? false,
      preprocess: options.preprocess ?? true,
      force: options.force ?? false,
    }),
  });
}

export function preprocessBa300(start: string, end: string, options: { dryRun?: boolean; force?: boolean } = {}): Promise<Ba300OperationResponse> {
  return request('/analytics/ba300/preprocess', {
    method: 'POST',
    body: JSON.stringify({
      start,
      end,
      dry_run: options.dryRun ?? false,
      force: options.force ?? false,
    }),
  });
}

export function getBurnedAreaTimeline(month: string, geographyId = 'GR'): Promise<BurnedAreaTimelineResponse> {
  return request('/analytics/burned-area/timeline', {
    method: 'POST',
    body: JSON.stringify({
      geography_type: 'country',
      geography_id: geographyId,
      granularity: 'month',
      cursor: `${month}-15`,
      display_mode: 'period',
    }),
  });
}

export function selectCluster(investigationId: string, clusterId: string): Promise<Investigation> {
  return request(`/investigations/${investigationId}/select-cluster`, {
    method: 'PATCH',
    body: JSON.stringify({ cluster_id: clusterId }),
  });
}

export function askAgent(investigationId: string, message: string): Promise<AgentResponse> {
  return request('/agent/query', {
    method: 'POST',
    body: JSON.stringify({ investigation_id: investigationId, message }),
  });
}

export function runAction(investigationId: string, action: SuggestedAction): Promise<AgentResponse> {
  return request('/agent/action', {
    method: 'POST',
    body: JSON.stringify({
      investigation_id: investigationId,
      action_id: action.id,
      skill_id: action.skill_id,
      parameters: action.parameters ?? {},
    }),
  });
}

export function setFindingReportInclusion(findingId: string, pinned: boolean): Promise<FindingCard> {
  return request(`/finding/${findingId}/report-inclusion`, { method: 'PATCH', body: JSON.stringify({ pinned }) });
}

export async function deleteFinding(findingId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/finding/${findingId}`, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
}

export function generateReport(investigationId: string): Promise<{ markdown: string }> {
  return request('/reports/generate', { method: 'POST', body: JSON.stringify({ investigation_id: investigationId }) });
}

export function reportPdfUrl(investigationId: string): string {
  return `${API_BASE}/reports/${investigationId}/pdf`;
}


export type SceneRole = 'before' | 'during' | 'after';
export type LegacySceneRole = SceneRole | 'pre' | 'post';


export function imageryPreviewUrl(findingId: string, role: LegacySceneRole, width = 720, candidateIndex?: number): string {
  const indexPart = candidateIndex === undefined ? '' : `&candidate_index=${candidateIndex}`;
  return `${API_BASE}/imagery/${findingId}/preview/${role}.png?width=${width}${indexPart}`;
}


export interface ImageryMapLayer {
  kind: 'image' | 'raster_tile';
  finding_id: string;
  role: SceneRole;
  candidate_index: number;
  url?: string;
  tiles?: string[];
  tile_size?: number;
  attribution?: string;
  bounds: [number, number, number, number];
  coordinates?: [[number, number], [number, number], [number, number], [number, number]];
  item_id?: string;
  datetime?: string;
  sensor?: string;
  composite?: string;
  minzoom?: number;
  maxzoom?: number;
  coverage_percent?: number | null;
  coverage_method?: string | null;
  scene_bounds?: [number, number, number, number];
  clip_bbox?: [number, number, number, number];
}

export function imageryMapLayer(findingId: string, role: SceneRole, width = 1400, candidateIndex?: number): Promise<ImageryMapLayer> {
  const indexPart = candidateIndex === undefined ? '' : `&candidate_index=${candidateIndex}`;
  return request(`/imagery/${findingId}/map-layer/${role}.json?width=${width}${indexPart}`);
}

export function updateImagerySelection(findingId: string, role: SceneRole, candidateIndex: number): Promise<FindingCard> {
  return request(`/imagery/${findingId}/selection`, {
    method: 'PATCH',
    body: JSON.stringify({ role, candidate_index: candidateIndex }),
  });
}
