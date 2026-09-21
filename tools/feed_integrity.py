"""Distribution-v2 semantic identities, mirrored by the backend and Flutter."""

from catalogue_integrity import catalogue_checksum


def membership_revision(product_ids):
    return catalogue_checksum(sorted(set(product_ids)))


def vendor_price_revision(manifest):
    return catalogue_checksum(
        {
            "contract_version": 2,
            "context": manifest["context"],
            "product_count": manifest["product_count"],
            "page_checksums": manifest["page_checksums"],
        }
    )


def _package(package, *, food=False):
    manifest = package["manifest"]
    return {
        "release_id": manifest["release_id"],
        "content_revision": manifest.get("content_revision") if food else None,
        "context": None if food else manifest["context"],
        "archive": package["archive"],
        "base_release_id": manifest.get("base_release_id")
        if food
        else package.get("base_release_id"),
        "delta_archive": None if food else package.get("delta_archive"),
    }


def food_feed_revision(index):
    return catalogue_checksum(
        {
            "format_version": 2,
            "minimum_app_build": index["minimum_app_build"],
            "snapshot": _package(index["snapshot"], food=True),
            "delta": _package(index["delta"], food=True) if index.get("delta") else None,
            "memberships": sorted(index["memberships"], key=lambda row: row["store_code"]),
        }
    )


def vendor_feed_revision(index):
    return catalogue_checksum(
        {
            "format_version": 2,
            "minimum_app_build": index["minimum_app_build"],
            "store_code": index["store_code"],
            "packages": [
                _package(row)
                for row in sorted(
                    index["packages"], key=lambda row: row["manifest"]["context"]["state"]
                )
            ],
        }
    )
