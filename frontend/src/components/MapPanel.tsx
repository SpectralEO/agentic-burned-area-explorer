import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import type { Map, StyleSpecification } from 'maplibre-gl';
import { CalendarDays, Info, Layers3, LocateFixed, MapPinned, SlidersHorizontal, X } from 'lucide-react';
import { getBurnedAreaTimeline, getClusters, imageryMapLayer, imageryPreviewUrl, selectCluster, updateImagerySelection } from '../lib/api';
import type { SceneRole } from '../lib/api';
import type { AnalyticsDatasetStatus, BurnedAreaTimelineResponse, FindingCard } from '../types';
import type { MapCapability, UiMapContext } from '../map-tools/registry';

interface Props {
  investigationId: string;
  finding: FindingCard[];
  focusRequest?: { findingId: string; requestId: number } | null;
  uiContext: UiMapContext;
  datasetStatus?: AnalyticsDatasetStatus | null;
  findingDrawerOpen: boolean;
  onClusterSelected: (clusterId?: string) => void | Promise<void>;
  onToggleReportInclusion: (card: FindingCard) => void | Promise<void>;
}

const DEMO_STYLE: StyleSpecification = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#f7f5ef' } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      paint: {
        'raster-opacity': 0.96,
        'raster-saturation': -0.1,
        'raster-contrast': -0.04,
        'raster-brightness-min': 0.03,
        'raster-brightness-max': 1,
      },
    },
  ],
};

function featureBounds(collection: GeoJSON.FeatureCollection): [[number, number], [number, number]] | null {
  const coords: number[][] = [];
  for (const feature of collection.features) {
    const geom = feature.geometry;
    if (!geom) continue;
    if (geom.type === 'Polygon') {
      geom.coordinates.flat(1).forEach((xy) => coords.push(xy as number[]));
    } else if (geom.type === 'MultiPolygon') {
      geom.coordinates.flat(2).forEach((xy) => coords.push(xy as number[]));
    }
  }
  if (!coords.length) return null;
  const xs = coords.map((c) => c[0]);
  const ys = coords.map((c) => c[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
}

function imageryFeatures(finding: FindingCard[]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const card of finding) {
    const payload = card.payload as any;
    if (!Array.isArray(payload?.candidates)) continue;
    for (const candidate of payload.candidates) {
      if (!candidate.geometry) continue;
      features.push({
        type: 'Feature',
        geometry: candidate.geometry as GeoJSON.Geometry,
        properties: {
          finding_id: card.id,
          item_id: candidate.item_id ?? 'unknown',
          role: candidate.role ?? 'candidate',
          sensor: candidate.sensor ?? payload.sensor_label ?? 'optical',
          composite: payload.composite_label ?? 'Composite',
          cloud_cover: candidate.cloud_cover ?? null,
          coverage_percent: candidate.coverage_percent ?? null,
          datetime: candidate.datetime ?? 'n/a',
        },
      });
    }
  }
  return { type: 'FeatureCollection', features };
}

function isOpticalFinding(card: FindingCard): boolean {
  const payload = card.payload as any;
  return Boolean(payload?.selected_pair || payload?.selected_scenes) && Boolean(payload?.composite_label);
}

function latestOpticalFinding(finding: FindingCard[]): FindingCard | null {
  const cards = finding.filter(isOpticalFinding).sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return cards[0] ?? null;
}

const SCENE_ROLES: { role: SceneRole; label: string; candidateRole: string }[] = [
  { role: 'before', label: 'Before', candidateRole: 'pre-fire' },
  { role: 'during', label: 'During', candidateRole: 'during-window' },
  { role: 'after', label: 'After', candidateRole: 'post-fire' },
];

function selectedScenes(card: FindingCard | null): Partial<Record<SceneRole, any>> {
  if (!card) return {};
  const payload = card.payload as any;
  const scenes = payload?.selected_scenes;
  if (scenes && typeof scenes === 'object') return scenes;
  const pair = payload?.selected_pair ?? {};
  const fallback: Partial<Record<SceneRole, any>> = {};
  if (pair.pre) fallback.before = pair.pre;
  if (pair.post?.role === 'during-window') fallback.during = pair.post;
  else if (pair.post) fallback.after = pair.post;
  return fallback;
}

function selectedScene(card: FindingCard | null, role: SceneRole): any | null {
  return selectedScenes(card)[role] ?? null;
}

function defaultSceneRole(card: FindingCard | null): SceneRole {
  if (!card) return 'after';
  const payload = card.payload as any;
  const scenes = selectedScenes(card);
  if (payload?.composite === 'fire_front_highlight' && scenes.during) return 'during';
  if (scenes.after) return 'after';
  if (scenes.during) return 'during';
  return 'before';
}

function opticalFindingSignature(card: FindingCard | null): string {
  if (!card) return 'none';
  const payload = card.payload as any;
  const pair = payload?.selected_pair ?? {};
  const compactCandidate = (candidate: any) => ({
    id: candidate?.item_id ?? null,
    role: candidate?.role ?? null,
    datetime: candidate?.datetime ?? null,
    provider: candidate?.stac_provider ?? null,
    source: candidate?.source ?? null,
  });
  return JSON.stringify({
    id: card.id,
    sensor: payload?.sensor_request ?? null,
    composite: payload?.composite ?? null,
    status: payload?.search_status ?? null,
    bounds: payload?.render_bounds ?? payload?.cluster_bbox ?? null,
    clip: payload?.clip_bbox ?? null,
    pair: {
      pre: compactCandidate(pair?.pre),
      post: compactCandidate(pair?.post),
    },
    scenes: Object.fromEntries(SCENE_ROLES.map(({ role }) => [role, compactCandidate(selectedScene(card, role))])),
    candidates: Array.isArray(payload?.candidates) ? payload.candidates.map(compactCandidate) : [],
  });
}

function roleCandidates(card: FindingCard | null, role: SceneRole): any[] {
  if (!card) return [];
  const payload = card.payload as any;
  const expected = SCENE_ROLES.find((entry) => entry.role === role)?.candidateRole;
  return Array.isArray(payload?.candidates)
    ? payload.candidates.filter((c: any) => c.role === expected)
    : [];
}

function selectedIndex(card: FindingCard | null, role: SceneRole): number {
  if (!card) return 0;
  const selectedId = selectedScene(card, role)?.item_id;
  const candidates = roleCandidates(card, role);
  const idx = candidates.findIndex((c: any) => c.item_id === selectedId);
  return idx >= 0 ? idx : 0;
}

function dateOnly(value: unknown): string {
  if (!value || typeof value !== 'string') return 'n/a';
  return value.slice(0, 10);
}

function validBbox(value: unknown): [number, number, number, number] | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const nums = value.map(Number);
  if (nums.some((n) => !Number.isFinite(n))) return null;
  const [west, south, east, north] = nums;
  if (west >= east || south >= north) return null;
  return [west, south, east, north];
}

