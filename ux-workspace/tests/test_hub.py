"""Unit tests for the Workshop Hub sidecar (ux-workspace/hub/hub_sidecar.py).

Run from the repository root:

    workshops\\personal-agent-multilora\\.venv\\Scripts\\python.exe -m pytest ux-workspace/tests -q
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[1] / "hub" / "hub_sidecar.py"
spec = importlib.util.spec_from_file_location("hub_sidecar", HUB)
hub = importlib.util.module_from_spec(spec)
sys.modules["hub_sidecar"] = hub
spec.loader.exec_module(hub)

TOKEN = "t" * 32


def manifest(wid: str = "demo", **overrides):
    data = {
        "schema": 1, "id": wid, "order": 1, "label": "Workshop X", "title": "Demo",
        "summary": "A demo workshop.", "status": "built", "optional": False, "hardware": "CPU",
        "docs": [{"path": "README.md", "title": "Start here"}],
        "commands": [{"kind": "check", "label": "Tests", "cwd": ".", "run": "pytest -q"}],
    }
    data.update(overrides)
    return data


def make_repo(tmp_path: Path, manifests: dict[str, object]) -> Path:
    for wid, data in manifests.items():
        folder = tmp_path / "workshops" / wid
        folder.mkdir(parents=True)
        (folder / "README.md").write_text(f"# {wid}\n", encoding="utf-8")
        (folder / "workshop.json").write_text(
            data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return tmp_path


# ---- the real repository -------------------------------------------------------------------

def test_every_real_workshop_manifest_is_valid():
    registry = hub.load_registry(hub.REPO_ROOT)
    assert registry.errors == []
    folders = {p.parent.name for p in (hub.REPO_ROOT / "workshops").glob("*/workshop.json")}
    assert {w["id"] for w in registry.workshops} == folders
    orders = [w["order"] for w in registry.workshops]
    assert orders == sorted(orders)


# ---- validation ----------------------------------------------------------------------------

@pytest.mark.parametrize("overrides, expected", [
    ({"schema": 2}, "'schema' must be 1"),
    ({"id": "other"}, "must equal the folder name"),
    ({"order": True}, "'order' must be an integer"),
    ({"status": "done"}, "'status' must be one of"),
    ({"summary": "x" * 401}, "at most 400"),
    ({"surprise": 1}, "unknown field 'surprise'"),
    ({"docs": []}, "'docs' must be a non-empty list"),
    ({"docs": [{"path": "../secret.md", "title": "x"}]}, "relative '.md' path"),
    ({"docs": [{"path": "notes.txt", "title": "x"}]}, "relative '.md' path"),
    ({"docs": [{"path": "MISSING.md", "title": "x"}]}, "does not exist"),
    ({"docs": [{"path": "README.md", "title": "a"}, {"path": "README.md", "title": "b"}]}, "listed twice"),
    ({"readiness": [{"label": "x", "path": "../outside"}]}, "readiness[0]"),
    ({"readiness": [{"label": "x", "path": "C:/abs"}]}, "readiness[0]"),
    ({"commands": [{"kind": "deploy", "label": "x", "cwd": ".", "run": "y"}]}, "kind must be one of"),
    ({"commands": [{"kind": "check", "label": "x", "cwd": "..\\up", "run": "y"}]}, "cwd must be"),
    ({"builds_on": ["demo"]}, "must not list the workshop itself"),
])
def test_invalid_manifests_are_reported_not_loaded(tmp_path, overrides, expected):
    repo = make_repo(tmp_path, {"demo": manifest(**overrides)})
    registry = hub.load_registry(repo)
    assert registry.workshops == []
    assert registry.errors[0]["manifest"] == "workshops/demo/workshop.json"
    assert any(expected in e for e in registry.errors[0]["errors"]), registry.errors


def test_bad_json_and_unknown_dependency_do_not_hide_valid_workshops(tmp_path):
    repo = make_repo(tmp_path, {
        "good": manifest("good", order=2),
        "broken": "{not json",
        "orphan": manifest("orphan", builds_on=["nowhere"]),
    })
    registry = hub.load_registry(repo)
    assert [w["id"] for w in registry.workshops] == ["good"]
    messages = {e["manifest"]: " ".join(e["errors"]) for e in registry.errors}
    assert "cannot read JSON" in messages["workshops/broken/workshop.json"]
    assert "unknown workshop 'nowhere'" in messages["workshops/orphan/workshop.json"]


def test_folders_without_a_manifest_are_ignored(tmp_path):
    repo = make_repo(tmp_path, {"demo": manifest()})
    (repo / "workshops" / "scratch").mkdir()
    registry = hub.load_registry(repo)
    assert [w["id"] for w in registry.workshops] == ["demo"] and registry.errors == []


# ---- HTTP ----------------------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path):
    repo = make_repo(tmp_path / "repo", {
        "demo": manifest(readiness=[{"label": "venv", "path": "workshops/demo/.venv"},
                                    {"label": "readme", "path": "workshops/demo/README.md"}]),
        "next": manifest("next", order=2, builds_on=["demo"]),
    })
    (repo / "workshops" / "demo" / "secret.md").write_text("not declared", encoding="utf-8")
    token_file = tmp_path / "state" / "sidecar-auth" / "workshop-hub.token"
    srv = hub.make_server(hub.HubConfig(repo_root=repo, token_file=token_file), port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, token_file, repo
    srv.shutdown()
    srv.server_close()


def call(srv, path, token=TOKEN, method="GET"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    headers = {hub.TOKEN_HEADER: token} if token else {}
    conn.request(method, path, headers=headers)
    resp = conn.getresponse()
    body = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, body, resp


def provision(token_file: Path):
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(TOKEN, encoding="utf-8")


def test_binds_to_loopback(server):
    assert server[0].server_address[0] == "127.0.0.1"


def test_health_is_open_and_data_free(server):
    status, body, resp = call(server[0], "/health", token=None)
    assert status == 200 and body == {"ok": True, "extension": "workshop-hub"}
    assert resp.getheader("Access-Control-Allow-Origin") == "*"


def test_503_before_consent_then_401_on_bad_token(server):
    srv, token_file, _ = server
    assert call(srv, "/v1/workshops")[0] == 503
    provision(token_file)
    assert call(srv, "/v1/workshops", token=None)[0] == 401
    assert call(srv, "/v1/workshops", token="x" * 32)[0] == 401
    assert call(srv, "/v1/workshops")[0] == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_only_get_is_allowed(server, method):
    status, _, resp = call(server[0], "/v1/workshops", method=method)
    assert status == 405 and resp.getheader("Allow") == "GET"


def test_list_detail_and_readiness(server):
    srv, token_file, _ = server
    provision(token_file)
    status, body, _ = call(srv, "/v1/workshops")
    assert status == 200 and [w["id"] for w in body["workshops"]] == ["demo", "next"]
    assert "commands" not in body["workshops"][0]
    status, detail, _ = call(srv, "/v1/workshops/demo")
    assert status == 200 and detail["folder"] == "workshops/demo"
    assert {r["label"]: r["present"] for r in detail["readiness"]} == {"venv": False, "readme": True}
    assert detail["commands"][0]["run"] == "pytest -q"
    assert call(srv, "/v1/workshops/nope")[0] == 404


def test_new_manifest_appears_without_restart(server):
    srv, token_file, repo = server
    provision(token_file)
    make_repo(repo, {"late": manifest("late", order=9)})
    ids = [w["id"] for w in call(srv, "/v1/workshops")[1]["workshops"]]
    assert ids[-1] == "late"


def test_doc_serves_only_declared_paths(server):
    srv, token_file, _ = server
    provision(token_file)
    status, body, _ = call(srv, "/v1/workshops/demo/doc?path=README.md")
    assert status == 200 and body["markdown"] == "# demo\n" and body["title"] == "Start here"
    for bad in ("secret.md", "../next/README.md", "%2E%2E/next/README.md", "workshop.json", ""):
        assert call(srv, f"/v1/workshops/demo/doc?path={bad}")[0] == 404, bad
    assert call(srv, "/v1/workshops/demo/doc")[0] == 404


def test_oversized_doc_is_refused(server, monkeypatch):
    srv, token_file, _ = server
    provision(token_file)
    monkeypatch.setattr(hub, "MAX_DOC_BYTES", 3)
    assert call(srv, "/v1/workshops/demo/doc?path=README.md")[0] == 413


def test_token_file_lookup_matches_webui_order(tmp_path):
    assert hub.resolve_token_file({"HERMES_EXT_SIDECAR_TOKEN_FILE": str(tmp_path / "t")}) == tmp_path / "t"
    assert hub.resolve_token_file({"HERMES_WEBUI_STATE_DIR": str(tmp_path)}) == \
        tmp_path / "sidecar-auth" / "workshop-hub.token"
    assert hub.resolve_token_file({"HERMES_HOME": str(tmp_path)}) == \
        tmp_path / "webui" / "sidecar-auth" / "workshop-hub.token"
