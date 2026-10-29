"""Collect scoped mutation evidence and reconcile durable default-branch alerts.

The publisher runs as trusted inline workflow code. It never checks out or
executes the tested repository; downloaded artifacts are treated only as data.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar


class MutationEvidence:
    """Validate population, threshold, source identity and execution completeness."""

    SCRIPTS: ClassVar[set[str]] = {
        "scripts/mutation_check.py",
        "scripts/mutate_menus.py",
    }

    @staticmethod
    def integer(value: object, minimum: int = 0) -> int:
        """Reject booleans and malformed counters."""
        if type(value) is not int or value < minimum:
            raise ValueError("Invalid integer counter")
        return value

    @staticmethod
    def digest(data: bytes) -> str:
        """Hash source text independently of checkout newline conversion."""
        return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

    @classmethod
    def policy(cls, raw: object) -> dict[str, Any]:
        """Require an explicit, bounded campaign and its existing required score."""
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema")) is not int
            or raw["schema"] != 1
        ):
            raise ValueError("Missing mutation policy")
        if raw.get("language") not in {"python", "rust"}:
            raise ValueError("Unknown campaign language")
        threshold = raw.get("required_score")
        if type(threshold) not in {int, float} or not 0 <= threshold <= 100:
            raise ValueError("Required mutation score is not configured")
        suites = raw.get("suites")
        if not isinstance(suites, list) or len(suites) != 2:
            raise ValueError("Both seeded campaigns are required")
        names = set()
        for suite in suites:
            if not isinstance(suite, dict):
                raise TypeError("Invalid suite")
            name = suite.get("name")
            if name not in {"baseline", "menus"} or name in names:
                raise ValueError("Invalid suite scope")
            names.add(name)
            expected_script = (
                "scripts/mutation_check.py"
                if name == "baseline"
                else "scripts/mutate_menus.py"
            )
            if suite.get("script") != expected_script:
                raise ValueError("Unexpected mutation harness")
            expected_report = (
                "docs/validation/mutation.json"
                if name == "baseline"
                else "docs/validation/menu-mutation.json"
            )
            if suite.get("report") != expected_report:
                raise ValueError("Unexpected report path")
            population = suite.get("population")
            if not isinstance(population, list) or not 1 <= len(population) <= 1000:
                raise ValueError("Missing full population")
            identities = []
            for item in population:
                if not isinstance(item, dict) or set(item) != {"source", "mutant"}:
                    raise ValueError("Invalid mutant identity")
                if not all(
                    isinstance(item[key], str)
                    and re.fullmatch(r"[A-Za-z0-9_./-]{1,160}", item[key])
                    and ".." not in item[key]
                    for key in ("source", "mutant")
                ):
                    raise ValueError("Unsafe mutant identity")
                identities.append((item["source"], item["mutant"]))
            if len(set(identities)) != len(identities):
                raise ValueError("Duplicate mutant population")
        return raw

    @staticmethod
    def scope(policy: dict[str, Any], harnesses: dict[str, str]) -> str:
        """Bind comparability to policy and seed definitions, not coverage fixes."""
        data = json.dumps(
            {"policy": policy, "harnesses": harnesses},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def assess(
        cls, payload: object, policy: dict[str, Any], harnesses: dict[str, str]
    ) -> dict[str, Any]:
        """Compute the score only from a complete, exact population."""
        policy = cls.policy(policy)
        scope = cls.scope(policy, harnesses)
        expected = sum(len(suite["population"]) for suite in policy["suites"])
        answer: dict[str, Any] = {
            "status": "incomplete",
            "scope": scope,
            "threshold": policy["required_score"],
            "expected": expected,
            "observed": 0,
            "killed": 0,
            "survived": 0,
            "invalid": 0,
            "timeout": 0,
            "score": None,
            "survivors": [],
            "reason": "Execution did not produce complete comparable evidence.",
        }
        if (
            not isinstance(payload, dict)
            or type(payload.get("schema")) is not int
            or payload["schema"] != 1
        ):
            return answer
        if payload.get("scope") != scope:
            answer["reason"] = (
                "Mutation population or harness digest differs from source."
            )
            return answer
        results = payload.get("suites")
        if not isinstance(results, list) or len(results) != len(policy["suites"]):
            return answer
        complete = True
        for suite, result in zip(policy["suites"], results, strict=True):
            if not isinstance(result, dict) or result.get("name") != suite["name"]:
                return answer
            records = result.get("records")
            if not isinstance(records, list):
                return answer
            wanted = {(p["source"], p["mutant"]) for p in suite["population"]}
            seen = set()
            suite_survivors = 0
            for record in records:
                if not isinstance(record, dict):
                    return answer
                identity = (record.get("source"), record.get("mutant"))
                if identity not in wanted or identity in seen:
                    return answer
                seen.add(identity)
                status = record.get("status")
                if status not in {"killed", "survived", "invalid", "timeout"}:
                    return answer
                answer["observed"] += 1
                answer[status] += 1
                if status == "survived":
                    suite_survivors += 1
                    answer["survivors"].append(f"{identity[0]}: {identity[1]}")
            code = result.get("returncode")
            if (
                seen != wanted
                or type(code) is not int
                or code != int(suite_survivors > 0)
            ):
                complete = False
        if not complete or answer["invalid"] or answer["timeout"]:
            return answer
        answer["score"] = 100 * answer["killed"] / expected
        answer["status"] = (
            "healthy" if answer["score"] >= answer["threshold"] else "findings"
        )
        answer["reason"] = (
            "Complete campaign meets the configured required score."
            if answer["status"] == "healthy"
            else "Complete campaign is below the configured required score."
        )
        return answer


class MutationRunner:
    """Run read-only-token campaigns and retain fresh reports and full logs."""

    @staticmethod
    def run(root: Path, environment: dict[str, str]) -> int:
        """Collect both suites; never mistake tracked historical JSON for new output."""
        policy = MutationEvidence.policy(
            json.loads((root / ".github/mutation-policy.json").read_text())
        )
        if environment["GITHUB_REF"] != "refs/heads/" + environment["DEFAULT_BRANCH"]:
            raise ValueError("Mutation execution requires the default branch")
        output = root / "mutation-results"
        output.mkdir(exist_ok=True)
        harnesses = {
            suite["script"]: MutationEvidence.digest(
                (root / suite["script"]).read_bytes()
            )
            for suite in policy["suites"]
        }
        payload: dict[str, Any] = {
            "schema": 1,
            "repository": environment["GITHUB_REPOSITORY"],
            "head_sha": environment["GITHUB_SHA"],
            "run_id": int(environment["GITHUB_RUN_ID"]),
            "run_number": int(environment["GITHUB_RUN_NUMBER"]),
            "run_attempt": int(environment["GITHUB_RUN_ATTEMPT"]),
            "scope": MutationEvidence.scope(policy, harnesses),
            "suites": [],
        }
        for suite in policy["suites"]:
            report = root / suite["report"]
            report.unlink(missing_ok=True)
            records = []
            code = None
            log_path = output / f"{suite['name']}.log"
            print(
                f"Running complete {suite['name']} campaign; log: {log_path}",
                flush=True,
            )
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    result = subprocess.run(
                        [sys.executable, suite["script"], policy["language"]],
                        cwd=root,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=1800,
                    )
                code = result.returncode
                if report.is_file():
                    raw = json.loads(report.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        records = [
                            {
                                key: record.get(key)
                                for key in ("source", "mutant", "status")
                            }
                            for record in raw
                            if isinstance(record, dict)
                        ]
                    (output / f"{suite['name']}.json").write_bytes(report.read_bytes())
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"Campaign execution failed: {error}\n")
            payload["suites"].append(
                {"name": suite["name"], "returncode": code, "records": records}
            )
        assessment = MutationEvidence.assess(payload, policy, harnesses)
        payload["assessment"] = assessment
        (output / "result.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        summary = (
            f"## Seeded mutation campaign: {assessment['status']}\n\n"
            f"Scope: `{assessment['scope']}`\n\n"
            f"Observed {assessment['observed']}/{assessment['expected']}; "
            f"killed {assessment['killed']}; survivors {assessment['survived']}; "
            f"invalid {assessment['invalid']}; timeouts {assessment['timeout']}.\n\n"
            f"Score: {assessment['score']}; required: {assessment['threshold']}%.\n\n"
            "Survivors remain in artifacts even when the required score passes.\n"
        )
        if environment.get("GITHUB_STEP_SUMMARY"):
            Path(environment["GITHUB_STEP_SUMMARY"]).write_text(
                summary, encoding="utf-8"
            )
        print(summary)
        return 0 if assessment["status"] == "healthy" else 1


class GitHub:
    """Use structured API requests; uncertain writes are not automatically repeated."""

    def api(
        self, path: str, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Read or mutate GitHub without shell interpolation or token arguments."""
        command = ["gh", "api", path, "--method", method]
        if payload is not None:
            command += ["--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=60,
        )
        return json.loads(result.stdout)

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        """Search all pages, including closed alerts, without duplicate creation."""
        records = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            response = self.api(f"{path}{separator}per_page=100&page={page}")
            items = response[key] if key else response
            if not isinstance(items, list):
                raise TypeError("Malformed paginated API response")
            records.extend(items)
            if len(items) < 100:
                return records
        raise ValueError("Pagination limit reached; refusing duplicate alert creation")