function findingFocusBbox(card: FindingCard): [number, number, number, number] | null {
  const payload = card.payload as any;
  return (
    validBbox(payload?.clip_bbox)
    ?? validBbox(payload?.render_bounds)
    ?? validBbox(payload?.cluster_bbox)
    ?? null
  );
}

function fitMapToBbox(map: Map, bbox: [number, number, number, number], maxZoom = 12) {
  const container = map.getContainer();
  const width = container.clientWidth || 900;
  const height = container.clientHeight || 600;
  map.fitBounds(
    [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
    {
      padding: {
        top: Math.min(90, Math.floor(height * 0.18)),
        bottom: Math.min(90, Math.floor(height * 0.18)),
        left: Math.min(90, Math.floor(width * 0.12)),
        right: Math.min(500, Math.floor(width * 0.42)),
      },
      maxZoom,
      duration: 520,
    },
  );
}

function capabilityIcon(id: MapCapability['id']) {
  if (id === 'burned-area-timeline') return <CalendarDays size={14} />;
  if (id === 'fit-to-aoi') return <LocateFixed size={14} />;
  if (id === 'cluster-selection') return <MapPinned size={14} />;
  if (id === 'before-during-after' || id === 'before-after-swipe') return <Layers3 size={14} />;
  return <SlidersHorizontal size={14} />;
}

function MapToolStrip({
  context,
  activeToolIds = [],
  onCapabilityClick,
}: {
  context: UiMapContext;
  activeToolIds?: MapCapability['id'][];
  onCapabilityClick: (capability: MapCapability) => void;
}) {
  const capabilities = context.capabilities.filter((capability) => capability.visible);
  return (
    <div className="map-tool-strip" aria-label="Available map tools">
      {capabilities.map((capability) => (
        <button
          key={capability.id}
          className={`map-tool-chip ${capability.status === 'active' || activeToolIds.includes(capability.id) ? 'map-tool-chip-active' : ''}`}
          disabled={!capability.enabled}
          title={capability.reason ?? capability.label}
          onClick={() => onCapabilityClick(capability)}
        >
          {capabilityIcon(capability.id)}
          <span>{capability.label}</span>
        </button>
      ))}
    </div>
  );
}

type SensorFilter = 'all' | 'sentinel-2' | 'landsat' | 'modis' | 's3-olci';

const SENSOR_FILTERS: { id: SensorFilter; label: string; unavailableLabel?: string }[] = [
  { id: 'all', label: 'All sensors' },
  { id: 'sentinel-2', label: 'Sentinel-2' },
  { id: 'landsat', label: 'Landsat' },
  { id: 'modis', label: 'MODIS' },
  { id: 's3-olci', label: 'S3 OLCI', unavailableLabel: 'Not configured' },
];

function sceneSensorKey(scene: any): SensorFilter | 'unknown' {
  const value = String(scene?.sensor_key ?? scene?.sensor ?? '').toLowerCase();
  if (value.includes('sentinel-2') || value === 's2' || value.includes('sentinel 2')) return 'sentinel-2';
  if (value.includes('landsat') || value.includes('oli')) return 'landsat';
  if (value.includes('modis') || value.includes('terra') || value.includes('aqua')) return 'modis';
  if (value.includes('olci') || value.includes('sentinel-3') || value.includes('sentinel 3')) return 's3-olci';
  return 'unknown';
}

function availableSensorKeys(card: FindingCard): Set<SensorFilter> {
  const payload = card.payload as any;
  const keys = new Set<SensorFilter>(['all']);
  if (!Array.isArray(payload?.candidates)) return keys;
  for (const candidate of payload.candidates) {
    const key = sceneSensorKey(candidate);
    if (key !== 'unknown') keys.add(key);
  }
  return keys;
}

function compareRolePair(card: FindingCard): { left: SceneRole; right: SceneRole } | null {
  const scenes = selectedScenes(card);
  if (!scenes.before) return null;
  if (scenes.after) return { left: 'before', right: 'after' };
  if (scenes.during) return { left: 'before', right: 'during' };
  return null;
}

function roleLabel(role: SceneRole): string {
  return SCENE_ROLES.find((entry) => entry.role === role)?.label ?? role;
}

function OpticalMapControl({
  card,
  activeRole,
  setActiveRole,
  footprintsVisible,
  setFootprintsVisible,
  selectedIndexOverride,
  drawerOpen,
  onCloseLayer,
  onCandidateSelected,
  onSelectionChanged,
  onToggleReportInclusion,
}: {
  card: FindingCard;
  activeRole: SceneRole;
  setActiveRole: (role: SceneRole) => void;
  footprintsVisible: boolean;
  setFootprintsVisible: (value: boolean) => void;
  selectedIndexOverride?: number;
  drawerOpen: boolean;
  onCloseLayer: () => void;
  onCandidateSelected: (role: SceneRole, index: number) => void;
  onSelectionChanged: () => void | Promise<void>;
  onToggleReportInclusion: (card: FindingCard) => void | Promise<void>;
}) {
  const payload = card.payload as any;
  const activeScene = selectedScene(card, activeRole);
  const canRender = activeScene?.source === 'stac';
  const candidates = roleCandidates(card, activeRole);
  const idx = selectedIndexOverride ?? selectedIndex(card, activeRole);
  const selected = candidates[idx] ?? activeScene ?? {};
  const [busy, setBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [sensorFilter, setSensorFilter] = useState<SensorFilter>('all');
  const sensors = useMemo(() => availableSensorKeys(card), [card]);
  const sensorSignature = useMemo(() => Array.from(sensors).sort().join('|'), [sensors]);

  useEffect(() => {
    if (sensorFilter !== 'all' && !sensors.has(sensorFilter)) setSensorFilter('all');
  }, [sensorFilter, sensorSignature, sensors]);

  async function selectCandidate(role: SceneRole, index: number) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      setActiveRole(role);
      onCandidateSelected(role, index);
      await updateImagerySelection(card.id, role, index);
      await onSelectionChanged();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Could not update selected imagery.');
    } finally {
      setBusy(false);
    }
  }

  async function toggleReportInclusion() {
    if (reportBusy) return;
    setReportBusy(true);
    setMessage(null);
    try {
      await onToggleReportInclusion(card);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Could not update report inclusion.');
    } finally {
      setReportBusy(false);
    }
  }

  return (
    <div className={`optical-map-control ${drawerOpen ? 'optical-map-control-drawer-open' : ''}`}>
      <button
        type="button"
        aria-label="Close optical map layer"
        title="Close optical map layer"
        className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm hover:border-slate-300 hover:text-slate-950"
        onClick={onCloseLayer}
      >
        <X size={16} />
      </button>
      <div className="flex items-start justify-between gap-3 pr-11">
        <div className="min-w-0">
          <div className="text-[0.66rem] font-semibold uppercase tracking-[0.22em] text-sky-700">Optical map layer</div>
          <div className="mt-1 text-sm font-semibold tracking-[-0.02em] text-slate-950">{payload?.composite_label ?? 'Optical composite'}</div>
          <p className="mt-1 text-[0.72rem] leading-relaxed text-slate-600">
            {canRender ? 'Selected STAC scene rendered through the local composite tiler and bounded to the selected AOI. Pick one quicklook per period for the map and finding card; add it to the report only when ready.' : 'Pick a renderable STAC scene. Use real STAC mode with renderable assets to display imagery on the map.'}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-[0.68rem] ${canRender ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>{payload?.search_status ?? 'unknown'}</span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Quicklook sensor filters">
        {SENSOR_FILTERS.map((filter) => {
          const available = filter.id === 'all' || sensors.has(filter.id);
          const disabled = !available;
          return (
            <button
              key={filter.id}
              type="button"
              disabled={disabled}
              title={disabled ? `${filter.label} quicklooks are not available for this finding card.` : `Show ${filter.label} quicklooks`}
              onClick={() => setSensorFilter(filter.id)}
              className={`sensor-filter-chip ${sensorFilter === filter.id ? 'sensor-filter-chip-active' : ''}`}
            >
              <span>{filter.label}</span>
              {disabled && filter.unavailableLabel && <span className="sensor-filter-chip-note">{filter.unavailableLabel}</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-3 grid grid-cols-3 rounded-full bg-slate-100 p-1 text-xs font-semibold">
        {SCENE_ROLES.map(({ role, label }) => {
          const count = roleCandidates(card, role).length;
          return (
          <button key={role} disabled={!count} onClick={() => setActiveRole(role)} className={`rounded-full px-3 py-2 disabled:opacity-35 ${activeRole === role ? 'bg-white text-slate-950 shadow-sm' : 'text-slate-500 hover:text-slate-900'}`}>
            {label}
          </button>
          );
        })}
      </div>

      <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/75 p-3 text-xs text-slate-600">
        <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
          <span className="text-slate-400">Scene</span><span className="font-medium text-slate-800">{candidates.length ? `${idx + 1} of ${candidates.length}` : 'none'}</span>
          <span className="text-slate-400">Date</span><span className="font-medium text-slate-800">{dateOnly(selected.datetime)}</span>
          <span className="text-slate-400">Cloud</span><span className="font-medium text-slate-800">{selected.cloud_cover ?? 'n/a'}%</span>
          <span className="text-slate-400">AOI coverage</span><span className="font-medium text-slate-800">{selected.coverage_percent ?? 'n/a'}%</span>
          <span className="text-slate-400">Sensor</span><span className="font-medium text-slate-800">{selected.sensor ?? payload?.sensor_label ?? 'optical'}</span>
        </div>
        {message && <div className="mt-2 rounded-xl border border-rose-200 bg-rose-50 p-2 text-rose-800">{message}</div>}
      </div>

      <div className="quicklook-scroll-region mt-3 min-h-0 overflow-auto pr-1">
        <div className="space-y-3">
          {SCENE_ROLES.map(({ role, label }) => {
            const roleScenes = roleCandidates(card, role)
              .map((scene, index) => ({ scene, index }))
              .filter(({ scene }) => sensorFilter === 'all' || sceneSensorKey(scene) === sensorFilter);
            const selectedId = selectedScene(card, role)?.item_id;
            return (
              <section key={role}>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</div>
                  <div className="text-[0.68rem] text-slate-400">{roleScenes.length} scene{roleScenes.length === 1 ? '' : 's'}</div>
                </div>
                {roleScenes.length ? (
                  <div className="grid grid-cols-2 gap-2">
                    {roleScenes.slice(0, 8).map(({ scene, index }) => {
                      const isSelected = scene.item_id === selectedId;
                      const thumbUrl = `${imageryPreviewUrl(card.id, role, 260, index)}&v=${encodeURIComponent(scene.item_id ?? `${role}-${index}`)}`;
                      return (
                        <button
                          key={`${role}-${scene.item_id ?? index}`}
                          type="button"
                          disabled={busy}
                          onClick={() => selectCandidate(role, index)}
                          className={`overflow-hidden rounded-xl border bg-white text-left shadow-sm transition disabled:opacity-60 ${isSelected ? 'border-sky-500 ring-2 ring-sky-200' : 'border-slate-200 hover:border-sky-300'}`}
                        >
                          <div className="aspect-[4/3] bg-slate-100">
                            <img src={thumbUrl} alt={`${label} candidate ${dateOnly(scene.datetime)}`} className="h-full w-full object-cover" loading="lazy" />
                          </div>
                          <div className="space-y-0.5 p-2 text-[0.68rem] leading-tight text-slate-600">
                            <div className="flex items-center justify-between gap-2 font-semibold text-slate-800">
                              <span>{dateOnly(scene.datetime)}</span>
                              {isSelected && <span className="rounded-full bg-sky-100 px-1.5 py-0.5 text-[0.6rem] text-sky-800">Selected</span>}
                            </div>
                            <div className="truncate">{scene.sensor ?? payload?.sensor_label ?? 'Optical'}</div>
                            <div className="flex justify-between gap-2 text-slate-500">
                              <span>Cloud {scene.cloud_cover ?? 'n/a'}%</span>
                              <span>AOI {scene.coverage_percent ?? 'n/a'}%</span>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-400">No {sensorFilter === 'all' ? '' : `${SENSOR_FILTERS.find((filter) => filter.id === sensorFilter)?.label} `}{label.toLowerCase()} candidates.</div>
                )}
              </section>
            );
          })}
        </div>
      </div>

      <label className="mt-3 flex items-center gap-2 text-xs text-slate-600">
        <input type="checkbox" checked={footprintsVisible} onChange={(e) => setFootprintsVisible(e.target.checked)} />
        Show STAC footprints
      </label>

      <div className="mt-3 flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/80 p-2">
        <div className="text-[0.72rem] leading-relaxed text-slate-600">
          {card.pinned ? 'This finding is currently included in the report.' : 'Exploration saved. It is not included in the report yet.'}
        </div>
        <button
          className={`shrink-0 rounded-full px-3 py-2 text-xs font-semibold ${card.pinned ? 'border border-slate-200 bg-white text-slate-600' : 'bg-slate-950 text-white'}`}
          disabled={reportBusy}
          onClick={toggleReportInclusion}
        >
          {card.pinned ? 'Remove from report' : 'Add to report'}
        </button>
      </div>
    </div>
  );
}

function CompareSwipeOverlay({
  map,
  card,
  findingSignature,
  indexByRole,
  drawerOpen,
  onClose,
}: {
  map: Map | null;
  card: FindingCard;
  findingSignature: string;
  indexByRole: Partial<Record<SceneRole, number>>;
  drawerOpen: boolean;
  onClose: () => void;
}) {
  const [split, setSplit] = useState(50);
  const [box, setBox] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const pair = useMemo(() => compareRolePair(card), [card]);

  useEffect(() => {
    if (!map || !pair) {
      setBox(null);
      return undefined;
    }

    let frame = 0;
    const update = () => {
      frame = 0;
      const bbox = findingFocusBbox(card);
      if (!bbox) {
        setBox(null);
        return;
      }
      const nw = map.project([bbox[0], bbox[3]]);
      const se = map.project([bbox[2], bbox[1]]);
      const left = Math.min(nw.x, se.x);
      const top = Math.min(nw.y, se.y);
      const width = Math.abs(se.x - nw.x);
      const height = Math.abs(se.y - nw.y);
      setBox(width > 36 && height > 36 ? { left, top, width, height } : null);
    };
    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(update);
    };

    update();
    map.on('move', schedule);
    map.on('zoom', schedule);
    map.on('resize', schedule);

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      map.off('move', schedule);
      map.off('zoom', schedule);
      map.off('resize', schedule);
    };
  }, [card, findingSignature, map, pair]);

  if (!pair || !box) return null;

  const leftIndex = indexByRole[pair.left] ?? selectedIndex(card, pair.left);
  const rightIndex = indexByRole[pair.right] ?? selectedIndex(card, pair.right);
  const leftScene = selectedScene(card, pair.left);
  const rightScene = selectedScene(card, pair.right);
  const leftUrl = `${imageryPreviewUrl(card.id, pair.left, 1600, leftIndex)}&compare=${pair.left}`;
  const rightUrl = `${imageryPreviewUrl(card.id, pair.right, 1600, rightIndex)}&compare=${pair.right}`;
  const payload = card.payload as any;

  return (
    <div
      className={`compare-swipe-overlay ${drawerOpen ? 'compare-swipe-overlay-drawer-open' : ''}`}
      style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
    >
      <img src={leftUrl} alt={`${roleLabel(pair.left)} selected quicklook`} className="compare-swipe-image" />
      <div className="compare-swipe-right" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <img src={rightUrl} alt={`${roleLabel(pair.right)} selected quicklook`} className="compare-swipe-image" />
      </div>
      <div className="compare-swipe-header">
        <div className="min-w-0">
          <div className="compare-swipe-kicker">Compare swipe</div>
          <div className="compare-swipe-title">{payload?.composite_label ?? 'Optical composite'}</div>
        </div>
        <button type="button" className="compare-swipe-close" aria-label="Close compare swipe" onClick={onClose}>
          <X size={15} />
        </button>
      </div>
      <div className="compare-swipe-label compare-swipe-label-left">
        <span>{roleLabel(pair.left)}</span>
        <strong>{dateOnly(leftScene?.datetime)}</strong>
      </div>
      <div className="compare-swipe-label compare-swipe-label-right">
        <span>{roleLabel(pair.right)}</span>
        <strong>{dateOnly(rightScene?.datetime)}</strong>
      </div>
      <div className="compare-swipe-divider" style={{ left: `${split}%` }}>
        <span />
      </div>
      <input
        aria-label="Swipe between selected optical quicklooks"
        className="compare-swipe-range"
        type="range"
        min="5"
        max="95"
        value={split}
        onChange={(event) => setSplit(Number(event.target.value))}
      />
    </div>
  );
}

function Ba300TimelineControl({
  months,
  activeMonth,
  timeline,
  loading,
  error,
  onMonthChange,
  onClose,
}: {
  months: string[];
  activeMonth: string;
  timeline: BurnedAreaTimelineResponse | null;
  loading: boolean;
  error: string | null;
  onMonthChange: (month: string) => void;
  onClose: () => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const activeIndex = Math.max(0, months.indexOf(activeMonth));
  const metrics = timeline?.metrics;
  const info = [
    ...(timeline?.caveats ?? []),
    timeline?.provenance?.source_product ? `Source: ${timeline.provenance.source_product}` : null,
    timeline?.provenance?.calculation_crs ? `Area calculation CRS: ${timeline.provenance.calculation_crs}` : null,
  ].filter(Boolean);
  return (
    <div className="ba300-timeline-control">
      <button
        type="button"
        aria-label="Close BA300 timeline"
        title="Close BA300 timeline"
        className="ba300-icon-button ba300-close-button"
        onClick={onClose}
      >
        <X size={15} />
      </button>
      <div className="ba300-timeline-header">
        <strong>{monthLabel(activeMonth)}</strong>
        <span>{metrics ? `${metrics.burned_area_occurrence_ha.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha` : '...'}</span>
        <span>{metrics?.cluster_count ?? '...'} clusters</span>
        <button
          type="button"
          aria-label="BA300 timeline information"
          title="BA300 timeline information"
          className="ba300-icon-button"
          onClick={() => setInfoOpen((value) => !value)}
        >
          <Info size={14} />
        </button>
      </div>
      <div className="ba300-slider-row">
        <input
          className="ba300-timeline-slider"
          type="range"
          min={0}
          max={Math.max(0, months.length - 1)}
          step={1}
          value={activeIndex}
          disabled={loading || months.length < 2}
          onChange={(event) => onMonthChange(months[Number(event.target.value)] ?? activeMonth)}
          aria-label="Select BA300 month"
        />
        <div className="ba300-slider-labels">
          <span>{months[0] ?? activeMonth}</span>
          <span>{months[months.length - 1] ?? activeMonth}</span>
        </div>
      </div>
      {loading && <div className="ba300-inline-note">Loading...</div>}
      {error && <div className="ba300-inline-note ba300-inline-error">{error}</div>}
      {infoOpen && (
        <div className="ba300-info-popover">
          {info.length ? info.map((item) => <p key={String(item)}>{item}</p>) : <p>Real BA300 monthly v4 layer.</p>}
        </div>
      )}
    </div>
  );
}

function removeLayerAndSource(map: Map, layerId: string, sourceId: string) {
  if (map.getLayer(layerId)) map.removeLayer(layerId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}

function removeBa300Layers(map: Map) {
  for (const layerId of ['ba300-clusters-line', 'ba300-clusters-fill', 'ba300-active-raster']) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  for (const sourceId of ['ba300-clusters', 'ba300-active-raster']) {
    if (map.getSource(sourceId)) map.removeSource(sourceId);
  }
}

function monthLabel(value: string): string {
  const [year, month] = value.split('-');
  return `${year}-${month}`;
}

function keepOpticalRasterReadable(map: Map) {
  if (!map.getLayer('active-optical-image')) return;
  if (map.getLayer('clusters-line-shadow')) {
    map.moveLayer('active-optical-image', 'clusters-line-shadow');
  }
  if (map.getLayer('imagery-footprints-fill')) {
    map.moveLayer('imagery-footprints-fill', 'active-optical-image');
  }
}

function whenMapStyleReady(map: Map, callback: () => void): () => void {
  let cancelled = false;
  let timer: number | null = null;

  function cleanup() {
    map.off('idle', attempt);
    map.off('styledata', attempt);
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  function schedule() {
    map.once('idle', attempt);
    map.once('styledata', attempt);
    timer = window.setTimeout(attempt, 150);
  }

  function attempt() {
    cleanup();
    if (cancelled) return;
    if (map.isStyleLoaded()) {
      callback();
      return;
    }
    schedule();
  }

  attempt();
  return () => {
    cancelled = true;
    cleanup();
  };
}

export default function MapPanel({ investigationId, finding, focusRequest, uiContext, datasetStatus, findingDrawerOpen, onClusterSelected, onToggleReportInclusion }: Props) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const clustersBoundsRef = useRef<[[number, number], [number, number]] | null>(null);
  const selectedRef = useRef<string | null>(null);
  const onClusterSelectedRef = useRef(onClusterSelected);
  const activeCardSignatureRef = useRef<string | null>(null);
  const latestOpticalIdRef = useRef<string | null>(null);
  const lastForcedFitNonceRef = useRef(0);
  const [, setSelected] = useState<string | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [selectionOverride, setSelectionOverride] = useState<{ findingId: string; findingSignature: string } & Partial<Record<SceneRole, number>> | null>(null);
  const [, setStatus] = useState('Initialising MapLibre workspace...');
  const [error, setError] = useState<string | null>(null);
  const [activeRole, setActiveRole] = useState<SceneRole>('after');
  const [activeOpticalFindingId, setActiveOpticalFindingId] = useState<string | null>(null);
  const [opticalLayerVisible, setOpticalLayerVisible] = useState(true);
  const [compareMode, setCompareMode] = useState(false);
  const [timelineVisible, setTimelineVisible] = useState(true);
  const [activeTimelineMonth, setActiveTimelineMonth] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<BurnedAreaTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const [footprintsVisible, setFootprintsVisible] = useState(false);
  const [layerError, setLayerError] = useState<string | null>(null);
  const imageryCollection = useMemo(() => imageryFeatures(finding), [finding]);
  const latestOpticalCard = useMemo(() => latestOpticalFinding(finding), [finding]);
  const activeOpticalCard = useMemo(() => {
    const requested = activeOpticalFindingId ? finding.find((card) => card.id === activeOpticalFindingId && isOpticalFinding(card)) : null;
    return requested ?? latestOpticalCard;
  }, [activeOpticalFindingId, finding, latestOpticalCard]);
  const activeOpticalSignature = useMemo(() => opticalFindingSignature(activeOpticalCard), [activeOpticalCard]);
  const currentOpticalIndex = useMemo(() => {
    if (!activeOpticalCard) return 0;
    if (
      selectionOverride?.findingId === activeOpticalCard.id
      && selectionOverride.findingSignature === activeOpticalSignature
      && selectionOverride[activeRole] !== undefined
    ) {
      return Number(selectionOverride[activeRole]);
    }
    return selectedIndex(activeOpticalCard, activeRole);
  }, [activeOpticalCard, activeOpticalSignature, activeRole, selectionOverride]);
  const currentOpticalIndices = useMemo(() => {
    if (!activeOpticalCard) return {};
    return Object.fromEntries(SCENE_ROLES.map(({ role }) => {
      const overridden = selectionOverride?.findingId === activeOpticalCard.id
        && selectionOverride.findingSignature === activeOpticalSignature
        && selectionOverride[role] !== undefined
        ? Number(selectionOverride[role])
        : selectedIndex(activeOpticalCard, role);
      return [role, overridden];
    })) as Partial<Record<SceneRole, number>>;
  }, [activeOpticalCard, activeOpticalSignature, selectionOverride]);
  const ba300Months = useMemo(() => {
    const months = datasetStatus?.ba300_monthly_v4?.ingested_months ?? [];
    return Array.from(new Set(months)).sort();
  }, [datasetStatus]);
  const ba300ClusterYear = useMemo(() => {
    const latest = ba300Months[ba300Months.length - 1];
    return latest ? Number(latest.slice(0, 4)) : 2025;
  }, [ba300Months]);

  function handleCapabilityClick(capability: MapCapability) {
    if (!capability.enabled) return;
    const map = mapRef.current;
    if (capability.id === 'before-during-after') {
      if (activeOpticalCard) setOpticalLayerVisible(true);
      setCompareMode(false);
      return;
    }
    if (capability.id === 'burned-area-timeline') {
      setTimelineVisible((current) => !current);
      if (!activeTimelineMonth && ba300Months.length) {
        setActiveTimelineMonth(ba300Months[ba300Months.length - 1]);
      }
      return;
    }
    if (capability.id === 'before-after-swipe') {
      if (!activeOpticalCard) return;
      setOpticalLayerVisible(true);
      setCompareMode((current) => {
        const next = !current;
        if (!current && map) {
          const bbox = findingFocusBbox(activeOpticalCard);
          if (bbox) fitMapToBbox(map, bbox);
        }
        return next;
      });
      return;
    }
    if (capability.id === 'fit-to-aoi' && map) {
      const bbox = activeOpticalCard ? findingFocusBbox(activeOpticalCard) : null;
      if (bbox) {
        fitMapToBbox(map, bbox);
        return;
      }
      if (clustersBoundsRef.current) {
        map.fitBounds(clustersBoundsRef.current, { padding: 90, duration: 520, maxZoom: 6.5 });
      }
    }
  }

  useEffect(() => { onClusterSelectedRef.current = onClusterSelected; }, [onClusterSelected]);

  useEffect(() => {
    if (!latestOpticalCard) {
      latestOpticalIdRef.current = null;
      return;
    }
    if (latestOpticalIdRef.current !== latestOpticalCard.id) {
      latestOpticalIdRef.current = latestOpticalCard.id;
      setActiveOpticalFindingId(latestOpticalCard.id);
      setOpticalLayerVisible(true);
      setCompareMode(false);
      setFocusNonce((nonce) => nonce + 1);
    }
  }, [latestOpticalCard?.id]);

  useEffect(() => {
    if (!activeTimelineMonth && ba300Months.length) {
      setActiveTimelineMonth(ba300Months[ba300Months.length - 1]);
    }
  }, [activeTimelineMonth, ba300Months]);

  useEffect(() => {
    if (ba300Months.length && !timelineVisible) return;
    if (!ba300Months.length) setTimelineVisible(false);
  }, [ba300Months.length, timelineVisible]);

  useEffect(() => {
    if (!timelineVisible || !activeTimelineMonth) return;
    let cancelled = false;
    setTimelineLoading(true);
    setTimelineError(null);
    getBurnedAreaTimeline(activeTimelineMonth)
      .then((result) => {
        if (cancelled) return;
        setTimeline(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setTimeline(null);
          setTimelineError(err instanceof Error ? err.message : 'Could not load BA300 timeline month.');
        }
      })
      .finally(() => {
        if (!cancelled) setTimelineLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTimelineMonth, timelineVisible]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || !map.isStyleLoaded()) return;
    removeBa300Layers(map);
    if (!timelineVisible || !timeline) return;

    const active = timeline.layers.active;
    if (active.tiles.length) {
      map.addSource('ba300-active-raster', {
        type: 'raster',
        tiles: active.tiles,
        tileSize: 256,
        bounds: active.bounds.length === 4 ? active.bounds as [number, number, number, number] : undefined,
        attribution: 'CLMS BA300 monthly v4',
      });
      map.addLayer({
        id: 'ba300-active-raster',
        type: 'raster',
        source: 'ba300-active-raster',
        paint: { 'raster-opacity': active.opacity ?? 0.9, 'raster-fade-duration': 120 },
      }, map.getLayer('clusters-line-shadow') ? 'clusters-line-shadow' : undefined);
    }

    map.addSource('ba300-clusters', { type: 'geojson', data: timeline.clusters, promoteId: 'cluster_id' });
    map.addLayer({
      id: 'ba300-clusters-fill',
      type: 'fill',
      source: 'ba300-clusters',
      paint: {
        'fill-color': '#dc2626',
        'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.44, 0.22],
      },
    });
    map.addLayer({
      id: 'ba300-clusters-line',
      type: 'line',
      source: 'ba300-clusters',
      paint: {
        'line-color': ['case', ['boolean', ['feature-state', 'selected'], false], '#0f172a', '#7f1d1d'],
        'line-opacity': 0.85,
        'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 2.4, 1.4],
      },
    });

    const bounds = active.bounds.length === 4 ? active.bounds as [number, number, number, number] : null;
    if (bounds) fitMapToBbox(map, bounds, 7);
    const onBa300ClusterClick = async (e: maplibregl.MapLayerMouseEvent) => {
      const feature = e.features?.[0];
      const cid = feature?.properties?.cluster_id as string | undefined;
      if (!cid) return;
      if (selectedRef.current) {
        map.setFeatureState({ source: 'ba300-clusters', id: selectedRef.current }, { selected: false });
        if (map.getSource('clusters')) map.setFeatureState({ source: 'clusters', id: selectedRef.current }, { selected: false });
      }
      map.setFeatureState({ source: 'ba300-clusters', id: cid }, { selected: true });
      if (map.getSource('clusters')) map.setFeatureState({ source: 'clusters', id: cid }, { selected: true });
      selectedRef.current = cid;
      setSelected(cid);
      try {
        await onClusterSelectedRef.current(cid);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not select real BA300 cluster.');
      }
    };
    const onBa300ClusterEnter = () => { map.getCanvas().style.cursor = 'pointer'; };
    const onBa300ClusterLeave = () => { map.getCanvas().style.cursor = ''; };
    map.on('click', 'ba300-clusters-fill', onBa300ClusterClick);
    map.on('mouseenter', 'ba300-clusters-fill', onBa300ClusterEnter);
    map.on('mouseleave', 'ba300-clusters-fill', onBa300ClusterLeave);

    return () => {
      if (mapRef.current) {
        mapRef.current.off('click', 'ba300-clusters-fill', onBa300ClusterClick);
        mapRef.current.off('mouseenter', 'ba300-clusters-fill', onBa300ClusterEnter);
        mapRef.current.off('mouseleave', 'ba300-clusters-fill', onBa300ClusterLeave);
        removeBa300Layers(mapRef.current);
      }
    };
  }, [mapLoaded, timeline, timelineVisible]);

  useEffect(() => {
    if (!focusRequest) return;
    const card = finding.find((item) => item.id === focusRequest.findingId);
    if (!card || !isOpticalFinding(card)) return;
    setActiveOpticalFindingId(card.id);
    setOpticalLayerVisible(true);
    setCompareMode(false);
    setFocusNonce((nonce) => nonce + 1);
    const map = mapRef.current;
    const bbox = findingFocusBbox(card);
    if (map && bbox) fitMapToBbox(map, bbox);
    setStatus(`Reopened optical map layer from finding card: ${card.title}`);
  }, [focusRequest?.requestId, finding]);

  useEffect(() => {
    if (!activeOpticalCard) return;
    if (activeCardSignatureRef.current !== activeOpticalSignature) {
      activeCardSignatureRef.current = activeOpticalSignature;
      setActiveRole(defaultSceneRole(activeOpticalCard));
      return;
    }
    const candidates = roleCandidates(activeOpticalCard, activeRole);
    const hasSelectedActiveScene = Boolean(selectedScene(activeOpticalCard, activeRole)) || candidates.length > 0;
    if (!hasSelectedActiveScene) {
      setActiveRole(defaultSceneRole(activeOpticalCard));
    }
  }, [activeOpticalCard?.id, activeOpticalSignature, activeRole]);

  useEffect(() => {
    if (!activeOpticalCard) {
      setSelectionOverride(null);
      setCompareMode(false);
      return;
    }
    if (
      selectionOverride
      && (
        selectionOverride.findingId !== activeOpticalCard.id
        || selectionOverride.findingSignature !== activeOpticalSignature
      )
    ) {
      setSelectionOverride(null);
    }
  }, [activeOpticalCard?.id, activeOpticalSignature, selectionOverride]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || !map.isStyleLoaded()) return;
    const source = map.getSource('imagery-footprints') as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(imageryCollection);
  }, [imageryCollection, mapLoaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || !map.isStyleLoaded()) return;
    for (const layerId of ['imagery-footprints-fill', 'imagery-footprints-line']) {
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', footprintsVisible ? 'visible' : 'none');
    }
    keepOpticalRasterReadable(map);
  }, [footprintsVisible, mapLoaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    let cancelled = false;
    const cancelStyleWait = whenMapStyleReady(map, () => {
      if (cancelled) return;
      setLayerError(null);
      removeLayerAndSource(map, 'active-optical-image', 'active-optical-image');
      if (!activeOpticalCard || !opticalLayerVisible || compareMode) return;

      const activeScene = selectedScene(activeOpticalCard, activeRole);
      const canRender = activeScene?.source === 'stac';
      if (!canRender) return;

      imageryMapLayer(activeOpticalCard.id, activeRole, 1600, currentOpticalIndex)
        .then((layer) => {
          if (cancelled || !mapRef.current) return;
          const currentMap = mapRef.current;
          removeLayerAndSource(currentMap, 'active-optical-image', 'active-optical-image');
          if (layer.kind === 'raster_tile') {
            if (!layer.tiles?.length) throw new Error('Tiler mode did not return any raster tile URLs.');
            currentMap.addSource('active-optical-image', {
              type: 'raster',
              tiles: layer.tiles,
              tileSize: layer.tile_size ?? 256,
              attribution: layer.attribution,
              bounds: layer.bounds,
            });
            const mapBounds = currentMap.getBounds();
            const sceneIntersects = !(mapBounds.getEast() < layer.bounds[0] || mapBounds.getWest() > layer.bounds[2] || mapBounds.getNorth() < layer.bounds[1] || mapBounds.getSouth() > layer.bounds[3]);
            const belowSuggestedZoom = layer.minzoom !== undefined && currentMap.getZoom() < layer.minzoom;
            const forceFit = focusNonce !== lastForcedFitNonceRef.current;
            if (forceFit) {
              fitMapToBbox(currentMap, findingFocusBbox(activeOpticalCard) ?? layer.bounds, layer.maxzoom ?? 12);
              lastForcedFitNonceRef.current = focusNonce;
            } else if (!sceneIntersects || belowSuggestedZoom) {
              fitMapToBbox(currentMap, layer.bounds, layer.maxzoom ?? 12);
            }
          } else {
            if (!layer.url || !layer.coordinates) throw new Error('Preview-image mode did not return an image URL and coordinates.');
            currentMap.addSource('active-optical-image', {
              type: 'image',
              url: `${layer.url}&_=${Date.now()}`,
              coordinates: layer.coordinates,
            });
            const forceFit = focusNonce !== lastForcedFitNonceRef.current;
            if (forceFit) {
              fitMapToBbox(currentMap, findingFocusBbox(activeOpticalCard) ?? layer.bounds, layer.maxzoom ?? 12);
              lastForcedFitNonceRef.current = focusNonce;
            }
          }
          currentMap.addLayer({
            id: 'active-optical-image',
            type: 'raster',
            source: 'active-optical-image',
            maxzoom: layer.maxzoom,
            paint: { 'raster-opacity': 1, 'raster-fade-duration': 120 },
          }, currentMap.getLayer('clusters-line-shadow') ? 'clusters-line-shadow' : undefined);
          keepOpticalRasterReadable(currentMap);
        })
        .catch((err) => {
          if (!cancelled) setLayerError(err instanceof Error ? err.message : 'Could not render optical image layer.');
        });
    });
    return () => {
      cancelled = true;
      cancelStyleWait();
    };
  }, [activeOpticalSignature, activeRole, compareMode, currentOpticalIndex, mapLoaded, opticalLayerVisible, focusNonce]);

  useEffect(() => {
    if (!divRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: divRef.current,
      style: DEMO_STYLE,
      center: [23.7, 39.1],
      zoom: 5.7,
      minZoom: 4,
      maxZoom: 13,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');

    map.on('error', (event) => {
      const message = event.error?.message ?? 'Map rendering error';
      const sourceId = (event as any).sourceId;
      if (sourceId === 'active-optical-image') {
        setLayerError(`Optical tile error: ${message}`);
        return;
      }
      if (!message.toLowerCase().includes('tile')) setError(message);
    });

    map.on('load', async () => {
      setMapLoaded(true);
      try {
        setStatus('Loading Greece burn clusters…');
        const clusters = await getClusters(ba300ClusterYear);

        map.addSource('clusters', { type: 'geojson', data: clusters, promoteId: 'cluster_id' });
        map.addLayer({
          id: 'clusters-fill',
          type: 'fill',
          source: 'clusters',
          paint: {
            'fill-color': ['interpolate', ['linear'], ['get', 'area_ha'], 2_500, '#eab308', 20_000, '#d97706', 60_000, '#b91c1c'],
            'fill-opacity': 0.32,
          },
        });
        map.addLayer({
          id: 'clusters-line-shadow',
          type: 'line',
          source: 'clusters',
          paint: {
            'line-color': '#713f12',
            'line-opacity': 0.55,
            'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 6, 2.6],
          },
        });
        map.addLayer({
          id: 'clusters-line',
          type: 'line',
          source: 'clusters',
          paint: {
            'line-color': '#ffffff',
            'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 4, 1.8],
          },
        });

        map.addSource('imagery-footprints', { type: 'geojson', data: imageryCollection });
        map.addLayer({
          id: 'imagery-footprints-fill',
          type: 'fill',
          source: 'imagery-footprints',
          layout: { visibility: footprintsVisible ? 'visible' : 'none' },
          paint: {
            'fill-color': ['match', ['get', 'role'], 'pre-fire', '#2563eb', 'post-fire', '#0891b2', 'during-window', '#7c3aed', '#0f766e'],
            'fill-opacity': 0.025,
          },
        });
        map.addLayer({
          id: 'imagery-footprints-line',
          type: 'line',
          source: 'imagery-footprints',
          layout: { visibility: footprintsVisible ? 'visible' : 'none' },
          paint: {
            'line-color': ['match', ['get', 'role'], 'pre-fire', '#2563eb', 'post-fire', '#0891b2', 'during-window', '#7c3aed', '#0f766e'],
            'line-width': 2.0,
            'line-dasharray': [2, 1.2],
            'line-opacity': 0.75,
          },
        });

        const bounds = featureBounds(clusters);
        if (bounds) {
          clustersBoundsRef.current = bounds;
          map.fitBounds(bounds, { padding: 90, duration: 850, maxZoom: 6.5 });
        }

        map.on('click', 'clusters-fill', async (e) => {
          const feature = e.features?.[0];
          if (!feature) return;
          const cid = feature.properties?.cluster_id as string | undefined;
          if (!cid) return;
          if (selectedRef.current) map.setFeatureState({ source: 'clusters', id: selectedRef.current }, { selected: false });
          map.setFeatureState({ source: 'clusters', id: cid }, { selected: true });
          selectedRef.current = cid;
          setSelected(cid);
          try {
            await selectCluster(investigationId, cid);
            onClusterSelectedRef.current(cid);
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not select cluster. Is the backend running?');
          }
          const area = Number(feature.properties?.area_ha ?? 0).toLocaleString();
          const region = feature.properties?.admin_region ?? '';
          const burnStart = feature.properties?.burn_window_start ?? 'n/a';
          const burnEnd = feature.properties?.burn_window_end ?? 'n/a';
          new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 16, maxWidth: '260px' })
            .setLngLat(e.lngLat)
            .setHTML(`<div class="wea-popup-title">${cid}</div><div class="wea-popup-metric">${area} ha</div><div class="wea-popup-meta">${region}</div><div class="wea-popup-meta">Burn window: ${burnStart} → ${burnEnd}</div>`)
            .addTo(map);
        });

        map.on('click', 'imagery-footprints-line', (e) => {
          const feature = e.features?.[0];
          if (!feature) return;
          const p = feature.properties ?? {};
          new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 16, maxWidth: '280px' })
            .setLngLat(e.lngLat)
            .setHTML(`<div class="wea-popup-title">${p.sensor ?? 'Optical imagery'}</div><div class="wea-popup-metric">${p.role ?? 'candidate'} · ${p.composite ?? ''}</div><div class="wea-popup-meta">${p.datetime ?? 'n/a'}</div><div class="wea-popup-meta">Cloud cover: ${p.cloud_cover ?? 'n/a'}%</div><div class="wea-popup-meta">AOI coverage: ${p.coverage_percent ?? 'n/a'}%</div><div class="wea-popup-meta">${p.item_id ?? ''}</div>`)
            .addTo(map);
        });

        for (const layerId of ['clusters-fill', 'imagery-footprints-line']) {
          map.on('mouseenter', layerId, () => { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', layerId, () => { map.getCanvas().style.cursor = ''; });
        }

        setStatus('Map ready. Run an optical imagery skill to render selected before/after STAC imagery as raster tiles from the local custom tiler. Use the optical control to review alternatives.');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not load clusters. Check the backend API.');
        setStatus('Map rendered, but cluster data could not be loaded.');
      }
    });

    mapRef.current = map;
    return () => { setMapLoaded(false); map.remove(); mapRef.current = null; };
  }, [ba300ClusterYear, investigationId]);

  return (
    <main className="map-surface relative h-full min-w-[420px] overflow-hidden bg-white">
      <div ref={divRef} className="absolute inset-0" />
      <MapToolStrip
        context={uiContext}
        activeToolIds={[
          ...(compareMode ? ['before-after-swipe' as const] : []),
          ...(timelineVisible ? ['burned-area-timeline' as const] : []),
        ]}
        onCapabilityClick={handleCapabilityClick}
      />
      {(error || layerError) && (
        <div className="map-alerts">
        {error && <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{error}</div>}
        {layerError && <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs leading-relaxed text-rose-700">{layerError}</div>}
        </div>
      )}
      {activeOpticalCard && opticalLayerVisible && !compareMode && (
        <OpticalMapControl
          card={activeOpticalCard}
          activeRole={activeRole}
          setActiveRole={setActiveRole}
          footprintsVisible={footprintsVisible}
          setFootprintsVisible={setFootprintsVisible}
          selectedIndexOverride={currentOpticalIndex}
          drawerOpen={findingDrawerOpen}
          onCloseLayer={() => {
            setOpticalLayerVisible(false);
            setCompareMode(false);
          }}
          onCandidateSelected={(role, index) => setSelectionOverride((prev) => ({
            ...(prev?.findingId === activeOpticalCard.id && prev.findingSignature === activeOpticalSignature ? prev : {}),
            findingId: activeOpticalCard.id,
            findingSignature: activeOpticalSignature,
            [role]: index,
          }))}
          onSelectionChanged={onClusterSelectedRef.current}
          onToggleReportInclusion={onToggleReportInclusion}
        />
      )}
      {activeOpticalCard && opticalLayerVisible && compareMode && (
        <CompareSwipeOverlay
          map={mapRef.current}
          card={activeOpticalCard}
          findingSignature={activeOpticalSignature}
          indexByRole={currentOpticalIndices}
          drawerOpen={findingDrawerOpen}
          onClose={() => setCompareMode(false)}
        />
      )}
      {timelineVisible && activeTimelineMonth && (
        <Ba300TimelineControl
          months={ba300Months.length ? ba300Months : [activeTimelineMonth]}
          activeMonth={activeTimelineMonth}
          timeline={timeline}
          loading={timelineLoading}
          error={timelineError}
          onMonthChange={setActiveTimelineMonth}
          onClose={() => {
            setTimelineVisible(false);
            setTimeline(null);
            const map = mapRef.current;
            if (map) removeBa300Layers(map);
          }}
        />
      )}
    </main>
  );
}
