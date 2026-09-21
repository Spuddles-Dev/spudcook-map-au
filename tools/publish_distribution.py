"""Publish verified immutable assets, then advance only the public current pointer."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from validate_distribution import ROOT, assets, require, validate

REPOSITORY = "Spuddles-Dev/spudcook-map-au"


def command(*args, check=True):
    result = subprocess.run(args, check=check, text=True, capture_output=True)
    return result


def api(path, *, body=None, missing=False, method="POST", conflict=False):
    args = ["gh", "api", "repos/" + REPOSITORY + "/" + path]
    if body is None:
        result = command(*args, check=False)
    else:
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "request.json"
            file.write_text(json.dumps(body), encoding="utf-8")
            result = command(*args, "--method", method, "--input", str(file), check=False)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        if conflict and any(f"HTTP {code}" in result.stderr for code in (409, 422)):
            return None
        raise RuntimeError("GitHub API operation failed; the public pointer was not advanced")
    return json.loads(result.stdout)


def verify_release(release, expected):
    actual = {item["name"]: item for item in release["assets"]}
    require(set(actual) == set(expected), "Release assets are incomplete or unexpected")
    for name, (size, digest) in expected.items():
        require(
            actual[name]["size"] == size and actual[name].get("digest") == "sha256:" + digest,
            "GitHub asset digest/size mismatch",
        )


def find_release(tag):
    release = api("releases/tags/" + tag, missing=True)
    if release is not None:
        return release
    # GitHub's release-by-tag endpoint omits drafts. Authenticated list/read-by-ID
    # endpoints include them, so a failed upload can resume the existing draft.
    for page in range(1, 101):
        rows = api(f"releases?per_page=100&page={page}")
        matching = [row for row in rows if row["tag_name"] == tag]
        require(len(matching) <= 1, "Multiple drafts have the same data tag")
        if matching:
            return matching[0]
        if len(rows) < 100:
            break
    else:
        raise ValueError("Release discovery exceeded its bounded page budget")
    # The CLI's authenticated release lookup can discover drafts that are not
    # yet visible in the REST tag/list indexes used by an Actions token.
    lookup = command(
        "gh",
        "release",
        "view",
        tag,
        "--repo",
        REPOSITORY,
        "--json",
        "databaseId,tagName",
        check=False,
    )
    if lookup.returncode == 0:
        identity = json.loads(lookup.stdout)
        require(
            identity.get("tagName") == tag and isinstance(identity.get("databaseId"), int),
            "Draft discovery returned another release",
        )
        return api("releases/" + str(identity["databaseId"]))
    return None


def verify_tagged_files(
    tag, index_path, index, *, asset_specs=None, relative_directory="distribution"
):
    tree = api("git/trees/" + tag + "?recursive=1")
    require(not tree.get("truncated"), "Cannot verify a truncated Git tree")
    entries = {item["path"]: item for item in tree["tree"] if item["type"] == "blob"}
    paths = [index_path] + [
        index_path.parent / asset["path"]
        for asset in (assets(index) if asset_specs is None else asset_specs)
    ]
    for path in paths:
        raw = path.read_bytes()
        git_digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        relative = relative_directory + "/" + path.name
        row = entries.get(relative, {})
        require(
            row.get("sha") == git_digest and row.get("size") == len(raw),
            "Tagged raw bytes differ from the validated release assets",
        )


def advance_pointer(
    tag,
    raw,
    *,
    candidate_path="distribution/candidate-release.json",
    pointer_path="distribution/catalogue-release.json",
):
    result = {"release_tag": tag, "published": True, "pointer_advanced": False}
    head = api("git/ref/heads/main")["object"]["sha"]
    candidate = api("contents/" + candidate_path + "?ref=" + head)
    if base64.b64decode(candidate["content"]) != raw:
        return {**result, "reason": "newer_candidate_on_main"}
    current = api("contents/" + pointer_path + "?ref=" + head, missing=True)
    if current and base64.b64decode(current["content"]) == raw:
        return {**result, "reason": "already_current"}
    base = api("git/commits/" + head)["tree"]["sha"]
    blob = api(
        "git/blobs",
        body={"encoding": "base64", "content": base64.b64encode(raw).decode()},
    )
    tree = api(
        "git/trees",
        body={
            "base_tree": base,
            "tree": [
                {
                    "path": pointer_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            ],
        },
    )
    commit = api(
        "git/commits",
        body={
            "message": f"Publish current data pointer {tag}",
            "tree": tree["sha"],
            "parents": [head],
        },
    )
    # The new commit descends only from the verified head. A concurrent main
    # advance makes this a non-fast-forward update, even if the pointer file
    # itself is unchanged. Never force or merge an unverified newer candidate.
    updated = api(
        "git/refs/heads/main",
        body={"sha": commit["sha"], "force": False},
        method="PATCH",
        conflict=True,
    )
    if updated is None:
        require(
            api("git/ref/heads/main")["object"]["sha"] != head,
            "Pointer update rejected without a concurrent branch change",
        )
        return {**result, "reason": "main_changed_during_publication"}
    return {**result, "pointer_advanced": True}


def advance_pointer_with_retry(tag, raw, **paths):
    for _ in range(3):
        result = advance_pointer(tag, raw, **paths)
        if result.get("reason") != "main_changed_during_publication":
            return result
    # No force update: surface a retryable failure so an interrupted pointer
    # advance is visible instead of reporting a completely published stream.
    raise RuntimeError("Main changed during each pointer attempt; rerun publication")


def publish(
    index_path,
    *,
    validated=None,
    asset_specs=None,
    candidate_path="distribution/candidate-release.json",
    pointer_path="distribution/catalogue-release.json",
    index_asset_name="catalogue-release.json",
    latest=True,
):
    require(
        os.environ.get("GITHUB_REPOSITORY", REPOSITORY) == REPOSITORY,
        "Publication is restricted to the public data repository",
    )
    index = validate(index_path) if validated is None else validated
    raw = index_path.read_bytes()
    tag = index["release_tag"]
    sha = command("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
    require(len(sha) == 40, "Expected an exact checked commit")
    selected_assets = assets(index) if asset_specs is None else asset_specs
    expected = {a["path"]: (a["byte_length"], a["sha256"]) for a in selected_assets}
    expected[index_asset_name] = (len(raw), hashlib.sha256(raw).hexdigest())

    def verify_tag():
        if validated is None:
            verify_tagged_files(tag, index_path, index)
        else:
            verify_tagged_files(
                tag,
                index_path,
                index,
                asset_specs=selected_assets,
                relative_directory=str(Path(candidate_path).parent).replace("\\", "/"),
            )

    release = find_release(tag)
    if release is None:
        existing_tag = api("git/ref/tags/" + tag, missing=True)
        if existing_tag is None:
            api("git/refs", body={"ref": "refs/tags/" + tag, "sha": sha})
        # An interrupted run may have tagged an earlier source commit with
        # identical data. Verify its bytes, never move or replace that tag.
        verify_tag()
        release = api(
            "releases",
            body={
                "tag_name": tag,
                "target_commitish": sha,
                "name": tag,
                "draft": True,
                "prerelease": False,
                "make_latest": "false",
                "body": "Public Australian food catalogue and explicit state/chain price snapshots.\n\nValidated ZIP and typed-page SHA256 checksums. No personal data or automatic food-review approvals.\n",
            },
        )
        require(
            release.get("tag_name") == tag
            and release.get("draft") is True
            and isinstance(release.get("id"), int),
            "Draft creation returned an unexpected identity; pointer was not advanced",
        )
    release_path = "releases/" + str(release["id"])
    if release["draft"]:
        existing = {a["name"]: a for a in release["assets"]}
        require(set(existing) <= set(expected), "Unexpected draft assets")
        with tempfile.TemporaryDirectory() as directory:
            index_asset = Path(directory) / index_asset_name
            index_asset.write_bytes(raw)
            for name, (size, digest) in expected.items():
                if name in existing:
                    require(
                        existing[name]["size"] == size
                        and existing[name].get("digest") == "sha256:" + digest,
                        "Existing draft asset differs; refusing overwrite",
                    )
                    continue
                path = index_asset if name == index_asset_name else index_path.parent / name
                command("gh", "release", "upload", tag, str(path), "--repo", REPOSITORY)
        verify_release(api(release_path), expected)
        verify_tag()
        command(
            "gh",
            "release",
            "edit",
            tag,
            "--repo",
            REPOSITORY,
            "--draft=false",
            "--latest" if latest else "--latest=false",
        )
    release = api(release_path)
    require(
        not release["draft"] and not release["prerelease"],
        "Current pointer requires a published data release",
    )
    if validated is not None:
        require(
            release.get("immutable") is True, "Stream publication requires release immutability"
        )
    verify_release(release, expected)
    verify_tag()
    if validated is None:
        return advance_pointer_with_retry(tag, raw)
    return advance_pointer_with_retry(
        tag, raw, candidate_path=candidate_path, pointer_path=pointer_path
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=ROOT / "distribution/candidate-release.json")
    args = parser.parse_args()
    print(json.dumps(publish(args.index)))
