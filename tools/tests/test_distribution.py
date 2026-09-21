import base64
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publish_distribution
from validate_distribution import assets, validate

FIXTURE = Path(__file__).parent / "fixtures/minimal"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        shutil.copytree(FIXTURE, self.directory, dirs_exist_ok=True)
        self.index = self.directory / "candidate-release.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_offline_fixture(self):
        index = validate(self.index)
        self.assertEqual(index["snapshot"]["manifest"]["product_count"], 1)
        self.assertEqual(len(index["prices"]), 1)

    def test_corrupt_archive_rejected(self):
        index = json.loads(self.index.read_text())
        path = self.directory / index["snapshot"]["archive"]["path"]
        raw = bytearray(path.read_bytes())
        raw[-10] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            validate(self.index)

    def test_unsupported_contract_and_wrong_revision_rejected(self):
        from jsonschema.exceptions import ValidationError

        index = json.loads(self.index.read_text())
        index["format_version"] = 2
        self.index.write_text(json.dumps(index))
        with self.assertRaises(ValidationError):
            validate(self.index)
        index["format_version"] = 1
        index["minimum_app_build"] += 1
        self.index.write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError, "revision"):
            validate(self.index)

    def test_archive_path_traversal_rejected_by_generated_schema(self):
        from jsonschema.exceptions import ValidationError

        index = json.loads(self.index.read_text())
        index["snapshot"]["archive"]["path"] = "../elsewhere.zip"
        self.index.write_text(json.dumps(index))
        with self.assertRaises(ValidationError):
            validate(self.index)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.index_path = FIXTURE / "candidate-release.json"
        self.index = validate(self.index_path)
        self.raw = self.index_path.read_bytes()
        self.release = {
            "id": 123,
            "tag_name": self.index["release_tag"],
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": a["path"],
                    "size": a["byte_length"],
                    "digest": "sha256:" + a["sha256"],
                }
                for a in assets(self.index)
            ]
            + [
                {
                    "name": "catalogue-release.json",
                    "size": len(self.raw),
                    "digest": "sha256:" + hashlib.sha256(self.raw).hexdigest(),
                }
            ],
        }
        self.tree = {"truncated": False, "tree": []}
        for path in [self.index_path] + [
            self.index_path.parent / a["path"] for a in assets(self.index)
        ]:
            raw = path.read_bytes()
            self.tree["tree"].append(
                {
                    "path": "distribution/" + path.name,
                    "type": "blob",
                    "size": len(raw),
                    "sha": hashlib.sha1(
                        b"blob " + str(len(raw)).encode() + b"\0" + raw
                    ).hexdigest(),
                }
            )

    def test_incomplete_release_never_advances_pointer(self):
        broken = copy.deepcopy(self.release)
        broken["assets"].pop()
        with (
            patch.object(publish_distribution, "api", return_value=broken) as api,
            patch.object(publish_distribution, "command") as command,
        ):
            command.return_value.stdout = "a" * 40
            with self.assertRaisesRegex(ValueError, "incomplete"):
                publish_distribution.publish(self.index_path)
            self.assertFalse(any("contents/" in call.args[0] for call in api.call_args_list))
            self.assertEqual(command.call_count, 1)

    def test_newer_candidate_does_not_get_older_pointer(self):
        replies = [
            self.release,
            self.release,
            self.tree,
            {"object": {"sha": "b" * 40}},
            {"content": base64.b64encode(b"newer").decode()},
        ]
        with (
            patch.object(publish_distribution, "api", side_effect=replies),
            patch.object(publish_distribution, "command") as command,
        ):
            command.return_value.stdout = "a" * 40
            result = publish_distribution.publish(self.index_path)
            self.assertEqual(result["reason"], "newer_candidate_on_main")
            self.assertFalse(result["pointer_advanced"])
            self.assertEqual(command.call_count, 1)

    def test_complete_release_updates_only_pointer_with_cas(self):
        head = "b" * 40
        replies = [
            self.release,
            self.release,
            self.tree,
            {"object": {"sha": head}},
            {"content": base64.b64encode(self.raw).decode()},
            {"sha": "prior-file-sha", "content": base64.b64encode(b"old").decode()},
            {"tree": {"sha": "base-tree"}},
            {"sha": "pointer-blob"},
            {"sha": "updated-tree"},
            {"sha": "pointer-commit"},
            {"object": {"sha": "pointer-commit"}},
        ]
        with (
            patch.object(publish_distribution, "api", side_effect=replies) as api,
            patch.object(publish_distribution, "command") as command,
        ):
            command.return_value.stdout = "a" * 40
            result = publish_distribution.publish(self.index_path)
        self.assertTrue(result["pointer_advanced"])
        calls = api.call_args_list
        self.assertEqual(
            calls[4].args[0], "contents/distribution/candidate-release.json?ref=" + head
        )
        self.assertEqual(
            calls[5].args[0], "contents/distribution/catalogue-release.json?ref=" + head
        )
        self.assertEqual(base64.b64decode(calls[7].kwargs["body"]["content"]), self.raw)
        self.assertEqual(calls[8].kwargs["body"]["base_tree"], "base-tree")
        self.assertEqual(
            calls[8].kwargs["body"]["tree"],
            [
                {
                    "path": "distribution/catalogue-release.json",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "pointer-blob",
                }
            ],
        )
        self.assertEqual(calls[9].kwargs["body"]["parents"], [head])
        self.assertEqual(calls[10].kwargs["body"], {"sha": "pointer-commit", "force": False})
        self.assertEqual(calls[10].kwargs["method"], "PATCH")

    def test_concurrent_new_candidate_rejects_pointer_even_when_pointer_file_is_unchanged(
        self,
    ):
        head = "b" * 40
        replies = [
            {"object": {"sha": head}},
            {"content": base64.b64encode(self.raw).decode()},
            {"sha": "unchanged-pointer", "content": base64.b64encode(b"old").decode()},
            {"tree": {"sha": "base-tree"}},
            {"sha": "pointer-blob"},
            {"sha": "updated-tree"},
            {"sha": "pointer-commit"},
            None,  # The branch advanced after validation: non-fast-forward.
            {"object": {"sha": "c" * 40}},
        ]
        with patch.object(publish_distribution, "api", side_effect=replies) as api:
            result = publish_distribution.advance_pointer(self.index["release_tag"], self.raw)
        self.assertFalse(result["pointer_advanced"])
        self.assertEqual(result["reason"], "main_changed_during_publication")
        self.assertEqual(api.call_args_list[6].kwargs["body"]["parents"], [head])
        writes = [call for call in api.call_args_list if call.args[0] == "git/refs/heads/main"]
        self.assertEqual(len(writes), 1)
        self.assertFalse(writes[0].kwargs["body"]["force"])

    def test_conflict_response_is_only_suppressed_for_explicit_ref_update(self):
        failure = SimpleNamespace(
            returncode=1, stderr="gh: Update is not a fast forward (HTTP 422)"
        )
        with patch.object(publish_distribution, "command", return_value=failure):
            self.assertIsNone(
                publish_distribution.api(
                    "git/refs/heads/main",
                    body={"sha": "a" * 40, "force": False},
                    method="PATCH",
                    conflict=True,
                )
            )
            with self.assertRaises(RuntimeError):
                publish_distribution.api("git/refs", body={"ref": "refs/tags/data-v1-test"})

    def test_tagged_raw_bytes_must_match_release_assets(self):
        broken = copy.deepcopy(self.tree)
        broken["tree"][0]["sha"] = "0" * 40
        with (
            patch.object(
                publish_distribution,
                "api",
                side_effect=[self.release, self.release, broken],
            ),
            patch.object(publish_distribution, "command") as command,
        ):
            command.return_value.stdout = "a" * 40
            with self.assertRaisesRegex(ValueError, "Tagged raw"):
                publish_distribution.publish(self.index_path)
            self.assertEqual(command.call_count, 1)

    def test_resumed_draft_tag_mismatch_rejected_before_publication(self):
        draft = copy.deepcopy(self.release)
        draft["draft"] = True
        broken = copy.deepcopy(self.tree)
        broken["tree"][0]["sha"] = "0" * 40
        with (
            patch.object(publish_distribution, "api", side_effect=[None, [draft], draft, broken]),
            patch.object(publish_distribution, "command") as command,
        ):
            command.return_value.stdout = "a" * 40
            with self.assertRaisesRegex(ValueError, "Tagged raw"):
                publish_distribution.publish(self.index_path)
            self.assertEqual(command.call_count, 1)

    def _complete_draft(self, orphan=False, resume=False):
        state = {
            "release": None,
            "uploaded": [],
            "pointer": False,
            "tagged": orphan or resume,
        }
        if resume:
            state["release"] = {
                "id": 123,
                "tag_name": self.index["release_tag"],
                "draft": True,
                "prerelease": False,
                "assets": [],
            }
        expected = {row["name"]: row for row in self.release["assets"]}

        def api(path, *, body=None, missing=False, method="POST", conflict=False):
            if path == "releases" and body:
                self.assertFalse(resume, "Existing drafts must be resumed")
                self.assertTrue(state["tagged"])
                self.assertTrue(body["draft"])
                state["release"] = {
                    "id": 123,
                    "tag_name": self.index["release_tag"],
                    "draft": True,
                    "prerelease": False,
                    "assets": [],
                }
                return copy.deepcopy(state["release"])
            if path.startswith("releases/tags/"):
                release = state["release"]
                return copy.deepcopy(release) if release and not release["draft"] else None
            if path.startswith("releases?per_page="):
                return [copy.deepcopy(state["release"])] if state["release"] else []
            if path == "releases/123":
                return copy.deepcopy(state["release"])
            if path.startswith("git/ref/tags/"):
                return {"object": {"type": "commit", "sha": "c" * 40}} if orphan else None
            if path == "git/refs":
                self.assertFalse(orphan, "Existing orphan tag must not be replaced")
                self.assertEqual(body["sha"], "a" * 40)
                state["tagged"] = True
                return {}
            if path.startswith("git/trees/"):
                self.assertTrue(state["tagged"])
                return self.tree
            if path == "git/ref/heads/main":
                return {"object": {"sha": "b" * 40}}
            if path == "git/commits/" + "b" * 40:
                return {"tree": {"sha": "base-tree"}}
            if path == "git/blobs":
                return {"sha": "pointer-blob"}
            if path == "git/trees":
                return {"sha": "pointer-tree"}
            if path == "git/commits":
                self.assertEqual(body["parents"], ["b" * 40])
                return {"sha": "pointer-commit"}
            if path == "git/refs/heads/main":
                self.assertFalse(state["release"]["draft"])
                self.assertEqual(set(state["uploaded"]), set(expected))
                self.assertEqual(body, {"sha": "pointer-commit", "force": False})
                self.assertEqual(method, "PATCH")
                state["pointer"] = True
                return {"object": {"sha": "pointer-commit"}}
            if "candidate-release.json" in path:
                self.assertFalse(state["release"]["draft"])
                return {"content": base64.b64encode(self.raw).decode()}
            if "catalogue-release.json" in path:
                return None
            self.fail("Unexpected API operation")

        def command(*args, **kwargs):
            if args[:3] == ("gh", "release", "view"):
                return SimpleNamespace(returncode=1, stdout="")
            if args[:3] == ("gh", "release", "upload"):
                path = Path(args[4])
                raw = path.read_bytes()
                row = {
                    "name": path.name,
                    "size": len(raw),
                    "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                }
                self.assertEqual(row, expected[path.name])
                state["release"]["assets"].append(row)
                state["uploaded"].append(path.name)
            elif args[:3] == ("gh", "release", "edit"):
                self.assertEqual(set(state["uploaded"]), set(expected))
                state["release"]["draft"] = False
            return SimpleNamespace(stdout="a" * 40)

        with (
            patch.object(publish_distribution, "api", side_effect=api),
            patch.object(publish_distribution, "command", side_effect=command),
        ):
            result = publish_distribution.publish(self.index_path)
        self.assertTrue(result["published"] and result["pointer_advanced"] and state["pointer"])

    def test_draft_is_completed_and_verified_before_public_pointer(self):
        self._complete_draft()

    def test_orphan_tag_from_earlier_commit_is_reused_with_exact_verified_bytes(self):
        self._complete_draft(orphan=True)

    def test_existing_draft_omitted_by_tag_endpoint_is_resumed_using_stable_id(self):
        self._complete_draft(resume=True)

    def test_draft_discovery_paginates_when_older_than_first_list_page(self):
        draft = {**self.release, "draft": True}
        with patch.object(
            publish_distribution,
            "api",
            side_effect=[
                None,
                [{"tag_name": "other"}] * 100,
                [draft],
            ],
        ) as api:
            self.assertEqual(publish_distribution.find_release(self.index["release_tag"]), draft)
        self.assertEqual(api.call_args_list[-1].args[0], "releases?per_page=100&page=2")

    def test_cli_discovery_resumes_draft_when_rest_indexes_lag(self):
        tag = self.index["release_tag"]
        draft = {**self.release, "draft": True}
        with (
            patch.object(publish_distribution, "api", side_effect=[None, [], draft]) as api,
            patch.object(
                publish_distribution,
                "command",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"databaseId": 123, "tagName": tag}),
                ),
            ),
        ):
            self.assertEqual(publish_distribution.find_release(tag), draft)
        self.assertEqual(api.call_args_list[-1].args[0], "releases/123")

    def test_orphan_tag_with_changed_bytes_is_not_reused_or_moved(self):
        for row in self.tree["tree"]:
            with self.subTest(path=row["path"]):
                broken = copy.deepcopy(self.tree)
                next(item for item in broken["tree"] if item["path"] == row["path"])["sha"] = (
                    "0" * 40
                )
                with (
                    patch.object(
                        publish_distribution,
                        "api",
                        side_effect=[
                            None,
                            [],
                            {"object": {"type": "commit", "sha": "c" * 40}},
                            broken,
                        ],
                    ) as api,
                    patch.object(publish_distribution, "command") as command,
                ):
                    command.return_value.stdout = "a" * 40
                    with self.assertRaisesRegex(ValueError, "Tagged raw"):
                        publish_distribution.publish(self.index_path)
                    self.assertFalse(any(call.kwargs.get("body") for call in api.call_args_list))
                    self.assertEqual(command.call_count, 2)


if __name__ == "__main__":
    unittest.main()
