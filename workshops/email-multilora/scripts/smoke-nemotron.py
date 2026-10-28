import json
import os
import urllib.request

base_url = os.environ.get("NEMOTRON_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    api_request = urllib.request.Request(
        base_url + path,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(api_request, timeout=180) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


request("/health")
models = request("/v1/models")
if not any(model["id"] == "nemotron-local" for model in models["data"]):
    raise SystemExit("FAIL: nemotron-local is not listed by /v1/models")

completion = request(
    "/v1/chat/completions",
    {
        "model": "nemotron-local",
        "messages": [
            {"role": "user", "content": "What is 2 + 2? Reply with only the number."}
        ],
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0,
        "max_tokens": 32,
    },
)
answer = completion["choices"][0]["message"]["content"]
if not answer or answer.strip() != "4":
    raise SystemExit(f"FAIL: expected '4', received {answer!r}")
print(json.dumps({
    "status": "ok",
    "base_url": base_url,
    "answer": answer,
    "usage": completion.get("usage"),
}, indent=2))