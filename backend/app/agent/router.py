from __future__ import annotations

import re
from typing import Any

from app.models import SuggestedAction


DEFAULT_ACTIONS = [
    SuggestedAction(id="ask_burned_area", label="How much burned?", skill_id="burned_area_accounting"),
    SuggestedAction(id="show_clusters", label="Show largest clusters", skill_id="burn_cluster_investigation"),
    SuggestedAction(id="find_multisensor_false_colour", label="Sentinel-2 + Landsat quicklooks", skill_id="optical_imagery_finding", requires=["selected_cluster"], parameters={"sensor": "any", "composite": "false_color"}),
    SuggestedAction(id="find_s2_false_colour", label="Sentinel-2 false colour", skill_id="optical_imagery_finding", requires=["selected_cluster"], parameters={"sensor": "sentinel-2", "composite": "false_color"}),
    SuggestedAction(id="generate_report", label="Generate finding brief", skill_id="wildfire_finding_brief"),
]


def select_skill(message: str, state: dict[str, Any]) -> tuple[str | None, str, dict[str, Any]]:
    m = message.lower().strip()
    params = extract_parameters(m)
    if re.search(r"\b(natura\s*2000|natura|ramsar|protected area|protected areas)\b", m):
        return None, "Real protected-area overlap workflows are not loaded yet.", params
    rules: list[tuple[str, str]] = [
        (r"\b(report|brief|write.*up|summary document)\b", "wildfire_finding_brief"),
        (r"\b(aod|smoke|aerosol|cams)\b", "aod_context"),
        (r"\b(drought|dry|era5|soil moisture|precipitation|temperature anomaly)\b", "drought_context"),
        (r"\b(ghsl|population|built.?up|exposure|settlement)\b", "ghsl_exposure_context"),
        (r"\b(land.?cover|forest|cropland|worldcover|tree cover|shrub)\b", "landcover_impact"),
        (r"\b(sentinel|sentinel-?2|s2|landsat|modis|imagery|image|before|after|optical|stac|false colou?r|true colou?r|natural colou?r|rgb|swir|shortwave|fire front|composite)\b", "optical_imagery_finding"),
        (r"\b(cluster|clusters|largest|event|where|open|inspect)\b", "burn_cluster_investigation"),
        (r"\b(how much|burned area|hectare|hectares|km2|km²|monthly|annual|20\d{2})\b", "burned_area_accounting"),
    ]
    for pattern, skill in rules:
        if re.search(pattern, m):
            details = []
            if params.get("sensor"):
                details.append(f"sensor={params['sensor']}")
            if params.get("composite"):
                details.append(f"composite={params['composite']}")
            suffix = f" Extracted {', '.join(details)}." if details else ""
            return skill, f"Matched intent pattern `{pattern}`.{suffix}", params
    return None, "No high-confidence skill match.", params


def extract_parameters(message: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    years = sorted({int(value) for value in re.findall(r"\b(20\d{2})\b", message) if int(value) >= 2001})
    if years:
        params["years"] = years
        params["year"] = years[-1]

    has_sentinel = re.search(r"\b(sentinel\s*-?\s*2|sentinel2|sentinel|s2)\b", message)
    has_landsat = re.search(r"\b(landsat|l8|l9|oli)\b", message)
    has_modis = re.search(r"\b(modis|terra|aqua)\b", message)
    wants_multi_sensor = re.search(
        r"\b(both|mixed|multi[-\s]?sensor|all\s+optical|any\s+sensor|best\s+available|fallback|mix\s+and\s+match)\b",
        message,
    )

    if (has_sentinel and has_landsat) or wants_multi_sensor:
        params["sensor"] = "any"
    elif has_sentinel:
        params["sensor"] = "sentinel-2"
    elif has_landsat:
        params["sensor"] = "landsat"
    elif has_modis:
        params["sensor"] = "modis"

    if re.search(r"\b(fire\s*front|front\s*highlight|shortwave|shortwave infrared|swir|active fire|hot edge|blend)\b", message):
        params["composite"] = "fire_front_highlight"
    elif re.search(r"\b(false\s*colou?r|false\s*rgb|nir|near infrared)\b", message):
        params["composite"] = "false_color"
    elif re.search(r"\b(true\s*colou?r|natural\s*colou?r|natural color|rgb)\b", message):
        params["composite"] = "true_color"

    cloud_match = re.search(r"(?:cloud|clouds|cloud cover)\D{0,12}(\d{1,2})(?:\s*%)?", message)
    if cloud_match:
        params["max_cloud"] = float(cloud_match.group(1))

    iso_date = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", message)
    if iso_date:
        params["event_date"] = iso_date.group(0)
    else:
        month_names = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        date_match = re.search(
            r"\b([0-3]?\d)\s+"
            r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
            r"\s+(20\d{2})\b",
            message,
        )
        if date_match:
            day = int(date_match.group(1))
            month = month_names[date_match.group(2)]
            year = int(date_match.group(3))
            params["event_date"] = f"{year:04d}-{month:02d}-{day:02d}"

    return params
