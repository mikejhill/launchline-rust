"""Reconcile a GitHub release with an already-published, attested Cargo archive."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


class GitHubRelease:
    """Publish a complete draft only after immutable package and source checks."""

    REPO = "mikejhill/launchline-rust"

    @staticmethod
    def gh(*args: str) -> str:
        """Run only explicit GitHub CLI arguments, with bounded execution."""
        return subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        ).stdout

    @classmethod
    def api(cls, path: str) -> object:
        """Inspect the fixed repository without accepting a supplied remote URL."""
        return json.loads(cls.gh("api", f"repos/{cls.REPO}/{path}"))

    @staticmethod
    def digest(path: Path) -> str:
        """Hash the exact local bytes rather than trusting filenames or asset sizes."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def prepare(cls, directory: Path) -> tuple[str, str, str, list[Path]]:
        """Require registry checksum, exact tag/source and verified build provenance."""
        record = json.loads((directory / "publish.json").read_text(encoding="utf-8"))
        version = os.environ["VERSION"]
        source = record["source_sha"]
        if (
            re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
            or re.fullmatch(r"[0-9a-f]{40}", source) is None
            or os.environ.get("SOURCE_SHA", source) != source
            or record["package"]["name"] != "launchline"
            or record["package"]["vers"] != version
            or record["package"]["repository"] != f"https://github.com/{cls.REPO}"
            or record["crate_file"] != f"launchline-{version}.crate"
        ):
            raise ValueError("Unexpected release identity")
        archive = directory / record["crate_file"]
        if not 0 < archive.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("Unexpected archive size")
        digest = cls.digest(archive)
        if digest != record["sha256"]:
            raise ValueError("Artifact checksum mismatch")
        request = urllib.request.Request(
            f"https://crates.io/api/v1/crates/launchline/{version}",
            headers={"User-Agent": f"launchline-release/1 (github.com/{cls.REPO})"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            registry = json.load(response)["version"]
        if registry["checksum"] != digest or registry["yanked"]:
            raise ValueError("Published crate differs or is yanked")
        tag = f"v{version}"
        if cls.api(f"commits/{tag}")["sha"] != source:
            raise ValueError("Existing source tag differs; never create or move it")
        if cls.api(f"compare/{source}...main")["merge_base_commit"]["sha"] != source:
            raise ValueError("Release source is not on main")
        run = cls.api(f"actions/runs/{os.environ['SOURCE_RUN_ID']}")
        if (
            run["head_sha"] != source
            or run["head_branch"] != "main"
            or run["event"] != "push"
            or run["path"] != ".github/workflows/release.yml"
            or run["status"] not in ("in_progress", "completed")
            or (run["status"] == "completed" and run["conclusion"] != "success")
        ):
            raise ValueError("Artifact run is not the successful source release")
        with tarfile.open(archive) as packaged:
            prefix = f"launchline-{version}/"
            vcs = json.load(packaged.extractfile(prefix + ".cargo_vcs_info.json"))
            if vcs["git"]["sha1"] != source:
                raise ValueError("Archive source differs")
            member = packaged.getmember(prefix + "release-changelog.md")
            if member.size > 256 * 1024:
                raise ValueError("Release notes exceed boundary")
            notes = packaged.extractfile(member).read().decode("utf-8")
        # Fetch and verify the bundle itself before attaching it as an asset.
        cls.gh("attestation", "download", str(archive), "--repo", cls.REPO)
        downloaded = Path(f"sha256-{digest}.jsonl")
        cls.gh(
            "attestation",
            "verify",
            str(archive),
            "--repo",
            cls.REPO,
            "--bundle",
            str(downloaded),
            "--source-digest",
            source,
            "--source-ref",
            "refs/heads/main",
            "--deny-self-hosted-runners",
            "--signer-workflow",
            f"{cls.REPO}/.github/workflows/release.yml",
        )
        provenance = directory / f"launchline-{version}.crate.intoto.jsonl"
        provenance.write_bytes(downloaded.read_bytes())
        assets = [archive, directory / "publish.json", provenance]
        checksums = directory / "SHA256SUMS"
        checksums.write_text(
            "".join(f"{cls.digest(path)}  {path.name}\n" for path in assets),
            encoding="utf-8",
        )
        assets.append(checksums)
        notes += (
            f"\n### Installation and verification\n\n"
            f"`cargo install launchline --version {version} --locked`\n\n"
            f"[crates.io package](https://crates.io/crates/launchline/{version}) · "
            f"[Source](https://github.com/{cls.REPO}/tree/{tag}) · "
            f"[Validated build](https://github.com/{cls.REPO}/actions/runs/{run['id']})\n\n"
            "Assets contain the published Cargo source archive, registry metadata, "
            "SHA-256 checksums and signed build provenance.\n\n"
            f"`gh attestation verify launchline-{version}.crate --repo {cls.REPO} "
            f"--source-digest {source} --deny-self-hosted-runners`\n"
        )
        return tag, source, notes, assets

    @classmethod
    def publish(cls, directory: Path) -> None:
        """Resume drafts/missing assets; reject conflicting bytes without clobbering."""
        tag, source, notes, assets = cls.prepare(directory)
        releases = cls.releases()
        release = next((item for item in releases if item["tag_name"] == tag), None)
        if release is None:
            body = directory / "github-release-notes.md"
            body.write_text(notes, encoding="utf-8")
            cls.gh(
                "release",
                "create",
                tag,
                "--repo",
                cls.REPO,
                "--verify-tag",
                "--target",
                source,
                "--draft",
                "--title",
                tag,
                "--notes-file",
                str(body),
            )
            # A network failure never retries creation blindly; the next run lists again.
            identity = json.loads(
                cls.gh(
                    "release", "view", tag, "--repo", cls.REPO, "--json", "databaseId"
                )
            )
            release = cls.api(f"releases/{identity['databaseId']}")
        existing = {item["name"] for item in release["assets"]}
        with tempfile.TemporaryDirectory(prefix="launchline-release-assets-") as tmp:
            for asset in assets:
                if asset.name not in existing:
                    cls.gh("release", "upload", tag, str(asset), "--repo", cls.REPO)
                cls.gh(
                    "release",
                    "download",
                    tag,
                    "--repo",
                    cls.REPO,
                    "--pattern",
                    asset.name,
                    "--dir",
                    tmp,
                )
                if cls.digest(Path(tmp) / asset.name) != cls.digest(asset):
                    raise ValueError(f"Release asset differs: {asset.name}")
        if cls.api(f"commits/{tag}")["sha"] != source:
            raise ValueError("Source tag changed during reconciliation")
        if release["draft"]:
            cls.gh("release", "edit", tag, "--repo", cls.REPO, "--draft=false")
        final = cls.api(f"releases/tags/{tag}")
        if final["draft"] or not {path.name for path in assets}.issubset(
            {item["name"] for item in final["assets"]}
        ):
            raise RuntimeError(
                "GitHub release readback is incomplete; reconcile before retry"
            )
        print(f"Verified complete GitHub release {tag}.")

    @classmethod
    def releases(cls) -> list[dict]:
        """Include older drafts and releases when reconciling an existing version."""
        pages = json.loads(
            cls.gh(
                "api",
                f"repos/{cls.REPO}/releases?per_page=100",
                "--paginate",
                "--slurp",
            )
        )
        return [release for page in pages for release in page]


if __name__ == "__main__":
    if os.environ.get("GITHUB_RELEASE_VERIFY_ONLY") == "1":
        GitHubRelease.prepare(Path("release"))
        print("Verified existing registry release, source tag and provenance.")
    else:
        GitHubRelease.publish(Path("release"))
