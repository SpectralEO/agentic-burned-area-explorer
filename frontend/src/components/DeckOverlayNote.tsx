/**
 * Optional extension point for deck.gl overlays.
 *
 * The v1 demo uses MapLibre layers directly. For dense gridded AOD/ERA5 layers,
 * temporal animations, large STAC footprint sets, or GPU-heavy analytics, add a
 * deck.gl overlay here and mount it inside MapPanel.
 */
export default function DeckOverlayNote() {
  return null;
}
