import copy
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalogue_integrity import catalogue_checksum
from feed_integrity import food_feed_revision
from test_streams import FIXTURE, archive, fixture
from validate_distribution import metadata
from validate_distribution import validate as validate_legacy
from validate_streams import validate


class MetadataDeltaTests(unittest.TestCase):
    def _candidate(self, directory, case, legacy=False):
        if legacy:
            shutil.copytree(FIXTURE, directory, dirs_exist_ok=True)
            path = directory / "candidate-release.json"
            index = json.loads(path.read_text())
        else:
            index, _ = fixture(directory)
            path = directory / "candidate-food.json"
        with zipfile.ZipFile(directory / index["snapshot"]["archive"]["path"]) as source:
            values = [json.loads(source.read(name)) for name in sorted(source.namelist())]
        content = copy.deepcopy(metadata(index["snapshot"], values))
        content["removed_product_ids"] = ["coles_retired"]
        content["removed_recipe_ids"] = [99]
        if case == "product":
            content["products"][0]["name"] = "Not in the complete target"
        elif case == "recipe":
            content["recipes"] = [{"recipe_id": 1, "name": "Not in target"}]
        elif case == "duplicate_product":
            content["products"] *= 2
        elif case == "remove_present":
            content["removed_product_ids"] = [content["products"][0]["product_id"]]
        elif case == "duplicate_removal":
            content["removed_product_ids"] *= 2
        elif case in ("private_reference", "private_product", "unknown_reference"):
            panel = {
                "basis": "per_100_g",
                "protein_g": 1,
                "source_label": "Private",
                "source_kind": "user",
            }
            if case == "private_reference":
                content["nutrition_references"] = [
                    {"reference_id": catalogue_checksum(panel), "nutrition": panel}
                ]
            else:
                content["products"][0]["food_facts"] = {
                    "product_id": content["products"][0]["product_id"],
                    "revision": "bad",
                    "nutrition": panel if case == "private_product" else None,
                    "nutrition_reference_id": "missing" if case == "unknown_reference" else None,
                }
        elif case == "missing_tree":
            content["ingredient_taxonomy"] = None
        elif case == "changed_tree":
            content["app_categories"]["total"] = 99
        manifest = copy.deepcopy(index["snapshot"]["manifest"])
        manifest.update(
            mode="delta",
            base_release_id="previous",
            page_count=1,
            page_checksums=[catalogue_checksum(content)],
        )
        page = {
            "release_id": manifest["release_id"],
            "base_release_id": "previous",
            "mode": "delta",
            "page_number": 0,
            "checksum": manifest["page_checksums"][0],
            "content": content,
        }
        index["delta"] = {"manifest": manifest, "archive": archive(directory, "delta.zip", page)}
        if not legacy:
            index["data_revision"] = food_feed_revision(index)
            index["release_tag"] = "food-v2-" + index["data_revision"]
        path.write_text(json.dumps(index))
        return path

    def test_valid_delta_in_both_distribution_versions(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as temporary:
                path = self._candidate(Path(temporary), "valid", legacy)
                (validate_legacy if legacy else validate)(path)

    def test_rehashed_adversarial_deltas_are_rejected(self):
        for legacy in (False, True):
            for case in (
                "product",
                "recipe",
                "duplicate_product",
                "remove_present",
                "duplicate_removal",
                "private_reference",
                "private_product",
                "unknown_reference",
                "missing_tree",
                "changed_tree",
            ):
                with (
                    self.subTest(legacy=legacy, case=case),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    path = self._candidate(Path(temporary), case, legacy)
                    with self.assertRaisesRegex(ValueError, "[Dd]elta"):
                        (validate_legacy if legacy else validate)(path)
