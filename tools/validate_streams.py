"""Validate independent public streams entirely from committed candidate bytes."""

import argparse
import json
from pathlib import Path

from feed_integrity import (
    food_feed_revision,
    membership_revision,
    vendor_feed_revision,
    vendor_price_revision,
)
from jsonschema import Draft202012Validator, FormatChecker
from validate_distribution import ROOT, metadata, metadata_delta, pages, prices, require

VENDORS = ("aldi", "coles", "drakes", "iga", "woolies")
STATES = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}


def assets(index, *, owned=False):
    if "snapshot" in index:
        return [index["snapshot"]["archive"]] + (
            [index["delta"]["archive"]] if index.get("delta") else []
        )
    result = []
    for package in index["packages"]:
        if owned and package["release_tag"] != index["release_tag"]:
            continue
        result.append(package["archive"])
        if package.get("delta_archive"):
            result.append(package["delta_archive"])
    return result


def locations(index):
    if "snapshot" in index:
        return "distribution/v2/candidate-food.json", "distribution/v2/food.json", "food.json"
    vendor = index["store_code"]
    require(vendor in VENDORS, "Unknown vendor")
    return (
        f"distribution/v2/prices/candidate-{vendor}.json",
        f"distribution/v2/prices/{vendor}.json",
        f"{vendor}.json",
    )


def validate(index_path, schema_path=ROOT / "schema/catalogue-distribution-v2.json"):
    require(not index_path.is_symlink(), "Index must be an ordinary file")
    require(index_path.stat().st_size <= 2 * 1024 * 1024, "Index byte budget exceeded")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    definitions = json.loads(schema_path.read_text(encoding="utf-8"))
    validators = {
        key: Draft202012Validator(value, format_checker=FormatChecker())
        for key, value in definitions.items()
    }
    food = "snapshot" in index
    validators["food_index" if food else "vendor_index"].validate(index)
    expected = food_feed_revision(index) if food else vendor_feed_revision(index)
    tag = "food-v2-" if food else f"prices-v2-{index['store_code']}-"
    require(
        index["data_revision"] == expected and index["release_tag"] == tag + expected,
        "Feed semantic revision mismatch",
    )
    all_assets = assets(index)
    require(
        len({asset["path"] for asset in all_assets}) == len(all_assets), "Duplicate archive names"
    )
    require(len(all_assets) < 1000, "Release asset budget exceeded")
    directory = index_path.parent
    if food:
        content = metadata(
            index["snapshot"],
            pages(directory, index["snapshot"]["archive"], validators["catalogue_page"]),
        )
        require(len(index["memberships"]) == len(VENDORS), "Missing vendor membership")
        expected_memberships = []
        for vendor in VENDORS:
            ids = {row["product_id"] for row in content["products"] if row["store_code"] == vendor}
            expected_memberships.append(
                {
                    "store_code": vendor,
                    "membership_revision": membership_revision(ids),
                    "product_count": len(ids),
                }
            )
        require(
            sorted(index["memberships"], key=lambda row: row["store_code"]) == expected_memberships,
            "Food vendor membership mismatch",
        )
        require(
            sum(row["product_count"] for row in expected_memberships) == len(content["products"]),
            "Food contains an unsupported vendor",
        )
        if index.get("delta"):
            delta, snapshot = index["delta"]["manifest"], index["snapshot"]["manifest"]
            require(
                delta["mode"] == "delta"
                and delta.get("base_release_id")
                and delta["base_release_id"] != snapshot["release_id"],
                "Invalid food delta base",
            )
            require(
                all(
                    delta[key] == snapshot[key]
                    for key in ("release_id", "content_revision", "product_count", "recipe_count")
                ),
                "Food delta targets a different snapshot",
            )
            metadata_delta(
                index["delta"],
                pages(directory, index["delta"]["archive"], validators["catalogue_page"]),
                index["snapshot"],
                content,
            )
    else:
        require(
            len(index["packages"]) == 8
            and {p["manifest"]["context"]["state"] for p in index["packages"]} == STATES,
            "Vendor feed requires exactly eight unique states",
        )
        for package in index["packages"]:
            manifest = package["manifest"]
            context = manifest["context"]
            require(
                context["store_code"] == index["store_code"]
                and package["release_tag"].startswith(f"prices-v2-{index['store_code']}-"),
                "Archive owner/context belongs to another vendor",
            )
            full = pages(directory, package["archive"], validators["price_page"])
            ids = {identity for page in full for identity in page["requested_ids"]}
            require(
                all(identity.startswith(index["store_code"] + "_") for identity in ids)
                and membership_revision(ids) == context["membership_revision"],
                "Price membership mismatch",
            )
            prices(package, full, ids, price_identity=vendor_price_revision)
            require(
                bool(package.get("base_release_id")) == bool(package.get("delta_archive")),
                "Price patch needs exact base",
            )
            if package.get("delta_archive"):
                require(
                    package["base_release_id"] != manifest["release_id"],
                    "Price patch targets itself",
                )
                patch = pages(directory, package["delta_archive"], validators["price_page"])
                require(
                    0 < len(patch) < len(full)
                    and all(
                        p["page_number"] < len(full) and p == full[p["page_number"]] for p in patch
                    ),
                    "Price patch differs from complete target",
                )
    return index


def candidates(root=ROOT):
    food = root / "distribution/v2/candidate-food.json"
    result = [food] if food.exists() else []
    result.extend(
        root / f"distribution/v2/prices/candidate-{vendor}.json"
        for vendor in VENDORS
        if (root / f"distribution/v2/prices/candidate-{vendor}.json").exists()
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path)
    args = parser.parse_args()
    checked = []
    for path in [args.index] if args.index else candidates():
        checked.append(validate(path)["release_tag"])
    print(json.dumps({"validated_streams": checked}))
