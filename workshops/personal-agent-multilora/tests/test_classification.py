"""Classification records: explicit unavailability, strict CLM health, multi-label C10."""

from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hermes_plugin.classification import (
    C10_DEFINITIONS,
    ClassifierSettings,
    c10_key,
    classify,
    lexical_features,
    lexical_scores,
)


class StubCLM:
    """Loopback stand-in for clm-serve with configurable health and answers."""

    def __init__(self, health: dict, answer_for):
        self.health, self.answer_for, self.requests = health, answer_for, []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, payload, headers=None):
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(stub.health)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append(body)
                answers = {name: {"type": "choice", **stub.answer_for(name, q)}
                           for name, q in body["questions"].items()}
                self._send({"model": body["model"], "answers": answers},
                           {"X-CLM-Latency-Ms": "12.5"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


HEALTHY = {"ok": True, "embedder": True, "models": ["clm-latest"]}


def yes(p):
    return {"choice": "yes" if p >= 0.5 else "no", "confidence": max(p, 1 - p),
            "probabilities": {"yes": p, "no": 1 - p}}


@pytest.fixture
def stub(request):
    health, answer_for = request.param
    server = StubCLM(health, answer_for)
    yield server
    server.close()


def clm_settings(stub, **extra):
    return ClassifierSettings(backend="clm", clm_url=stub.url, **extra)


def test_no_backend_is_explicitly_unavailable():
    record = classify("C10", "s", "b", ClassifierSettings())
    assert record["status"] == "unavailable" and record["labels"] is None
    assert record["real_backend"] is False


def test_unreachable_clm_is_unavailable():
    record = classify("C6", "s", "b", ClassifierSettings(backend="clm",
                                                         clm_url="http://127.0.0.1:9"))
    assert record["status"] == "unavailable" and "unreachable" in record["error"]


PICKS = {"finance_bills": 0.9, "reminders": 0.55}


@pytest.mark.parametrize("stub", [
    ({**HEALTHY, "mock": True}, lambda n, q: yes(0.5)),
    ({**HEALTHY, "embedder": False}, lambda n, q: yes(0.5)),
    ({**HEALTHY, "models": ["other"]}, lambda n, q: yes(0.5)),
], indirect=True)
def test_unhealthy_or_mock_server_is_rejected(stub):
    record = classify("C10", "s", "b", clm_settings(stub))
    assert record["status"] == "unavailable"
    assert stub.requests == []  # rejected at health, before any content is sent


@pytest.mark.parametrize("stub", [
    ({**HEALTHY, "mock": True}, lambda n, q: yes(PICKS.get(n, 0.1))),
], indirect=True)
def test_mock_only_with_explicit_opt_in_and_flagged(stub):
    record = classify("C10", "s", "b", clm_settings(stub, allow_mock=True))
    assert record["status"] == "ok" and record["real_backend"] is False


@pytest.mark.parametrize("stub", [(HEALTHY, lambda n, q: yes(PICKS.get(n, 0.1)))],
                         indirect=True)
def test_c10_keeps_every_positive_label(stub):
    record = classify("C10", "Invoice due", "Please pay by Friday.", clm_settings(stub))
    assert record["status"] == "ok" and record["real_backend"] is True
    assert record["labels"] == ["Finance & Bills", "Reminders"]
    assert record["uncertain_labels"] == ["Reminders"]          # 0.55 is within 0.1 of 0.5
    assert record["review_state"] == "needs_review"
    assert record["latency_ms"] == 12.5
    sent = stub.requests[0]
    assert set(sent["questions"]) == {c10_key(label) for label in C10_DEFINITIONS}
    assert sent["state"] == {"subject": "Invoice due", "body": "Please pay by Friday."}


@pytest.mark.parametrize("stub", [(HEALTHY, lambda n, q: yes(0.05))], indirect=True)
def test_c10_empty_prediction_is_reported(stub):
    record = classify("C10", "s", "b", clm_settings(stub))
    assert record["labels"] == [] and record["empty_prediction"] is True
    assert record["review_state"] == "needs_review"


def c6_answer(top, p):
    def answer(name, q):
        others = [k for k in q["criteria"] if k != top]
        probs = {top: p, **{k: (1 - p) / len(others) for k in others}}
        return {"choice": top, "confidence": p, "probabilities": probs}
    return answer


@pytest.mark.parametrize("stub", [(HEALTHY, c6_answer("verify_code", 0.8))], indirect=True)
def test_c6_confident_label(stub):
    record = classify("C6", "Your code", "123456", clm_settings(stub))
    assert (record["label"], record["abstained"]) == ("verify_code", False)


@pytest.mark.parametrize("stub", [(HEALTHY, c6_answer("spam", 0.3))], indirect=True)
def test_c6_abstains_below_threshold(stub):
    record = classify("C6", "s", "b", clm_settings(stub))
    assert record["label"] is None and record["abstained"] is True
    assert record["top2"][0] == "spam"


@pytest.mark.parametrize("stub", [
    (HEALTHY, lambda n, q: {"choice": "yes", "confidence": 1,
                            "probabilities": {"yes": 0.9, "no": 0.9}}),
    (HEALTHY, lambda n, q: {"choice": "yes", "confidence": 1,
                            "probabilities": {"yes": 1.5, "no": -0.5}}),
    (HEALTHY, lambda n, q: {"choice": "yes", "confidence": 1, "probabilities": {"yes": 1.0}}),
], indirect=True)
def test_invalid_distributions_are_unavailable_not_guessed(stub):
    record = classify("C10", "s", "b", clm_settings(stub))
    assert record["status"] == "unavailable"


def test_lexical_scores_match_sklearn(tmp_path):
    np = pytest.importorskip("numpy")
    text_mod = pytest.importorskip("sklearn.feature_extraction.text")
    from sklearn.linear_model import LogisticRegression

    docs = [
        ("Invoice 4471", "Please pay the invoice by Friday."),
        ("Flight booked", "Your flight to Austin is confirmed."),
        ("Invoice overdue", "Reminder: invoice payment is overdue."),
        ("Hotel booking", "Your hotel reservation for Austin."),
        ("Team sync", "Agenda for the project meeting."),
        ("Pay invoice", "The vendor invoice needs approval."),
    ]
    y = np.array([1, 0, 1, 0, 0, 1])
    vectorizer = text_mod.TfidfVectorizer(lowercase=True, token_pattern=r"[a-z0-9]+",
                                          ngram_range=(1, 2), sublinear_tf=True, norm="l2")
    x = vectorizer.fit_transform([f"{s}\n{b}" for s, b in docs])
    model = LogisticRegression(C=4.0, max_iter=2000).fit(x, y)
    artifact = {
        "labels": ["Finance & Bills"],
        "vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()},
        "idf": [float(v) for v in vectorizer.idf_],
        "coef": [[float(c) for c in model.coef_[0]]],
        "intercept": [float(model.intercept_[0])],
    }
    assert set(vectorizer.build_analyzer()("Pay the invoice")) == \
        set(lexical_features("Pay the invoice"))
    probe = ("Invoice invoice reminder", "pay pay the vendor")
    expected = model.predict_proba(vectorizer.transform([f"{probe[0]}\n{probe[1]}"]))[0, 1]
    assert math.isclose(lexical_scores(artifact, *probe)["Finance & Bills"], expected,
                        abs_tol=1e-9)