class MutationAlerts:
    """Keep findings and execution failures separate, with conservative recovery."""

    PREFIX = "<!-- mutation-alert-v1:"
    STATE = "<!-- mutation-state-v1:"

    def __init__(self, client: GitHub, repository: str) -> None:
        """Limit all API paths to the owning, explicitly configured repository."""
        if repository not in {"mikejhill/launchline", "mikejhill/launchline-rust"}:
            raise ValueError("Unexpected alert repository")
        self.client = client
        self.repository = repository
        self.base = f"repos/{repository}"

    def content(self, path: str, revision: str) -> bytes:
        """Read immutable policy/seed blobs as data, never as executable code."""
        record = self.client.api(f"{self.base}/contents/{path}?ref={revision}")
        if record.get("type") != "file":
            raise ValueError("Expected a regular source file")
        return base64.b64decode(record["content"], validate=False)

    @staticmethod
    def sequence(record: dict[str, Any]) -> tuple[int, int]:
        """Order reruns within a run, and reject older runs even if rerun later."""
        return (
            MutationEvidence.integer(record["run_number"], 1),
            MutationEvidence.integer(record["run_attempt"], 1),
        )

    def descendant(self, before: str, after: str) -> bool:
        """Require source ancestry rather than relying only on wall-clock ordering."""
        if before == after:
            return True
        response = self.client.api(f"{self.base}/compare/{before}...{after}")
        return response["merge_base_commit"]["sha"] == before

    @classmethod
    def state(cls, issue: dict[str, Any]) -> dict[str, Any] | None:
        """Reject malformed prior alert state; it cannot authorize recovery."""
        matches = re.findall(
            re.escape(cls.STATE) + r"([A-Za-z0-9+/=]+) -->", issue.get("body") or ""
        )
        if len(matches) != 1 or len(matches[0]) > 16_384:
            return None
        try:
            state = json.loads(base64.b64decode(matches[0], validate=True))
            cls.sequence(state)
            if not re.fullmatch(r"[0-9a-f]{40}", state["head_sha"]):
                return None
            if not re.fullmatch(r"[0-9a-f]{64}", state["scope"]):
                return None
            return state
        except (ValueError, TypeError, KeyError, RecursionError):
            return None

    def newer(self, run: dict[str, Any], issue: dict[str, Any]) -> bool:
        """Only strictly newer descendant evidence can update or recover an alert."""
        old = self.state(issue)
        if old is None:
            return False
        return self.sequence(run) > self.sequence(old) and self.descendant(
            old["head_sha"], run["head_sha"]
        )

    def reconcile(self, event: dict[str, Any], payload: object) -> dict[str, Any]:
        """Validate source identity and idempotently reconcile computed outcomes."""
        run_id = MutationEvidence.integer(event["id"], 1)
        run = self.client.api(f"{self.base}/actions/runs/{run_id}")
        repository = self.client.api(self.base)
        default = repository["default_branch"]
        if (
            run["head_branch"] != default
            or run["head_repository"]["full_name"] != self.repository
            or run["event"] not in {"push", "schedule", "workflow_dispatch"}
            or run["path"] != ".github/workflows/mutation.yml"
            or not re.fullmatch(r"[0-9a-f]{40}", run["head_sha"])
            or not self.descendant(run["head_sha"], default)
        ):
            raise ValueError("Not a trusted default-branch mutation execution")
        if run["status"] != "completed" or run["run_attempt"] != event["run_attempt"]:
            return {"status": "stale", "reason": "Run attempt changed or is incomplete"}
        latest = self.client.pages(
            f"{self.base}/actions/workflows/{run['workflow_id']}/runs"
            f"?branch={default}&status=completed",
            "workflow_runs",
        )
        if any(
            item.get("event") in {"push", "schedule", "workflow_dispatch"}
            and item.get("head_branch") == default
            and self.sequence(item) > self.sequence(run)
            for item in latest
        ):
            return {"status": "stale", "reason": "A newer completed run exists"}
        try:
            policy = MutationEvidence.policy(
                json.loads(
                    self.content(".github/mutation-policy.json", run["head_sha"])
                )
            )
            harnesses = {
                suite["script"]: MutationEvidence.digest(
                    self.content(suite["script"], run["head_sha"])
                )
                for suite in policy["suites"]
            }
            assessment = MutationEvidence.assess(payload, policy, harnesses)
            if (
                not isinstance(payload, dict)
                or any(
                    payload.get(key) != run[key]
                    for key in ("head_sha", "run_number", "run_attempt")
                )
                or payload.get("run_id") != run_id
                or payload.get("repository") != self.repository
                or any(
                    type(payload.get(key)) is not int
                    for key in ("run_id", "run_number", "run_attempt")
                )
            ):
                assessment["status"] = "incomplete"
                assessment["score"] = None
                assessment["reason"] = (
                    "Missing, malformed or mismatched result artifact."
                )
        except (
            ValueError,
            KeyError,
            TypeError,
            RecursionError,
            subprocess.CalledProcessError,
        ):
            assessment = {
                "status": "infrastructure",
                "scope": "0" * 64,
                "threshold": None,
                "score": None,
                "reason": "Source policy or results are malformed; inspect logs.",
            }
        if run["conclusion"] in {
            "cancelled",
            "skipped",
            "timed_out",
            "action_required",
        }:
            assessment["status"] = (
                run["conclusion"]
                if run["conclusion"] in {"cancelled", "skipped"}
                else "infrastructure"
            )
            assessment["score"] = None
            assessment["reason"] = (
                "Execution did not complete; findings recovery is forbidden."
            )
        elif assessment["status"] == "healthy" and run["conclusion"] != "success":
            assessment["status"] = "infrastructure"
            assessment["score"] = None
            assessment["reason"] = (
                "Workflow failed despite its artifact; inspect execution logs."
            )
        issues = [
            issue
            for issue in self.client.pages(f"{self.base}/issues?state=all")
            if "pull_request" not in issue
            and issue.get("user", {}).get("id") == 41898282
            and issue.get("user", {}).get("login") == "github-actions[bot]"
        ]
        prior = [
            self.state(issue)
            for issue in issues
            if self.PREFIX in (issue.get("body") or "")
        ]
        if any(
            state is not None and self.sequence(state) > self.sequence(run)
            for state in prior
        ):
            return {"status": "stale", "reason": "Newer durable alert evidence exists"}
        finding_marker = f"{self.PREFIX}findings:{assessment['scope']} -->"
        execution_marker = f"{self.PREFIX}execution -->"

        def find(marker: str) -> dict[str, Any] | None:
            matches = [issue for issue in issues if marker in (issue.get("body") or "")]
            if len(matches) > 1:
                raise ValueError(
                    "Duplicate managed alerts require manual reconciliation"
                )
            return matches[0] if matches else None

        finding = find(finding_marker)
        execution = find(execution_marker)
        complete = assessment["status"] in {"healthy", "findings"}
        if complete and any(
            issue is not None and self.state(issue) is None
            for issue in (finding, execution)
        ):
            assessment["status"] = "infrastructure"
            assessment["score"] = None
            assessment["reason"] = (
                "Prior alert metadata is malformed; manual triage required."
            )
            complete = False
        if (
            complete
            and finding is not None
            and self.state(finding)["scope"] != assessment["scope"]
        ):
            assessment["status"] = "infrastructure"
            assessment["score"] = None
            assessment["reason"] = (
                "Prior findings scope is inconsistent; manual triage required."
            )
            complete = False
        if complete:
            if assessment["status"] == "findings":
                self.write("findings", finding_marker, finding, run, assessment, "open")
            elif finding is not None and self.newer(run, finding):
                self.write(
                    "findings", finding_marker, finding, run, assessment, "closed"
                )
            if execution is not None and self.newer(run, execution):
                self.write(
                    "execution", execution_marker, execution, run, assessment, "closed"
                )
        else:
            self.write(
                "execution", execution_marker, execution, run, assessment, "open"
            )
        return assessment

    def write(
        self,
        kind: str,
        marker: str,
        issue: dict[str, Any] | None,
        run: dict[str, Any],
        assessment: dict[str, Any],
        state: str,
    ) -> None:
        """Manage one scoped issue without comments or healthy-run spam."""
        if (
            issue is not None
            and self.state(issue) is not None
            and not self.newer(run, issue)
        ):
            return
        saved = {key: run[key] for key in ("head_sha", "run_number", "run_attempt")}
        saved["scope"] = assessment["scope"]
        encoded = base64.b64encode(json.dumps(saved, sort_keys=True).encode()).decode()
        url = f"https://github.com/{self.repository}/actions/runs/{run['id']}"
        title = (
            f"Mutation score below required threshold ({assessment['scope'][:8]})"
            if kind == "findings"
            else "Mutation execution needs attention"
        )
        counts = ", ".join(
            f"{name}: {assessment.get(name, 'unknown')}"
            for name in (
                "expected",
                "observed",
                "killed",
                "survived",
                "invalid",
                "timeout",
            )
        )
        survivors = "\n".join(f"- `{item}`" for item in assessment.get("survivors", []))
        score = (
            "unavailable"
            if assessment["score"] is None
            else f"{assessment['score']:.2f}%"
        )
        threshold = (
            "unconfigured"
            if assessment["threshold"] is None
            else f"{assessment['threshold']}%"
        )
        body = (
            f"{marker}\n{self.STATE}{encoded} -->\n\n"
            f"Result: **{assessment['status']}**. [Run {run['run_number']} "
            f"attempt {run['run_attempt']}]({url}); commit `{run['head_sha']}`.\n\n"
            f"Scope: `{assessment['scope']}` "
            "(seeded campaign, not exhaustive coverage).\n\n"
            f"{counts}. Score: **{score}**; required: "
            f"**{threshold}**. A score at or above the threshold passes.\n\n"
            f"{assessment['reason']}\n\n{survivors}\n\n"
            "Triage the linked logs and mutation-results artifact. Add meaningful "
            "coverage or investigate surviving seeds; retain the configured threshold. "
            "For execution failures, repair setup/harness/timeout errors and rerun "
            "on the default branch. Only newer complete comparable results "
            "can resolve findings; "
            "partial, cancelled, skipped and malformed results cannot. "
            f"See [mutation policy and operations](https://github.com/{self.repository}/blob/main/docs/mutation-testing.md).\n"
        )
        assignees = sorted(
            {"mikejhill"}
            | {user["login"] for user in (issue or {}).get("assignees", [])}
        )
        data = {"title": title, "body": body, "state": state, "assignees": assignees}
        if issue is None:
            self.client.api(f"{self.base}/issues", "POST", data)
        else:
            self.client.api(f"{self.base}/issues/{issue['number']}", "PATCH", data)


def main() -> None:
    """Select the unprivileged collector or trusted workflow-run publisher."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "publish"])
    args = parser.parse_args()
    if args.command == "run":
        raise SystemExit(MutationRunner.run(Path.cwd(), dict(os.environ)))
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    result = Path(os.environ["RESULT_DIRECTORY"]) / "result.json"
    payload = None
    if (
        not result.is_symlink()
        and result.is_file()
        and result.stat().st_size <= 1_048_576
    ):
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            payload = None
    assessment = MutationAlerts(GitHub(), os.environ["GITHUB_REPOSITORY"]).reconcile(
        event["workflow_run"], payload
    )
    summary = (
        "## Mutation alert reconciliation\n\n```json\n"
        + json.dumps(assessment, indent=2)
        + "\n```\n"
    )
    Path("mutation-alert-assessment.json").write_text(
        json.dumps(assessment, indent=2) + "\n", encoding="utf-8"
    )
    print(summary)
    Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
