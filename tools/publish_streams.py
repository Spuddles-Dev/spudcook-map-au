"""Publish independent streams without replacing verified predecessor assets."""

import hashlib
import json

from publish_distribution import api, find_release, publish
from validate_distribution import ROOT, require
from validate_streams import assets, candidates, locations, validate


def verify_retained_archives(index, directory):
    if "snapshot" in index:
        return
    releases, trees = {}, {}
    for package in index["packages"]:
        owner = package["release_tag"]
        if owner == index["release_tag"]:
            continue
        if owner not in releases:
            release = find_release(owner)
            require(
                release is not None
                and not release["draft"]
                and not release["prerelease"]
                and release.get("immutable") is True,
                "Retained archive owner is not an immutable publication",
            )
            releases[owner] = {asset["name"]: asset for asset in release["assets"]}
            tree = api("git/trees/" + owner + "?recursive=1")
            require(not tree.get("truncated"), "Retained tag tree was truncated")
            trees[owner] = {row["path"]: row for row in tree["tree"] if row["type"] == "blob"}
        package_assets = [package["archive"]]
        if package.get("delta_archive"):
            package_assets.append(package["delta_archive"])
        for asset in package_assets:
            published = releases[owner].get(asset["path"], {})
            require(
                published.get("size") == asset["byte_length"]
                and published.get("digest") == "sha256:" + asset["sha256"],
                "Retained release asset differs",
            )
            raw = (directory / asset["path"]).read_bytes()
            row = trees[owner].get("distribution/v2/prices/" + asset["path"], {})
            digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            require(
                row.get("sha") == digest and row.get("size") == len(raw),
                "Retained browser asset differs",
            )


def publish_stream(path):
    index = validate(path)
    candidate, pointer, name = locations(index)
    require(path.resolve() == (ROOT / candidate).resolve(), "Unexpected stream candidate path")
    verify_retained_archives(index, path.parent)
    return publish(
        path,
        validated=index,
        asset_specs=assets(index, owned=True),
        candidate_path=candidate,
        pointer_path=pointer,
        index_asset_name=name,
        latest=False,
    )


def publish_all(paths=None):
    results, failed = [], False
    for path in candidates() if paths is None else paths:
        try:
            results.append(publish_stream(path))
        except Exception as error:
            failed = True
            results.append({"candidate": path.name, "published": False, "error": str(error)})
    return {"streams": results, "failed": failed}


if __name__ == "__main__":
    result = publish_all()
    print(json.dumps(result))
    raise SystemExit(1 if result["failed"] else 0)
