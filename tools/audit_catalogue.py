"""Verify published v2 bytes and report GTIN coverage without modifying releases."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from validate_distribution import ROOT, metadata, pages, require
from validate_streams import VENDORS, validate


def coverage(products):
    result = {}
    for vendor in VENDORS:
        records = [p for p in products if p["store_code"] == vendor]
        linked = sum(p.get("gtin_id") is not None for p in records)
        verified = sum(p.get("gtin_verified") is True for p in records)
        result[vendor] = {
            "products": len(records),
            "with_barcode": sum(bool(p.get("barcode")) for p in records),
            "linked_gtin": linked,
            "without_gtin_link": len(records) - linked,
            "verified": verified,
            "not_verified": len(records) - verified,
            "verified_without_link": sum(
                p.get("gtin_verified") is True and p.get("gtin_id") is None
                for p in records
            ),
        }
    require(
        sum(row["products"] for row in result.values()) == len(products),
        "Unknown retailer",
    )
    return result


def audit(root=ROOT):
    schema = root / "schema/catalogue-distribution-v2.json"
    paths = [root / "distribution/v2/food.json"] + [
        root / f"distribution/v2/prices/{vendor}.json" for vendor in VENDORS
    ]
    indexes = [validate(path, schema) for path in paths]
    food = indexes[0]
    definition = json.loads(schema.read_text(encoding="utf-8"))["catalogue_page"]
    values = pages(
        paths[0].parent,
        food["snapshot"]["archive"],
        Draft202012Validator(definition, format_checker=FormatChecker()),
    )
    products = metadata(food["snapshot"], values)["products"]
    streams = {}
    for path, index in zip(paths, indexes):
        candidate_path = path.with_name("candidate-" + path.name)
        candidate = (
            json.loads(candidate_path.read_text(encoding="utf-8"))
            if candidate_path.exists()
            else None
        )
        streams[index.get("store_code", "food")] = {
            "release_tag": index["release_tag"],
            "published_at": index["published_at"],
            "candidate_matches_current": (
                candidate["data_revision"] == index["data_revision"]
                if candidate
                else None
            ),
        }
    return {
        "food_release_tag": food["release_tag"],
        "catalogue_release_id": food["snapshot"]["manifest"]["release_id"],
        "product_count": len(products),
        "retailers": coverage(products),
        "streams": streams,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(audit(args.root.resolve()), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
