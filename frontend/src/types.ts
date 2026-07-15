export type FindingType =
  | 'primary_finding'
  | 'supporting_finding'
  | 'contextual_finding'
  | 'validation_finding'
  | 'caveat'
  | 'synthesis';

export interface Investigation {
  id: string;
  title: string;
  aoi: string;
  year: number;
  confidence_mode: string;
  selected_cluster_id?: string | null;
}

export interface FindingCard {
  id: string;
  investigation_id: string;
  type: FindingType;
  title: string;
  summary: string;
  source_dataset: string;
  geometry?: GeoJSON.Geometry | null;
  payload: Record<string, unknown>;
  provenance: Record<string, unknown>;
  caveats: string[];
  pinned: boolean;
  created_at: string;
}

export interface SuggestedAction {
  id: string;
  label: string;
  skill_id: string;
  requires: string[];
  parameters: Record<string, unknown>;
}

export interface ToolCallTrace {
  step_id: string;
  tool: string;
  status: 'ok' | 'skipped' | 'error';
  message: string;
  output_preview: Record<string, unknown>;
}

export interface AgentResponse {
  answer: string;
  selected_skill_id?: string | null;
  finding_cards: FindingCard[];
  suggested_actions: SuggestedAction[];
  trace: ToolCallTrace[];
}

export interface AgentRunTrace {
  input: string;
  started_at: string;
  completed_at?: string;
  response?: AgentResponse | null;
}

export interface DatasetStatusEntry {
  configured: boolean;
  discovered?: boolean;
  downloaded?: boolean;
  validated?: boolean;
  processed?: boolean;
  queryable?: boolean;
  source_mode?: string | null;
  ingested_months?: string[];
  missing_months?: string[];
  available_from?: string | null;
  available_to?: string | null;
  last_synced?: string | null;
  last_sync?: string | null;
  months_cached?: number | null;
  version?: string | null;
  boundary_count?: number | null;
  path?: string | null;
  missing: string[];
  caveats: string[];
}

export interface AnalyticsDatasetStatus {
  ba300_monthly_v4: DatasetStatusEntry;
  worldcover_2021: DatasetStatusEntry;
  natura2000: DatasetStatusEntry;
  ramsar: DatasetStatusEntry;
}

export interface Ba300OperationResponse {
  results?: Record<string, unknown>[];
  imported?: Record<string, unknown>[];
  status?: string | null;
  input?: string | null;
}

export interface BurnedAreaTimelineResponse {
  resolved_window: {
    active_start: string;
    active_end: string;
    context_start: string;
    context_end: string;
    granularity: 'day' | 'month' | 'year';
    display_mode: 'period' | 'cumulative';
    source_product: string;
    derivation_method: string;
  };
  metrics: {
    burned_area_occurrence_ha: number;
    unique_burned_surface_ha: number;
    cluster_count: number;
  };
  layers: {
    active: {
      type: 'raster';
      tiles: string[];
      bounds: number[];
      opacity: number;
    };
    context: {
      type: 'raster';
      tiles: string[];
      bounds: number[];
      opacity: number;
    };
  };
  clusters: GeoJSON.FeatureCollection;
  ui_context: Record<string, unknown>;
  provenance: Record<string, unknown>;
  caveats: string[];
}
