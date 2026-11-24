"""Regression coverage for provider tier labels used by real routing."""

import ast
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.patch_review import PatchRefusal, PatchReviewManager
from core.router import APIManager


class FakeResponse:
    status_code = 200
    headers = {}

    def json(self):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 3},
        }


class ProviderTierLabelTests(unittest.TestCase):
    """Ensure request tiers use labels accepted by the real matcher."""

    def test_required_tier_literals_match_validator_tier_labels(self):
        root = Path(__file__).resolve().parent
        validator_source = (root / "core" / "validator.py").read_text(
            encoding="utf-8-sig"
        )
        validator_tree = ast.parse(validator_source)
        validator_labels = {
            node.value.value
            for node in ast.walk(validator_tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "intel_tier"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        self.assertTrue(validator_labels, "Validator tier labels were not found")

        tracked = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "*.py"], cwd=root
        ).decode("utf-8").split("\0")
        self.assertLessEqual(len(tracked), 1000)
        findings = []
        for relative in tracked:
            if not relative or "venv" in Path(relative).parts:
                continue
            path = root / relative
            raw = path.read_bytes()
            self.assertLessEqual(len(raw), 5_000_000, relative)
            tree = ast.parse(raw.decode("utf-8-sig"), filename=relative)
            literals = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    literals.extend(
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "required_tier"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    )
                elif isinstance(node, ast.Dict):
                    literals.extend(
                        value
                        for key, value in zip(node.keys, node.values)
                        if isinstance(key, ast.Constant)
                        and key.value == "required_tier"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    )
                elif isinstance(node, ast.Assign):
                    literals.extend(
                        node.value
                        for target in node.targets
                        if isinstance(target, ast.Name)
                        and target.id == "required_tier"
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    )
                elif isinstance(node, ast.AnnAssign):
                    if (
                        isinstance(node.target, ast.Name)
                        and node.target.id == "required_tier"
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    ):
                        literals.append(node.value)
            for literal in literals:
                if not any(
                    APIManager._matches_tier(label, literal.value)
                    for label in validator_labels
                ):
                    findings.append(
                        f"{relative}:{literal.lineno}: {literal.value!r}"
                    )

        self.assertEqual(
            findings,
            [],
            "required_tier literals do not match validator tier labels:\n"
            + "\n".join(findings),
        )

    def test_patch_proposal_tier_selects_eligible_provider_with_real_matcher(self):
        class FakeRoutingDatabase:
            decryption_errors = {}

            def __init__(self, provider):
                self.provider = provider

            def get_active_providers(self):
                return [dict(self.provider)]

            def update_provider_fields(self, **kwargs):
                pass

            def record_usage(self, *args, **kwargs):
                pass

            def record_trace(self, *args, **kwargs):
                pass

        class RecordingAPIManager(APIManager):
            def __init__(self):
                super().__init__()
                self.request_kwargs = None

            def route_request(self, **kwargs):
                self.request_kwargs = dict(kwargs)
                return super().route_request(**kwargs)

        class FakePlanAgent:
            def is_reviewed_plan(self, plan_id):
                return True

        provider = {
            "id": 1,
            "name": "Tier One Syntax",
            "base_url": "https://syntax.example/v1",
            "api_key": "syntax-key",
            "model_name": "syntax-model",
            "assigned_agent": "Syntax",
            "intelligence_tier": "Tier 1: Genius",
            "speed_score_ms": 10,
            "supports_tools": True,
            "is_local": False,
            "failure_count": 0,
        }

        with tempfile.TemporaryDirectory(prefix="steward_tier_test_") as tmp:
            root = Path(tmp)
            target = root / "target.py"
            target.write_text("def target():\n    return 1\n", encoding="utf-8")
            incoming_root = root / "incoming"
            sorted_root = root / "sorted"
            incoming_root.mkdir()
            sorted_root.mkdir()
            api_manager = RecordingAPIManager()
            manager = PatchReviewManager(
                api_manager=api_manager,
                plan_agent=FakePlanAgent(),
                incoming_root=str(incoming_root),
                sorted_root=str(sorted_root),
                patches_dir=str(root / "patches"),
                backup_root=str(root / "backups"),
            )

            class FakeApplier:
                def admit_target(self, relative_path):
                    return SimpleNamespace(canonical_path=target)

            manager._applier = lambda workspace_root: FakeApplier()
            database = FakeRoutingDatabase(provider)
            with patch("core.router.get_db", return_value=database), patch(
                "core.router.requests.post", return_value=FakeResponse()
            ) as post:
                with self.assertRaises(PatchRefusal):
                    manager.propose(
                        str(root),
                        "target.py",
                        "Update target",
                        "plan-1",
                        conversation_epoch=1,
                    )

        self.assertIsNotNone(api_manager.request_kwargs)
        self.assertEqual(api_manager.request_kwargs["agent_name"], "Syntax")
        self.assertTrue(
            APIManager._matches_tier(
                provider["intelligence_tier"],
                api_manager.request_kwargs["required_tier"],
            )
        )
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
