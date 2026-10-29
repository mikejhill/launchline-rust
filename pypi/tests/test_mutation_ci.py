"""Mock alert state transitions and validate the real asynchronous workflow contract."""

from __future__ import annotations

import base64
import copy
import json
import re
import runpy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = next(
    p for p in Path(__file__).parents if (p / "scripts/mutation_ci.py").is_file()
)
MODULE = runpy.run_path(str(ROOT / "scripts/mutation_ci.py"))
EVIDENCE = MODULE["MutationEvidence"]
ALERTS = MODULE["MutationAlerts"]
RUNNER = MODULE["MutationRunner"]


def policy(threshold: float = 100) -> dict[str, Any]:
    """Create a small complete population for threshold-boundary tests."""
    return {
        "schema": 1,
        "language": "python",
        "required_score": threshold,
        "suites": [
            {
                "name": "baseline",
                "script": "scripts/mutation_check.py",
                "report": "docs/validation/mutation.json",
                "population": [
                    {"source": "src/example.py", "mutant": name}
                    for name in ["seed-a", "seed-b"]
                ],
            },
            {
                "name": "menus",
                "script": "scripts/mutate_menus.py",
                "report": "docs/validation/menu-mutation.json",
                "population": [
                    {"source": "src/example.py", "mutant": name}
                    for name in ["menu-a", "menu-b"]
                ],
            },
        ],
    }


