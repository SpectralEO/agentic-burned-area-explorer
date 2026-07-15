from __future__ import annotations

import argparse
import json

from app.ingestion.ba300_common import asset_summary, classify_assets, iter_periods, manual_download_payload, parse_period, search_month


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover CLMS BA300 monthly v4 STAC items.")
    parser.add_argument("--start", required=True, type=parse_period)
    parser.add_argument("--end", required=True, type=parse_period)
    parser.add_argument("--aoi")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    results = []
    for period in iter_periods(args.start, args.end):
        items = search_month(period, limit=args.limit)
        for item in items:
            classified = classify_assets(item)
            direct_bands = sorted(classified["bands"].keys())
            strategy = "stac-download" if {"bf", "cp", "dob", "lfp"}.issubset(direct_bands) else "manual_download_required"
            results.append(
                {
                    "period": period.label,
                    "item_id": item.get("id"),
                    "datetime": item.get("properties", {}).get("datetime"),
                    "start_datetime": item.get("properties", {}).get("start_datetime"),
                    "end_datetime": item.get("properties", {}).get("end_datetime"),
                    "assets": asset_summary(item),
                    "detected_bands": direct_bands,
                    "archives": [a.get("key") for a in classified["archives"]],
                    "selected_retrieval_strategy": strategy,
                    "authentication_required": True,
                    "expected_output_paths": {
                        "manifest": f"data/real/ba300/manifests/{period.label}.json",
                        "clipped": f"data/real/ba300/clipped/GR/{period.year:04d}/{period.month:02d}/",
                        "monthly_stats": "data/real/ba300/derived/GR/monthly_stats.parquet",
                    },
                    "manual_download": manual_download_payload(period, item, aoi=args.aoi),
                }
            )
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
