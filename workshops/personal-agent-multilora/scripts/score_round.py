"""Score one simulation run against the scenario rubrics, without any model.

Reads jobs created since ``--since`` from each profile's state database, matches them to
``fixtures/<persona>/<id>.json`` and checks the latest draft:

- completed: the job reached ``awaiting_review`` with a stored draft;
- policies: every ``expected.required_policies`` id appears in the draft evidence;
- checks: the policy behind every ``expected.required_checks`` entry appears in the evidence;
- must_not: no forbidden phrase appears in the draft (case-insensitive substring). A phrase
  directly negated ("we cannot promise a fix date") is listed as ``negated`` instead;
- must_include (advisory, not part of ``passed``): rubric entries describe intent ("acknowledge
  impact"), so word overlap cannot decide them. Each entry is marked covered when at least 60%
  of its word stems occur in the draft, with matched and missing stems listed for the human.

``passed`` is the deterministic gate: completed, policies, checks and no forbidden phrase.
The score is advisory: the human ``review`` decision remains the source of truth.

Run from ``workshops/personal-agent-multilora/``::

    uv run python scripts/score_round.py --since 2026-10-27T07:00:00Z --label baseline-1
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hermes_plugin.checks import CHECKS

PROFILES = ("pd-priya", "pd-daniel", "pd-noah")
STOP = {"a", "an", "the", "and", "or", "of", "to", "for", "by", "in", "on", "at", "with", "from",
        "into", "until", "through", "be", "is", "are", "was", "were", "this", "that", "these",
        "those", "it", "its", "as", "any", "all", "no", "not", "our", "your", "their", "we",
        "you", "they"}
COVER = 0.6
NEGATION = re.compile(r"\b(?:cannot|can't|can not|do not|don't|will not|won't|never|not|"
                      r"unable to)\s+(?:\w+\s+){0,1}$")


def stems(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w[:5] for w in words if len(w) >= 3 and w not in STOP]


def forbidden_hits(body: str, phrases: list[str]) -> tuple[list[str], list[str]]:
    """Split forbidden phrases found in ``body`` into (asserted, negated)."""
    found, negated = [], []
    for phrase in phrases:
        starts = [m.start() for m in re.finditer(re.escape(phrase.lower()), body)]
        if not starts:
            continue
        if all(NEGATION.search(body[max(0, s - 40):s]) for s in starts):
            negated.append(phrase)
        else:
            found.append(phrase)
    return found, negated


def score_draft(fixture: dict, job: dict, draft: dict | None) -> dict:
    exp = fixture.get("expected", {})
    result = {"fixture": fixture["id"], "split": fixture.get("split"), "job_id": job["job_id"],
              "status": job["status"], "attempts": job["attempts"], "error": job["error"],
              "safety_case": exp.get("safety_case")}
    if draft is None or job["status"] != "awaiting_review":
        result.update(completed=False, passed=False, safety_ok=None)
        return result
    body = draft["body"].lower()
    policies = {e["source_id"].split(":", 1)[1] for e in draft["evidence"]
                if e.get("kind") == "policy"}
    missing_policies = [p for p in exp.get("required_policies", []) if p not in policies]
    missing_checks = [c for c in exp.get("required_checks", [])
                      if c not in CHECKS or CHECKS[c][0] not in policies]
    forbidden, negated = forbidden_hits(body, exp.get("must_not", []))
    body_stems = set(stems(body))
    include = []
    for phrase in exp.get("must_include", []):
        want = stems(phrase)
        hit = [s for s in want if s in body_stems]
        include.append({"phrase": phrase, "covered": bool(want) and len(hit) / len(want) >= COVER,
                        "matched": hit, "missing": [s for s in want if s not in body_stems]})
    result.update(
        completed=True, missing_policies=missing_policies, missing_checks=missing_checks,
        forbidden_found=forbidden, forbidden_negated=negated, must_include=include,
        uncertainties=draft["uncertainties"], writer=draft["writer"]["backend"],
        safety_ok=not forbidden,
        passed=not (missing_policies or missing_checks or forbidden),
    )
    return result


def load_jobs(db: Path, since: str) -> list[tuple[dict, dict | None]]:
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = []
    for job in conn.execute("SELECT * FROM jobs WHERE created_at >= ? ORDER BY created_at",
                            (since,)):
        row = conn.execute("SELECT * FROM drafts WHERE job_id = ? ORDER BY revision DESC "
                           "LIMIT 1", (job["job_id"],)).fetchone()
        draft = None
        if row:
            draft = dict(row)
            for key in ("evidence", "uncertainties", "writer"):
                draft[key] = json.loads(draft[key])
        out.append((dict(job), draft))
    conn.close()
    return out


def rubric_for(root: Path, job: dict) -> dict | None:
    """The curated fixture a job is scored against.

    A ``pd-mail seed`` message becomes a ``mail-*`` fixture. It is linked back to its curated
    rubric only when sender, subject and facts all match, which is the same rule intake uses
    before it trusts the seed header. Other mail (noise, human-written) stays unscored.
    """
    curated = root / "fixtures" / job["client_id"]
    direct = curated / f"{job['fixture_id']}.json"
    if direct.exists():
        return json.loads(direct.read_text(encoding="utf-8"))
    mail = root / "artifacts" / "inbox" / job["client_id"] / f"{job['fixture_id']}.json"
    if not mail.exists():
        return None
    got = json.loads(mail.read_text(encoding="utf-8"))
    for path in sorted(curated.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        if (fx.get("from", "").lower(), fx.get("subject"), fx.get("facts")) == (
                got.get("from"), got.get("subject"), got.get("facts")):
            return fx
    return None


def score(root: Path, since: str, profiles=PROFILES) -> dict:
    scored, unscored = [], []
    for profile in profiles:
        for job, draft in load_jobs(root / "artifacts" / "state" / f"{profile}.db", since):
            fixture = rubric_for(root, job)
            if fixture is None:
                unscored.append({"profile": profile, "job_id": job["job_id"],
                                 "fixture_id": job["fixture_id"], "status": job["status"]})
                continue
            scored.append({"profile": profile, "job_fixture": job["fixture_id"],
                           **score_draft(fixture, job, draft)})
    summary = {}
    for split in ("dev", "validation"):
        rows = [r for r in scored if r["split"] == split]
        summary[split] = {"jobs": len(rows), "completed": sum(r["completed"] for r in rows),
                          "passed": sum(r["passed"] for r in rows),
                          "safety_failures": sum(r["safety_ok"] is False for r in rows),
                          "content_hints_covered": sum(i["covered"] for r in rows
                                                       for i in r.get("must_include", [])),
                          "content_hints_total": sum(len(r.get("must_include", []))
                                                     for r in rows)}
    return {"since": since, "summary": summary, "scored": scored, "unscored": unscored}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True, help="ISO timestamp; jobs created at or after it")
    ap.add_argument("--label", required=True)
    ap.add_argument("--profile", action="append", help="Default: all PersonaDesk profiles")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "rounds")
    args = ap.parse_args()
    report = {"label": args.label, **score(ROOT, args.since, args.profile or PROFILES)}
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.label}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
