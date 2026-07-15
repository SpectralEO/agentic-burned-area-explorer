from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingestion.ba300_service import import_input


def main() -> None:
    parser = argparse.ArgumentParser(description="Import manually downloaded CLMS BA300 monthly v4 files.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--aoi", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = import_input(args.input, aoi_path=args.aoi, force=args.force, dry_run=args.dry_run, limit=args.limit)
    if result.get("status") == "no_products_detected":
        raise SystemExit(f"No BA300 GeoTIFF/COG band set was detected under {args.input}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
