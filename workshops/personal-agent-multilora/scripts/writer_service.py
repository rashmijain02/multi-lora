"""Loopback writer service: one base model plus the persona's LoRA adapter.

Run it from ``workshops/email-multilora`` so the email workshop package and its training
dependencies are available (repository-relative command):

    cd workshops/email-multilora
    uv run --extra training --with fastapi --with uvicorn \
        python ../personal-agent-multilora/scripts/writer_service.py --backend peft --device cuda

``--backend vllm`` forwards to a vLLM OpenAI server started with ``--enable-lora`` (one
``--lora-modules`` entry per persona adapter), which is the DGX Spark path.

Contract: ``POST /v1/draft`` with ``client_id, adapter, subject, body, brief[]`` returns
``text, client_id, adapter, base_model, base_revision, adapter_revision, adapted``. The
service rejects an adapter that does not match the persona registry and binds to 127.0.0.1.
It has no tools, memory, or approval power.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any

PD_ROOT = Path(__file__).resolve().parents[1]
EMAIL_ROOT = PD_ROOT.parent / "email-multilora"
sys.path.insert(0, str(EMAIL_ROOT))


def compose_body(body: str, brief: list[str]) -> str:
    """Append verified facts so the adapter can phrase them; it must not add new claims."""
    if not brief:
        return body
    facts = "\n".join(f"- {item}" for item in brief)
    return f"{body}\n\nVERIFIED FACTS FOR THE REPLY (do not add other commitments)\n{facts}"


def create_app(args: argparse.Namespace):
    from email_workshop.persona import (
        load_persona_dataset,
        load_persona_registry,
        persona_messages,
        verify_persona_adapter,
    )
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field

    run_root = (EMAIL_ROOT / args.run_root).resolve()
    registry = load_persona_registry(EMAIL_ROOT)
    backends: dict[str, Any] = {}
    lock = threading.Lock()  # one generation at a time: the GPU is the shared resource

    class DraftRequest(BaseModel):
        client_id: str = Field(max_length=64)
        adapter: str = Field(max_length=64)
        subject: str = Field(max_length=1000)
        body: str = Field(max_length=20000)
        brief: list[str] = Field(default_factory=list, max_length=20)

    app = FastAPI(title="PersonaDesk writer", version="0.1.0")

    def manifest_for(client_id: str) -> dict[str, Any]:
        return verify_persona_adapter(run_root, EMAIL_ROOT, client_id)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "backend": args.backend, "loaded": sorted(backends)}

    @app.post("/v1/draft")
    def draft(req: DraftRequest) -> dict[str, Any]:
        spec = registry.get(req.client_id)
        if spec is None or spec["adapter"] != req.adapter:
            raise HTTPException(403, "Adapter does not match the persona registry.")
        try:
            manifest = manifest_for(req.client_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(503, f"Adapter not verified: {exc}") from exc
        config = manifest["config"]
        body = compose_body(req.body, [b[:400] for b in req.brief])
        with lock:
            if args.backend == "peft":
                from email_workshop.persona import PersonaBackend

                if req.client_id not in backends:
                    backends.clear()  # keep one persona resident on small GPUs
                    backends[req.client_id] = PersonaBackend(
                        run_root, EMAIL_ROOT, req.client_id, device=args.device
                    )
                text = backends[req.client_id].generate(req.subject, body, adapted=True)
            else:
                import requests

                _, _, profile, _ = load_persona_dataset(EMAIL_ROOT, req.client_id)
                response = requests.post(
                    f"{args.vllm_url.rstrip('/')}/v1/chat/completions",
                    json={"model": req.adapter,
                          "messages": persona_messages(spec, profile, req.subject, body),
                          "temperature": 0, "max_tokens": 256},
                    timeout=120,
                )
                if response.status_code != 200:
                    raise HTTPException(502, f"vLLM error {response.status_code}")
                text = response.json()["choices"][0]["message"]["content"]
        files = manifest.get("files", {})
        revision = hashlib.sha256(repr(sorted(files.items())).encode()).hexdigest()[:16]
        return {
            "text": text.strip(),
            "client_id": req.client_id,
            "adapter": req.adapter,
            "base_model": config["model_id"],
            "base_revision": config["model_revision"],
            "adapter_revision": revision,
            "adapted": True,
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backend", choices=["peft", "vllm"], default="peft")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--run-root", default=os.getenv("EMAIL_PERSONA_RUN",
                                                        "artifacts/persona-lora-run-2026"),
                        help="Persona run root, relative to workshops/email-multilora")
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    if Path(args.run_root).is_absolute() or ".." in Path(args.run_root).parts:
        parser.error("--run-root must be relative to workshops/email-multilora")
    import uvicorn

    uvicorn.run(create_app(args), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
