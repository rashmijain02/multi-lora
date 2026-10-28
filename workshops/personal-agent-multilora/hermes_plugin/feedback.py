"""Export reviewed feedback for offline improvement candidates.

Only reviews with explicit learning consent are exported, and only for ``dev``-split
fixtures: validation/test fixtures stay held out so improvement cannot leak into evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import load_fixture
from .permissions import PersonaGrant
from .store import Store


def eligible_feedback(store: Store, root: Path, grant: PersonaGrant) -> tuple[list, list]:
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    query = (
        "SELECT r.review_id, r.job_id, r.draft_hash, r.decision, r.edited_text, r.reason,"
        " r.learning_consent, j.client_id, j.fixture_id, d.body, d.revision"
        " FROM reviews r JOIN jobs j ON j.job_id = r.job_id"
        " JOIN drafts d ON d.job_id = r.job_id AND d.artifact_hash = r.draft_hash"
        " WHERE j.client_id = ? ORDER BY r.created_at"
    )
    for r in store.conn.execute(query, (grant.client_id,)):
        r = dict(r)
        if not r["learning_consent"]:
            skipped.append({"review_id": r["review_id"], "reason": "no_learning_consent"})
            continue
        fixture = load_fixture(root, grant, r["fixture_id"])
        if fixture.data["split"] != "dev":
            skipped.append({"review_id": r["review_id"], "reason": "held_out_split"})
            continue
        if r["decision"] == "reject" and not r["edited_text"]:
            skipped.append({"review_id": r["review_id"], "reason": "rejected_without_edit"})
            continue
        rows.append({
            "client_id": r["client_id"],
            "fixture_id": r["fixture_id"],
            "fixture_hash": fixture.sha,
            "review_id": r["review_id"],
            "draft_hash": r["draft_hash"],
            "decision": r["decision"],
            "subject": fixture.data["subject"],
            "body": fixture.data["body"],
            "target": r["edited_text"] or r["body"],
            "edited": bool(r["edited_text"]),
        })
    return rows, skipped


def export_feedback(store: Store, root: Path, grant: PersonaGrant, out: Path) -> dict[str, Any]:
    rows, skipped = eligible_feedback(store, root, grant)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"exported": len(rows), "skipped": skipped, "path": out.name}
