"""Build a verified Cargo archive and its documented registry API metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


class CrateBuild:
    """Produce publication inputs with no registry credential or OIDC permission."""

    @staticmethod
    def main() -> None:
        """Package and compile the archive, preserving literal dependency metadata."""
        root = Path(__file__).resolve().parents[1]
        data = json.loads(
            subprocess.check_output(
                ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
                cwd=root,
            )
        )
        package = next(
            item
            for item in data["packages"]
            if item["id"] in data["workspace_members"] and item["name"] == "launchline"
        )
        version = package["version"]
        source = (
            os.environ.get("SOURCE_SHA")
            or subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
        )
        if (
            re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
            or re.fullmatch(r"[0-9a-f]{40}", source) is None
        ):
            raise ValueError("Expected numeric version and exact source commit")
        dependencies = []
        for dep in package["dependencies"]:
            if dep["registry"] is not None:
                raise ValueError(
                    "Only crates.io dependencies can enter this publication"
                )
            dependencies.append(
                {
                    "name": dep["name"],
                    "version_req": dep["req"],
                    "features": dep["features"],
                    "optional": dep["optional"],
                    "default_features": dep["uses_default_features"],
                    "target": dep["target"],
                    "kind": dep["kind"] or "normal",
                    "registry": None,
                    "explicit_name_in_toml": dep["rename"],
                }
            )
        metadata = {
            "name": "launchline",
            "vers": version,
            "deps": dependencies,
            "features": package["features"],
            "authors": package["authors"],
            "description": package["description"],
            "documentation": package["documentation"],
            "homepage": package["homepage"],
            "readme": (root / "README.md").read_text(encoding="utf-8"),
            "readme_file": "README.md",
            "keywords": package["keywords"],
            "categories": package["categories"],
            "license": package["license"],
            "license_file": None,
            "repository": package["repository"],
            "badges": {},
            "links": package["links"],
            "rust_version": package["rust_version"],
        }
        subprocess.run(
            ["cargo", "package", "--locked", "--allow-dirty"], cwd=root, check=True
        )
        output = root / "crate-release"
        output.mkdir(exist_ok=True)
        filename = f"launchline-{version}.crate"
        path = output / filename
        shutil.copyfile(root / "target/package" / filename, path)
        record = {
            "source_sha": source,
            "crate_file": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "package": metadata,
        }
        (output / "publish.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    CrateBuild.main()