class FakeGitHub(MODULE["GitHub"]):
    """Simulate GitHub reads/writes, with no live issue creation."""

    def __init__(self, threshold: float = 100) -> None:
        self.repository = "mikejhill/launchline"
        self.base = "repos/" + self.repository
        self.policy = policy(threshold)
        self.harnesses = {
            "scripts/mutation_check.py": b"baseline seeds\n",
            "scripts/mutate_menus.py": b"menu seeds\n",
        }
        self.issues: list[dict[str, Any]] = []
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.reads: list[str] = []
        self.latest: list[dict[str, Any]] = []
        self.diverged: set[tuple[str, str]] = set()
        self.run: dict[str, Any] = {}
        self.advance(1)

    def advance(self, number: int, conclusion: str = "success") -> None:
        """Move to a newer descendant default-branch run."""
        self.run = {
            "id": 1000 + number,
            "run_number": number,
            "run_attempt": 1,
            "head_sha": f"{number:040x}",
            "head_branch": "main",
            "head_repository": {"full_name": self.repository},
            "event": "push",
            "path": ".github/workflows/mutation.yml",
            "workflow_id": 50,
            "status": "completed",
            "conclusion": conclusion,
        }

    def evidence(self, statuses: list[str] | None = None) -> dict[str, Any]:
        """Produce identity-bound data; scores are independently recomputed."""
        states = statuses or ["killed"] * 4
        hashes = {name: EVIDENCE.digest(data) for name, data in self.harnesses.items()}
        results = []
        for index, suite in enumerate(self.policy["suites"]):
            records = [
                {**item, "status": states[index * 2 + n]}
                for n, item in enumerate(suite["population"])
            ]
            results.append(
                {
                    "name": suite["name"],
                    "records": records,
                    "returncode": int(any(r["status"] != "killed" for r in records)),
                }
            )
        return {
            "schema": 1,
            "repository": self.repository,
            "run_id": self.run["id"],
            "run_number": self.run["run_number"],
            "run_attempt": self.run["run_attempt"],
            "head_sha": self.run["head_sha"],
            "scope": EVIDENCE.scope(self.policy, hashes),
            "suites": results,
        }

    def api(
        self, path: str, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Interpret the publisher's fixed API paths and record mutations."""
        if method != "GET":
            assert payload is not None
            self.writes.append((method, copy.deepcopy(payload)))
            if method == "POST":
                record = {
                    "number": max([i["number"] for i in self.issues] + [0]) + 1,
                    "user": {"id": 41898282, "login": "github-actions[bot]"},
                }
                self.issues.append(record)
            else:
                number = int(path.rsplit("/", 1)[1])
                record = next(i for i in self.issues if i["number"] == number)
            record.update(copy.deepcopy(payload))
            record["assignees"] = [{"login": name} for name in payload["assignees"]]
            return copy.deepcopy(record)
        self.reads.append(path)
        if path == self.base:
            return {"default_branch": "main"}
        if "/actions/runs/" in path:
            assert int(path.rsplit("/", 1)[1]) == self.run["id"]
            return copy.deepcopy(self.run)
        if "/contents/" in path:
            filename = path.split("/contents/", 1)[1].split("?", 1)[0]
            content = (
                json.dumps(self.policy).encode()
                if filename == ".github/mutation-policy.json"
                else self.harnesses[filename]
            )
            return {"type": "file", "content": base64.b64encode(content).decode()}
        if "/compare/" in path:
            before, after = path.split("/compare/", 1)[1].split("...", 1)
            return {
                "merge_base_commit": {
                    "sha": "0" * 40 if (before, after) in self.diverged else before
                }
            }
        page = int(re.search(r"page=(\d+)$", path)[1])
        start = (page - 1) * 100
        if "/actions/workflows/" in path:
            return {
                "workflow_runs": copy.deepcopy(
                    (self.latest or [self.run])[start : start + 100]
                )
            }
        if "/issues?" in path:
            return copy.deepcopy(self.issues[start : start + 100])
        raise AssertionError(path)

    def publish(self, payload: object) -> dict[str, Any]:
        """Run the real reconciliation code against this fake service."""
        return ALERTS(self, self.repository).reconcile(copy.deepcopy(self.run), payload)


class TestMutationAlerts:
    """Cover genuine findings, passing scores and conservative alert recovery."""

    @pytest.mark.parametrize(
        ("threshold", "status", "issues"),
        [(75, "healthy", 0), (50, "healthy", 0), (100, "findings", 1)],
    )
    def test_threshold_equality_above_and_below(
        self, threshold: float, status: str, issues: int
    ) -> None:
        """Passing scores retain survivors without opening findings issues."""
        client = FakeGitHub(threshold)
        result = client.publish(client.evidence(["killed"] * 3 + ["survived"]))
        assert result["score"] == 75
        assert result["status"] == status
        assert result["survivors"]
        assert len(client.issues) == issues
        if issues:
            assert client.issues[0]["assignees"] == [{"login": "mikejhill"}]
            assert "required: **100%**" in client.issues[0]["body"]

    def test_create_update_reopen_and_idempotence(self) -> None:
        """Repeated events reconcile one issue and fresh regressions reopen it."""
        client = FakeGitHub()
        payload = client.evidence(["killed"] * 3 + ["survived"])
        client.publish(payload)
        client.publish(payload)
        assert len(client.writes) == 1
        client.issues[0]["state"] = "closed"
        client.advance(2, "failure")
        client.publish(client.evidence(["killed", "survived"] * 2))
        assert len(client.issues) == 1
        assert client.issues[0]["state"] == "open"
        assert "Score: **50.00%**" in client.issues[0]["body"]

    def test_new_complete_comparable_result_recovers_both_alerts(self) -> None:
        """New complete source evidence resolves old score and execution alerts."""
        client = FakeGitHub()
        client.publish(client.evidence(["killed"] * 3 + ["survived"]))
        client.advance(2, "failure")
        client.publish(None)
        assert len(client.issues) == 2
        assert all(i["state"] == "open" for i in client.issues)
        client.advance(3)
        assert client.publish(client.evidence())["status"] == "healthy"
        assert all(i["state"] == "closed" for i in client.issues)

    def test_passing_score_with_survivors_recovers_without_claiming_fixed(self) -> None:
        """Recovery means the threshold passed, rather than all mutants vanished."""
        client = FakeGitHub(75)
        client.publish(client.evidence(["killed", "survived"] * 2))
        client.advance(2)
        result = client.publish(client.evidence(["killed"] * 3 + ["survived"]))
        assert result["score"] == 75
        assert result["survivors"]
        assert client.issues[0]["state"] == "closed"
        assert "survived: 1" in client.issues[0]["body"]
        assert "mutants fixed" not in client.issues[0]["body"]

    def test_non_descendant_evidence_cannot_recover_findings(self) -> None:
        """A newer run number alone cannot authorize source recovery."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        old = client.run["head_sha"]
        client.advance(2)
        client.diverged.add((old, client.run["head_sha"]))
        client.publish(client.evidence())
        assert client.issues[0]["state"] == "open"
        assert len(client.writes) == 1

    @pytest.mark.parametrize(
        "conclusion", ["cancelled", "skipped", "timed_out", "action_required"]
    )
    def test_incomplete_execution_never_closes_findings(self, conclusion: str) -> None:
        """Cancelled and skipped jobs cannot turn a stored regression green."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        client.advance(2, conclusion)
        result = client.publish(client.evidence())
        assert result["score"] is None
        assert result["status"] in {"cancelled", "skipped", "infrastructure"}
        assert len(client.issues) == 2
        assert all(i["state"] == "open" for i in client.issues)

    @pytest.mark.parametrize(
        "fault",
        ["missing", "duplicate", "invalid", "timeout", "identity", "boolean", "scope"],
    )
    def test_partial_or_malformed_data_preserves_findings(self, fault: str) -> None:
        """Malformed evidence opens a separate execution alert."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        client.advance(2, "failure")
        payload = client.evidence()
        if fault == "missing":
            payload["suites"][0]["records"].pop()
        elif fault == "duplicate":
            payload["suites"][0]["records"][1] = payload["suites"][0]["records"][0]
        elif fault in {"invalid", "timeout"}:
            payload["suites"][0]["records"][0]["status"] = fault
        elif fault == "identity":
            payload["head_sha"] = "f" * 40
        elif fault == "boolean":
            payload["suites"][0]["returncode"] = False
        else:
            payload["scope"] = "f" * 64
        result = client.publish(payload)
        assert result["status"] == "incomplete"
        assert result["score"] is None
        assert client.issues[0]["state"] == "open"
        assert len(client.issues) == 2

    def test_scope_change_is_not_comparable_recovery(self) -> None:
        """Different seed definitions cannot close the older population's issue."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        client.advance(2)
        client.harnesses["scripts/mutation_check.py"] = b"different seed definitions"
        assert client.publish(client.evidence())["status"] == "healthy"
        assert client.issues[0]["state"] == "open"
        assert len(client.writes) == 1

    def test_stale_and_superseded_attempts_cannot_recover(self) -> None:
        """Out-of-order events and older attempts leave newer evidence intact."""
        client = FakeGitHub()
        client.advance(5)
        client.publish(client.evidence(["survived"] * 4))
        newer = copy.deepcopy(client.run)
        client.advance(4)
        client.latest = [newer]
        assert client.publish(client.evidence())["status"] == "stale"
        assert client.issues[0]["state"] == "open"
        event = copy.deepcopy(client.run)
        client.run["run_attempt"] = 2
        assert (
            ALERTS(client, client.repository).reconcile(event, client.evidence())[
                "status"
            ]
            == "stale"
        )
        assert len(client.writes) == 1

    def test_missing_required_threshold_is_not_invented(self) -> None:
        """Missing policy produces an execution alert with no fabricated score."""
        client = FakeGitHub()
        payload = client.evidence()
        del client.policy["required_score"]
        result = client.publish(payload)
        assert result["status"] == "infrastructure"
        assert result["threshold"] is None
        assert "unconfigured" in client.issues[0]["body"]

    def test_durable_watermark_survives_workflow_history_lag(self) -> None:
        """New incomplete evidence blocks recovery from an older healthy run."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        client.advance(3, "failure")
        client.publish(None)
        client.advance(2)
        assert client.publish(client.evidence())["status"] == "stale"
        assert all(issue["state"] == "open" for issue in client.issues)

    def test_untrusted_issue_cannot_spoof_the_bot_watermark(self) -> None:
        """Public issue text is data and cannot suppress the managed campaign."""
        client = FakeGitHub()
        client.advance(500)
        client.publish(client.evidence(["survived"] * 4))
        client.issues[0]["user"] = {"id": 123, "login": "someone"}
        client.advance(2)
        assert client.publish(client.evidence(["survived"] * 4))["status"] == "findings"
        assert len(client.issues) == 2

    def test_malformed_prior_state_requires_manual_triage(self) -> None:
        """Unknown historical alert metadata cannot authorize automatic closure."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        client.issues[0]["body"] = client.issues[0]["body"].split("\n", 1)[0]
        client.advance(2)
        assert client.publish(client.evidence())["status"] == "infrastructure"
        assert client.issues[0]["state"] == "open"

    def test_paginated_closed_alert_is_reopened_without_duplicates(self) -> None:
        """Closed alerts beyond page one are found while PR lookalikes are ignored."""
        client = FakeGitHub()
        client.publish(client.evidence(["survived"] * 4))
        canonical = copy.deepcopy(client.issues[0])
        canonical.update(number=101, state="closed")
        dummies = [
            {"number": n, "body": "unrelated", "state": "closed"} for n in range(1, 101)
        ]
        dummies[0].update(body=canonical["body"], pull_request={})
        client.issues = [*dummies, canonical]
        client.advance(2, "failure")
        client.publish(client.evidence(["survived"] * 4))
        assert len(client.issues) == 101
        assert client.issues[-1]["state"] == "open"
        assert any("issues?state=all&per_page=100&page=2" in p for p in client.reads)

    @pytest.mark.parametrize("fault", ["branch", "fork", "event", "path"])
    def test_foreign_or_nondefault_executions_are_rejected(self, fault: str) -> None:
        """Only executions of this workflow on this default branch can write."""
        client = FakeGitHub()
        if fault == "branch":
            client.run["head_branch"] = "feature"
        elif fault == "fork":
            client.run["head_repository"]["full_name"] = "someone/fork"
        elif fault == "event":
            client.run["event"] = "pull_request"
        else:
            client.run["path"] = ".github/workflows/unrelated.yml"
        with pytest.raises(ValueError, match="trusted default-branch"):
            client.publish(client.evidence())
        assert not client.writes


class TestMutationWorkflow:
    """Keep mutation asynchronous and privileged publication isolated from source."""

    def test_workflow_trigger_permissions_and_inline_source(self) -> None:
        """Keep execution read-only and alert code independent of artifact code."""
        worker = yaml.safe_load((ROOT / ".github/workflows/mutation.yml").read_text())
        publisher = yaml.safe_load(
            (ROOT / ".github/workflows/mutation-alerts.yml").read_text()
        )
        assert set(worker["on"]) == {"push", "schedule", "workflow_dispatch"}
        assert worker["on"]["push"]["branches"] == ["main"]
        assert worker["concurrency"]["cancel-in-progress"] is False
        job = worker["jobs"]["mutation"]
        assert job["permissions"] == {"contents": "read"}
        assert "Default branch required" in job["steps"][0]["run"]
        assert publisher["on"]["workflow_run"]["types"] == ["completed"]
        assert publisher["concurrency"]["cancel-in-progress"] is False
        alert = publisher["jobs"]["publish"]
        assert alert["permissions"] == {
            "contents": "read",
            "actions": "read",
            "issues": "write",
        }
        assert "head_branch == github.event.repository.default_branch" in alert["if"]
        assert not any("checkout" in step.get("uses", "") for step in alert["steps"])
        inline = next(step["run"] for step in alert["steps"] if "run" in step)
        code = (
            inline.split("python3 - publish <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0] + "\n"
        )
        assert code == (ROOT / "scripts/mutation_ci.py").read_text()

    def test_pr_release_and_composite_gates_do_not_run_mutation(self) -> None:
        """PR and release pipelines preserve other checks without mutation work."""
        for name in ["ci.yml", "release.yml"]:
            text = (ROOT / ".github/workflows" / name).read_text()
            assert "scripts/mutation_check.py" not in text
            assert "scripts/mutate_menus.py" not in text
            assert "poe mutation" not in text
        project = ROOT / "pyproject.toml"
        if project.is_file():
            line = next(
                s
                for s in project.read_text().splitlines()
                if s.startswith("release-check =")
            )
            assert "mutation" not in line


class TestMutationCollector:
    """Exercise fresh-output collection with harmless disposable harness fixtures."""

    @staticmethod
    def fixture(root: Path, threshold: float, statuses: list[str]) -> dict[str, str]:
        """Use tiny child scripts, without running a mutation campaign in PR tests."""
        configured = policy(threshold)
        (root / ".github").mkdir()
        (root / "scripts").mkdir()
        (root / "docs/validation").mkdir(parents=True)
        (root / ".github/mutation-policy.json").write_text(json.dumps(configured))
        for index, suite in enumerate(configured["suites"]):
            records = [
                {**item, "status": statuses[index * 2 + n]}
                for n, item in enumerate(suite["population"])
            ]
            code = int(any(record["status"] == "survived" for record in records))
            script = (
                "import pathlib\n"
                f"pathlib.Path({suite['report']!r}).write_text({json.dumps(records)!r})\n"
                f"raise SystemExit({code})\n"
            )
            (root / suite["script"]).write_text(script, encoding="utf-8")
        return {
            "GITHUB_REF": "refs/heads/main",
            "DEFAULT_BRANCH": "main",
            "GITHUB_REPOSITORY": "mikejhill/launchline",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "10",
            "GITHUB_RUN_NUMBER": "1",
            "GITHUB_RUN_ATTEMPT": "1",
        }

    @pytest.mark.parametrize(
        ("threshold", "statuses"),
        [(100, ["killed"] * 4), (75, ["killed"] * 3 + ["survived"])],
    )
    def test_complete_collection_respects_the_configured_score(
        self, tmp_path: Path, threshold: float, statuses: list[str]
    ) -> None:
        """A passing threshold can include survivors and a legacy harness exit one."""
        environment = self.fixture(tmp_path, threshold, statuses)
        assert RUNNER.run(tmp_path, environment) == 0
        result = json.loads((tmp_path / "mutation-results/result.json").read_text())
        assert result["assessment"]["status"] == "healthy"
        assert result["assessment"]["observed"] == 4

    def test_historical_report_is_not_reused_after_execution_failure(
        self, tmp_path: Path
    ) -> None:
        """Deleting old report data prevents a failed campaign looking healthy."""
        environment = self.fixture(tmp_path, 100, ["killed"] * 4)
        (tmp_path / "docs/validation/mutation.json").write_text("[]")
        (tmp_path / "scripts/mutation_check.py").write_text("raise SystemExit(2)\n")
        assert RUNNER.run(tmp_path, environment) == 1
        result = json.loads((tmp_path / "mutation-results/result.json").read_text())
        assert result["assessment"]["status"] == "incomplete"
        assert result["assessment"]["score"] is None
        assert (tmp_path / "mutation-results/baseline.log").is_file()

    def test_nondefault_manual_ref_is_rejected_before_execution(
        self, tmp_path: Path
    ) -> None:
        """Manual execution cannot sample an unreviewed branch."""
        environment = self.fixture(tmp_path, 100, ["killed"] * 4)
        environment["GITHUB_REF"] = "refs/heads/feature"
        with pytest.raises(ValueError, match="default branch"):
            RUNNER.run(tmp_path, environment)
        assert not (tmp_path / "mutation-results").exists()
