# ERA5 Drought Context

Add pre-fire environmental dryness context for a selected cluster.

## Use when

The user asks for this analytical procedure during a wildfire finding investigation.

## Operating rules

- Call deterministic backend tools; do not let the LLM compute EO metrics directly.
- Create structured finding cards for outputs that may enter a report.
- Include source dataset, method, parameters, and caveats.
- Preserve the distinction between primary, supporting, contextual, and validation finding.
- Avoid emergency-response, legal, damage, or casualty claims.

## Caveats

This MVP uses synthetic demo data. Production use must connect to real CLMS BA, Sentinel/Landsat STAC, WorldCover, GHSL, CAMS, and ERA5 integrations with validated preprocessing.
