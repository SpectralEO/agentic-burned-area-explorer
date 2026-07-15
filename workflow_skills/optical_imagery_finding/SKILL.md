# Optical Imagery Finding

Use this skill when the user asks for pre/post optical imagery, Sentinel-2, Landsat, MODIS, true colour, false colour, SWIR, or fire-front/highlight composites for a selected burn cluster.

## Intent examples

- Show before/after Sentinel-2 imagery for this cluster.
- Find a false colour composite.
- Use Landsat as fallback.
- Show a fire-front highlight image using SWIR.
- Use MODIS for broad context.

## Procedure

1. Require a selected burn cluster.
2. Resolve the user sensor intent:
   - Sentinel-2 / S2 → `sentinel-2`
   - Landsat / L8 / L9 → `landsat`
   - MODIS / Terra / Aqua → `modis`
   - unspecified → `any`, preferring Sentinel-2 then Landsat.
3. Resolve the user composite intent:
   - RGB / natural colour / true colour → `true_color`
   - false colour / NIR → `false_color`
   - SWIR / shortwave infrared / fire front / highlight / blend → `fire_front_highlight`.
   - Handle fire-front highlight as natural-colour RGB blended with SWIR finding, following the ESA-style 23 August 2023 Evros/Alexandroupoli example; do not handle it as plain SWIR/NIR/red false colour.
4. Infer the burn window from the selected cluster metadata. In real CLMS mode this should use DOB/monthly detections and product caveats.
5. Search pre-fire and post-fire windows separately. For fire-front highlight, also search the event date/window when one is supplied or stored on the cluster.
6. Rank candidates by cloud cover, temporal bracketing, and footprint intersection/coverage.
7. Create a supporting finding card that includes sensor, composite recipe, candidate scenes, selected pair, reason, burn window, and caveats.

## Composite rules

- True colour is visual orientation finding.
- False colour is supporting finding for burn-scar/vegetation contrast.
- Fire-front highlight is a natural-colour/SWIR visualisation recipe. It is not an active-fire detection algorithm.
- MODIS is coarse contextual finding and should not be handleed as cluster-level perimeter validation.

## Caveats

This MVP can run in `mock`, `auto`, or `real` STAC mode. Production use should validate cloud masks, asset-level coverage, band availability, scene geometry, and whether a composite recipe is appropriate for the requested sensor.
