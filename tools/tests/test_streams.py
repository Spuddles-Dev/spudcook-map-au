import base64
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publish_distribution
import publish_streams
from catalogue_integrity import catalogue_checksum
from feed_integrity import (
    food_feed_revision,
    membership_revision,
    vendor_feed_revision,
    vendor_price_revision,
)
from validate_streams import STATES, VENDORS, assets, validate

FIXTURE = Path(__file__).parent / "fixtures/minimal"


def archive(directory, name, page):
    raw = json.dumps(page, separators=(",", ":"), ensure_ascii=False).encode()
    path = directory / name
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("page-00000.json", raw)
    return {
        "path": name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "byte_length": path.stat().st_size,
        "uncompressed_bytes": len(raw),
    }


def fixture(directory):
    old = json.loads((FIXTURE / "candidate-release.json").read_text())
    food = {
        "format_version": 2,
        "minimum_app_build": 230,
        "source_revision": 0,
        "published_at": old["published_at"],
        "snapshot": old["snapshot"],
        "delta": None,
        "memberships": [
            {
                "store_code": vendor,
                "product_count": int(vendor == "coles"),
                "membership_revision": membership_revision(
                    ["coles_0000"] if vendor == "coles" else []
                ),
            }
            for vendor in VENDORS
        ],
    }
    food["data_revision"] = food_feed_revision(food)
    food["release_tag"] = "food-v2-" + food["data_revision"]
    shutil.copyfile(
        FIXTURE / old["snapshot"]["archive"]["path"], directory / old["snapshot"]["archive"]["path"]
    )
    (directory / "candidate-food.json").write_text(json.dumps(food))
    prices = directory / "prices"
    prices.mkdir()
    with zipfile.ZipFile(FIXTURE / old["prices"][0]["archive"]["path"]) as source:
        original = json.loads(source.read("page-00000.json"))
    packages = []
    for state in sorted(STATES):
        page = copy.deepcopy(original)
        page["content"]["state"] = state
        page["content"]["prices"]["coles_0000"]["source_state"] = state
        page["checksum"] = catalogue_checksum(
            {"requested_ids": page["requested_ids"], "content": page["content"]}
        )
        manifest = {
            "contract_version": 2,
            "context": {
                "state": state,
                "store_code": "coles",
                "membership_revision": membership_revision(["coles_0000"]),
            },
            "source_revision": 0,
            "next_evaluation_at": None,
            "generated_at": old["published_at"],
            "product_count": 1,
            "page_count": 1,
            "page_checksums": [page["checksum"]],
        }
        manifest["release_id"] = vendor_price_revision(manifest)
        page["release_id"] = manifest["release_id"]
        packages.append(
            {
                "manifest": manifest,
                "archive": archive(
                    prices, f"prices-{state.lower()}-{manifest['release_id']}.zip", page
                ),
                "release_tag": "prices-v2-coles-" + "0" * 64,
                "base_release_id": None,
                "delta_archive": None,
            }
        )
    vendor = {
        "format_version": 2,
        "minimum_app_build": 230,
        "store_code": "coles",
        "published_at": old["published_at"],
        "packages": packages,
    }
    vendor["data_revision"] = vendor_feed_revision(vendor)
    vendor["release_tag"] = "prices-v2-coles-" + vendor["data_revision"]
    for package in packages:
        package["release_tag"] = vendor["release_tag"]
    (prices / "candidate-coles.json").write_text(json.dumps(vendor))
    return food, vendor


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.food, self.vendor = fixture(self.directory)
        self.food_path = self.directory / "candidate-food.json"
        self.vendor_path = self.directory / "prices/candidate-coles.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_food_and_eight_state_vendor(self):
        self.assertEqual(validate(self.food_path), self.food)
        self.assertEqual(validate(self.vendor_path), self.vendor)

    def test_transport_times_counters_and_archive_owner_do_not_change_semantic_identity(self):
        changed = copy.deepcopy(self.vendor)
        changed["published_at"] = "2026-09-22T00:00:00Z"
        changed["packages"][0]["manifest"]["source_revision"] = 999
        changed["packages"][0]["release_tag"] = "prices-v2-coles-" + "f" * 64
        self.assertEqual(vendor_feed_revision(changed), self.vendor["data_revision"])
        changed["packages"][0]["archive"]["sha256"] = "e" * 64
        self.assertNotEqual(vendor_feed_revision(changed), self.vendor["data_revision"])

    def test_food_membership_mismatch_is_not_hidden_by_rehashed_index(self):
        self.food["memberships"][1]["membership_revision"] = "0" * 64
        self.food["data_revision"] = food_feed_revision(self.food)
        self.food["release_tag"] = "food-v2-" + self.food["data_revision"]
        self.food_path.write_text(json.dumps(self.food))
        with self.assertRaisesRegex(ValueError, "membership"):
            validate(self.food_path)

    def test_corrupt_price_archive_rejected(self):
        path = self.vendor_path.parent / self.vendor["packages"][0]["archive"]["path"]
        raw = bytearray(path.read_bytes())
        raw[-3] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            validate(self.vendor_path)

    def test_wrong_vendor_owner_rejected(self):
        self.vendor["packages"][0]["release_tag"] = "prices-v2-aldi-" + "f" * 64
        self.vendor_path.write_text(json.dumps(self.vendor))
        with self.assertRaisesRegex(ValueError, "owner"):
            validate(self.vendor_path)

    def test_only_new_archives_are_uploaded(self):
        self.vendor["packages"][0]["release_tag"] = "prices-v2-coles-" + "f" * 64
        self.assertEqual(len(assets(self.vendor, owned=True)), 7)

    def test_failure_does_not_block_next_vendor(self):
        with patch.object(
            publish_streams,
            "publish_stream",
            side_effect=[ValueError("bad feed"), {"published": True}],
        ):
            result = publish_streams.publish_all([self.food_path, self.vendor_path])
        self.assertTrue(result["failed"])
        self.assertTrue(result["streams"][1]["published"])

    def test_retained_draft_never_becomes_a_dependency(self):
        self.vendor["packages"][0]["release_tag"] = "prices-v2-coles-" + "f" * 64
        with patch.object(
            publish_streams,
            "find_release",
            return_value={"draft": True, "prerelease": False, "immutable": False},
        ):
            with self.assertRaisesRegex(ValueError, "immutable"):
                publish_streams.verify_retained_archives(self.vendor, self.vendor_path.parent)

    def test_feed_pointer_uses_its_own_candidate_and_compare_and_swap(self):
        raw = self.food_path.read_bytes()
        replies = [
            {"object": {"sha": "a" * 40}},
            {"content": base64.b64encode(raw).decode()},
            None,
            {"tree": {"sha": "tree"}},
            {"sha": "blob"},
            {"sha": "tree2"},
            {"sha": "commit"},
            {"ok": True},
        ]
        with patch.object(publish_distribution, "api", side_effect=replies) as api:
            result = publish_distribution.advance_pointer(
                self.food["release_tag"],
                raw,
                candidate_path="distribution/v2/candidate-food.json",
                pointer_path="distribution/v2/food.json",
            )
        self.assertTrue(result["pointer_advanced"])
        self.assertEqual(
            api.call_args_list[1].args[0],
            "contents/distribution/v2/candidate-food.json?ref=" + "a" * 40,
        )
        self.assertEqual(
            api.call_args_list[5].kwargs["body"]["tree"][0]["path"], "distribution/v2/food.json"
        )
        self.assertFalse(api.call_args_list[-1].kwargs["body"]["force"])

    def test_pointer_retry_rechecks_after_concurrent_main_change(self):
        conflict = {"reason": "main_changed_during_publication"}
        with patch.object(
            publish_distribution,
            "advance_pointer",
            side_effect=[
                conflict,
                {"pointer_advanced": True},
            ],
        ) as advance:
            result = publish_distribution.advance_pointer_with_retry("tag", b"index")
        self.assertTrue(result["pointer_advanced"])
        self.assertEqual(advance.call_count, 2)

    def test_pointer_retry_stops_for_newer_candidate_and_bounds_contention(self):
        conflict = {"reason": "main_changed_during_publication"}
        with patch.object(
            publish_distribution,
            "advance_pointer",
            side_effect=[
                conflict,
                {"reason": "newer_candidate_on_main"},
            ],
        ) as advance:
            result = publish_distribution.advance_pointer_with_retry("tag", b"index")
        self.assertEqual(result["reason"], "newer_candidate_on_main")
        self.assertEqual(advance.call_count, 2)
        with patch.object(
            publish_distribution, "advance_pointer", return_value=conflict
        ) as advance:
            with self.assertRaisesRegex(RuntimeError, "rerun"):
                publish_distribution.advance_pointer_with_retry("tag", b"index")
        self.assertEqual(advance.call_count, 3)
