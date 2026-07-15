from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingestion.ba300_common import parse_period
from app.ingestion.ba300_service import sync_range


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise CLMS BA300 monthly v4 products.")
    parser.add_argument("--start", required=True, type=parse_period)
    parser.add_argument("--end", required=True, type=parse_period)
    parser.add_argument("--aoi", required=True, type=Path)
    parser.add_argument("--source", choices=["auto", "stac-download", "sentinel-hub", "local"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(
        json.dumps(
            sync_range(
                args.start,
                args.end,
                aoi_path=args.aoi,
                source=args.source,
                dry_run=args.dry_run,
                force=args.force,
                limit=args.limit,
                preprocess=True,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
