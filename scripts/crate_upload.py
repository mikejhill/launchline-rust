"""Publish one verified, prebuilt Cargo archive without building or executing it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward a registry credential through a redirect."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Reject redirects rather than broadening the credential destination."""
        return


class CrateUpload:
    """Use Cargo's documented upload protocol with a fixed registry destination."""

    API = "https://crates.io/api/v1/crates"

    @staticmethod
    def bundle(directory: Path) -> tuple[dict[str, object], bytes, str]:
        """Require the expected crate, version, digest and reviewed source SHA."""
        record = json.loads((directory / "publish.json").read_text(encoding="utf-8"))
        version = os.environ["VERSION"]
        source = os.environ["GITHUB_SHA"]
        if (
            re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
            or re.fullmatch(r"[0-9a-f]{40}", source) is None
        ):
            raise ValueError("Invalid release identity")
        package = record["package"]
        if (
            package["name"] != "launchline"
            or package["vers"] != version
            or record["source_sha"] != source
        ):
            raise ValueError("Release identity does not match reviewed source")
        filename = f"launchline-{version}.crate"
        if record["crate_file"] != filename:
            raise ValueError("Unexpected crate filename")
        path = directory / filename
        if not 0 < path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("Crate exceeds registry size boundary")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if (
            digest != record["sha256"]
            or package.get("repository")
            != "https://github.com/mikejhill/launchline-rust"
        ):
            raise ValueError("Artifact checksum or repository mismatch")
        return package, payload, digest

    @staticmethod
    def _existing(version: str) -> str | None:
        """Return only the public registry checksum; distinguish 404 from failures."""
        request = urllib.request.Request(
            f"{CrateUpload.API}/launchline/{version}",
            headers={
                "User-Agent": "launchline-release/1 (github.com/mikejhill/launchline-rust)"
            },
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                request, timeout=30
            ) as response:
                return str(json.load(response)["version"]["checksum"])
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise RuntimeError(
                f"Registry inspection failed (HTTP {error.code})"
            ) from None

    @staticmethod
    def publish(directory: Path) -> None:
        """Upload once or accept an exact-checksum retry; never overwrite a version."""
        package, payload, digest = CrateUpload.bundle(directory)
        version = str(package["vers"])
        existing = CrateUpload._existing(version)
        if existing is not None:
            if existing != digest:
                raise ValueError("Existing registry version has different bytes")
            sys.stdout.write("Registry already contains the exact tested crate.\n")
            return
        metadata = json.dumps(package, separators=(",", ":")).encode()
        body = (
            struct.pack("<I", len(metadata))
            + metadata
            + struct.pack("<I", len(payload))
            + payload
        )
        request = urllib.request.Request(
            CrateUpload.API + "/new",
            data=body,
            method="PUT",
            headers={
                "Authorization": os.environ["CRATES_IO_TOKEN"],
                "Content-Type": "application/octet-stream",
                "Accept": "application/json",
                "User-Agent": "launchline-release/1 (github.com/mikejhill/launchline-rust)",
            },
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                request, timeout=60
            ) as response:
                result = json.load(response)
                if result.get("errors"):
                    raise RuntimeError("Registry rejected the upload")
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(
                "Upload outcome uncertain; inspect exact version/checksum before retry"
            ) from error
        for _attempt in range(12):
            existing = CrateUpload._existing(version)
            if existing is not None:
                if existing != digest:
                    raise ValueError("Published checksum differs from tested artifact")
                sys.stdout.write("Published exact tested crate to crates.io.\n")
                return
            time.sleep(5)
        raise RuntimeError(
            "Upload accepted but visibility unconfirmed; inspect before retry"
        )

    @staticmethod
    def main() -> None:
        """Validate without credentials, or publish the same already-tested archive."""
        directory = Path("release")
        if os.environ.get("CRATE_VERIFY_ONLY") == "1":
            CrateUpload.bundle(directory)
            sys.stdout.write("Verified crate release bundle.\n")
        else:
            CrateUpload.publish(directory)


if __name__ == "__main__":
    CrateUpload.main()
