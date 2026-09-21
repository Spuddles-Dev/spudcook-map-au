"""Validate a candidate without backend access, credentials or archive extraction."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

from catalogue_integrity import catalogue_checksum
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MAX_PAGE_BYTES = 2 * 1024 * 1024 + 4096
MAX_PAGES = 2000
PAGE_NAME = re.compile(r"page-([0-9]{5})\.json")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def assets(index):
    result = [index["snapshot"]["archive"]]
    if index.get("delta"):
        result.append(index["delta"]["archive"])
    for package in index["prices"]:
        result.append(package["archive"])
        if package.get("delta_archive"):
            result.append(package["delta_archive"])
    return result


def semantic_price(manifest):
    return {key: manifest[key] for key in ("context", "product_count", "page_checksums")}


def revision(index):
    manifest = index["snapshot"]["manifest"]
    return catalogue_checksum(
        {
            "format_version": 1,
            "minimum_app_build": index["minimum_app_build"],
            "catalogue_release_id": manifest["release_id"],
            "catalogue_content_revision": manifest["content_revision"],
            "prices": [
                semantic_price(p["manifest"])
                for p in sorted(
                    index["prices"],
                    key=lambda p: (
                        p["manifest"]["context"]["state"],
                        p["manifest"]["context"]["store_code"],
                    ),
                )
            ],
        }
    )


def pages(directory, asset, validator):
    path = directory / asset["path"]
    require(not path.is_symlink() and path.is_file(), "Archive must be an ordinary file")
    require(path.stat().st_size == asset["byte_length"], "Archive compressed size mismatch")
    require(
        hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"], "Archive SHA256 mismatch"
    )
    result, total, names = [], 0, set()
    with zipfile.ZipFile(path) as archive:
        require(len(archive.infolist()) <= MAX_PAGES, "Archive page budget exceeded")
        for member in archive.infolist():
            match = PAGE_NAME.fullmatch(member.filename)
            require(
                match is not None and member.filename not in names, "Unsafe or duplicate ZIP member"
            )
            require(
                not member.flag_bits & 1 and not member.is_dir(), "Encrypted/directory ZIP member"
            )
            require(
                (member.external_attr >> 16) & 0o170000 in (0, 0o100000), "ZIP links are forbidden"
            )
            require(
                member.compress_type == zipfile.ZIP_DEFLATED and member.file_size <= MAX_PAGE_BYTES,
                "ZIP page budget/compression mismatch",
            )
            names.add(member.filename)
            total += member.file_size
            require(total <= asset["uncompressed_bytes"], "Archive expanded budget exceeded")
            with archive.open(member) as stream:
                body = stream.read(MAX_PAGE_BYTES + 1)
            require(len(body) == member.file_size, "ZIP member length mismatch")
            page = json.loads(body)
            validator.validate(page)
            require(page["page_number"] == int(match[1]), "Page filename/identity mismatch")
            result.append(page)
    require(total == asset["uncompressed_bytes"], "Archive expanded size mismatch")
    return sorted(result, key=lambda p: p["page_number"])


def metadata(package, values):
    manifest = package["manifest"]
    require(
        len(values) == manifest["page_count"] == len(manifest["page_checksums"]),
        "Metadata page count mismatch",
    )
    combined = {}
    for number, page in enumerate(values):
        require(
            page["page_number"] == number
            and page["release_id"] == manifest["release_id"]
            and page["mode"] == manifest["mode"]
            and page.get("base_release_id") == manifest.get("base_release_id"),
            "Metadata page envelope mismatch",
        )
        require(
            page["checksum"]
            == manifest["page_checksums"][number]
            == catalogue_checksum(page["content"]),
            "Metadata semantic checksum mismatch",
        )
        for key, value in page["content"].items():
            if isinstance(value, list):
                combined.setdefault(key, []).extend(value)
            elif value is not None:
                require(key not in combined, "Duplicate metadata singleton section")
                combined[key] = value
    if manifest["mode"] == "delta":
        return combined
    require(
        manifest["mode"] == "snapshot" and manifest.get("base_release_id") is None,
        "Expected complete snapshot",
    )
    require(
        not combined.get("removed_product_ids") and not combined.get("removed_recipe_ids"),
        "Snapshot contains removals",
    )
    require(
        catalogue_checksum(combined) == manifest["content_revision"],
        "Complete metadata checksum mismatch",
    )
    products, recipes = combined["products"], combined["recipes"]
    require(
        len(products) == manifest["product_count"] and len(recipes) == manifest["recipe_count"],
        "Metadata record count mismatch",
    )
    require(
        len({p["product_id"] for p in products}) == len(products)
        and len({r["recipe_id"] for r in recipes}) == len(recipes),
        "Duplicate product/recipe IDs",
    )
    require(
        combined.get("app_categories") is not None
        and combined.get("ingredient_taxonomy") is not None,
        "Missing reference tree",
    )
    nutrition = {r["reference_id"]: r["nutrition"] for r in combined["nutrition_references"]}
    require(len(nutrition) == len(combined["nutrition_references"]), "Duplicate nutrition identity")
    for identity, panel in nutrition.items():
        require(
            panel["source_kind"] != "user" and catalogue_checksum(panel) == identity,
            "Private/incorrect nutrition reference",
        )
    for product in products:
        facts = product.get("food_facts")
        if facts:
            require(facts["product_id"] == product["product_id"], "Food facts identity mismatch")
            require(
                not facts.get("nutrition_reference_id")
                or facts["nutrition_reference_id"] in nutrition,
                "Unresolved nutrition reference",
            )
            require(
                not facts.get("nutrition") or facts["nutrition"]["source_kind"] != "user",
                "Private nutrition in public product",
            )
    require(
        all(r["nutrition"]["source_kind"] != "user" for r in combined["ingredient_nutrition"]),
        "Private ingredient nutrition",
    )
    return combined


def prices(package, values, membership, *, price_identity=None):
    manifest = package["manifest"]
    context = manifest["context"]
    require(
        manifest["release_id"] == (
            catalogue_checksum(semantic_price(manifest))
            if price_identity is None else price_identity(manifest)
        ),
        "Price release identity mismatch",
    )
    require(
        len(values) == manifest["page_count"] == len(manifest["page_checksums"]),
        "Price page count mismatch",
    )
    seen = set()
    for number, page in enumerate(values):
        require(
            page["page_number"] == number and page["release_id"] == manifest["release_id"],
            "Price page envelope mismatch",
        )
        content = page["content"]
        require(
            content["state"] == context["state"] and content["currency_code"] == "AUD",
            "Price context mismatch",
        )
        requested = set(page["requested_ids"])
        found, missing = set(content["prices"]), set(content["not_found"])
        require(
            len(requested) == len(page["requested_ids"]) and not seen & requested,
            "Duplicate requested price IDs",
        )
        require(
            not found & missing
            and found | missing == requested
            and len(missing) == len(content["not_found"]),
            "Price outcomes are not a disjoint complete partition",
        )
        require(
            page["checksum"]
            == manifest["page_checksums"][number]
            == catalogue_checksum({"requested_ids": page["requested_ids"], "content": content}),
            "Price semantic checksum mismatch",
        )
        for identity, price in content["prices"].items():
            require(
                price["product_id"] == identity
                and price["store_code"] == context["store_code"]
                and price["source_state"] in (context["state"], "ALL")
                and price["currency_code"] == "AUD",
                "Price source provenance mismatch",
            )
        seen.update(requested)
    require(
        seen == membership and len(seen) == manifest["product_count"], "Price membership mismatch"
    )


def validate(index_path, schema_path=ROOT / "schema/catalogue-distribution-v1.json"):
    require(index_path.stat().st_size <= 2 * 1024 * 1024, "Index byte budget exceeded")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    schemas = json.loads(schema_path.read_text(encoding="utf-8"))
    validators = {
        key: Draft202012Validator(value, format_checker=FormatChecker())
        for key, value in schemas.items()
    }
    validators["index"].validate(index)
    require(
        index["release_tag"] == "data-v1-" + index["data_revision"]
        and revision(index) == index["data_revision"],
        "Index semantic revision mismatch",
    )
    all_assets = assets(index)
    require(
        len(all_assets) < 1000 and len({a["path"] for a in all_assets}) == len(all_assets),
        "Duplicate assets or GitHub release limit exceeded",
    )
    directory = index_path.parent
    combined = metadata(
        index["snapshot"],
        pages(directory, index["snapshot"]["archive"], validators["catalogue_page"]),
    )
    if index.get("delta"):
        current, delta = index["snapshot"]["manifest"], index["delta"]["manifest"]
        require(
            delta["mode"] == "delta"
            and delta.get("base_release_id")
            and delta["base_release_id"] != current["release_id"],
            "Invalid metadata delta base",
        )
        require(
            all(
                delta[key] == current[key]
                for key in ("release_id", "content_revision", "product_count", "recipe_count")
            ),
            "Delta target differs from complete snapshot",
        )
        metadata(
            index["delta"],
            pages(directory, index["delta"]["archive"], validators["catalogue_page"]),
        )
    contexts = set()
    for package in index["prices"]:
        manifest = package["manifest"]
        context = manifest["context"]
        key = (context["state"], context["store_code"])
        require(
            key not in contexts
            and context.get("store_id") is None
            and context["catalogue_release_id"] == index["snapshot"]["manifest"]["release_id"],
            "Duplicate or invalid chain price context",
        )
        require(
            context["state"] in {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}
            and context["store_code"] in {"aldi", "coles", "drakes", "iga", "woolies"},
            "Unsupported Australian price context",
        )
        contexts.add(key)
        expected = {
            p["product_id"]
            for p in combined["products"]
            if p["store_code"] == context["store_code"]
        }
        full = pages(directory, package["archive"], validators["price_page"])
        prices(package, full, expected)
        require(
            bool(package.get("base_release_id")) == bool(package.get("delta_archive")),
            "Price patch needs its exact base",
        )
        if package.get("delta_archive"):
            require(
                package["base_release_id"] != manifest["release_id"], "Price patch targets itself"
            )
            patch = pages(directory, package["delta_archive"], validators["price_page"])
            require(
                0 < len(patch) < len(full), "Price patch must be smaller than the complete package"
            )
            require(
                all(p["page_number"] < len(full) and p == full[p["page_number"]] for p in patch),
                "Price patch differs from its complete target",
            )
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "index", nargs="?", type=Path, default=ROOT / "distribution/candidate-release.json"
    )
    args = parser.parse_args()
    value = validate(args.index)
    print(
        json.dumps(
            {
                "validated": True,
                "release_tag": value["release_tag"],
                "archives": len(assets(value)),
                "price_contexts": len(value["prices"]),
            }
        )
    )
