from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVALUATION_ROOT.parents[2]
MODULE_PATH = EVALUATION_ROOT / "scripts" / "validate_skill_packages.py"
SPEC = importlib.util.spec_from_file_location("validate_skill_packages", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class SkillPackageValidatorTest(unittest.TestCase):
    def _package(self, root: Path, name: str = "sample-skill") -> Path:
        package = root / name
        (package / "agents").mkdir(parents=True)
        (package / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A bounded test skill.\n---\n\n# Test\n\nInstructions.\n",
            encoding="utf-8",
        )
        (package / "agents" / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: \"Sample Skill\"\n"
            "  short_description: \"Validate a sample skill\"\n"
            f"  default_prompt: \"Use ${name} for this bounded task.\"\n",
            encoding="utf-8",
        )
        return package

    def test_repository_candidates_are_loadable_packages(self) -> None:
        for name in ("context-composer", "explore-approaches", "review-skill-candidate"):
            with self.subTest(name=name):
                self.assertEqual(VALIDATOR.validate_package(REPO_ROOT / "skills" / name)["name"], name)

    def test_rejects_name_directory_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._package(Path(temporary))
            skill = package / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8").replace("name: sample-skill", "name: other-skill"), encoding="utf-8")
            with self.assertRaisesRegex(VALIDATOR.PackageError, "match its directory"):
                VALIDATOR.validate_package(package)

    def test_rejects_default_prompt_without_explicit_skill_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._package(Path(temporary))
            metadata = package / "agents" / "openai.yaml"
            metadata.write_text(metadata.read_text(encoding="utf-8").replace("$sample-skill", "the skill"), encoding="utf-8")
            with self.assertRaisesRegex(VALIDATOR.PackageError, "explicitly invoke"):
                VALIDATOR.validate_package(package)

    def test_rejects_malformed_yaml_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._package(Path(temporary))
            skill = package / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace("description: A bounded test skill.", "description: [broken"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(VALIDATOR.PackageError, "safe plain YAML scalar"):
                VALIDATOR.validate_package(package)


if __name__ == "__main__":
    unittest.main()
