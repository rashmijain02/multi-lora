from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import requests

from email_workshop.data import ADAPTERS, DOMAINS, allowed_labels, write_json
from email_workshop.training import prompt_ids, verify_adapters


def vllm_command(root: Path, linux_run_root: str) -> list[str]:
    manifests = verify_adapters(root)
    config = manifests["generalist"]["config"]
    linux_path = PurePosixPath(linux_run_root)
    if (
        not linux_run_root
        or linux_path.is_absolute()
        or "\\" in linux_run_root
        or ":" in linux_run_root
        or ".." in linux_path.parts
    ):
        raise ValueError(
            "linux_run_root must be a relative POSIX path within the Linux/WSL workshop directory."
        )
    return [
        "vllm",
        "serve",
        config["model_id"],
        "--revision",
        config["model_revision"],
        "--served-model-name",
        "email-base",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--enable-lora",
        "--max-loras",
        "4",
        "--max-lora-rank",
        str(config["rank"]),
        "--max-model-len",
        str(config["max_length"]),
        "--gpu-memory-utilization",
        "0.75",
        "--lora-modules",
        *[f"{name}={PurePosixPath(linux_run_root) / 'adapters' / name}" for name in ADAPTERS],
    ]


class VllmBackend:
    def __init__(self, root: Path, base_url: str = "http://127.0.0.1:8000/v1"):
        from transformers import AutoTokenizer

        manifests = verify_adapters(root)
        parsed = urlparse(base_url)
        if (
            parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"
        ):
            raise ValueError("This workshop only sends email text to a local vLLM endpoint.")
        self.base_url = base_url.rstrip("/")
        self.tokenizer = AutoTokenizer.from_pretrained(root / "adapters" / "generalist")
        self.prompt_budget = manifests["generalist"]["config"]["max_length"] - 128
        self.headers = {"Content-Type": "application/json"}
        if key := os.getenv("VLLM_API_KEY"):
            self.headers["Authorization"] = f"Bearer {key}"
        self.identity = {
            "backend": "local-vllm",
            "url": self.base_url,
            "adapters": manifests,
            "generation": {"max_tokens": 128, "temperature": 0},
        }
        response = requests.get(f"{self.base_url}/models", headers=self.headers, timeout=10)
        response.raise_for_status()
        ids = {model["id"] for model in response.json()["data"]}
        required = {"email-base", *ADAPTERS}
        if missing := required - ids:
            raise RuntimeError(f"vLLM is missing model/adapter IDs: {sorted(missing)}")
        runtime = requests.get(f"{self.base_url[:-3]}/version", headers=self.headers, timeout=10)
        runtime.raise_for_status()
        self.identity["server_version"] = runtime.json()["version"]

    def generate(self, subject: str, body: str, adapter: str) -> str:
        response = requests.post(
            f"{self.base_url}/completions",
            headers=self.headers,
            json={
                "model": "email-base" if adapter == "base" else adapter,
                "prompt": prompt_ids(
                    self.tokenizer, subject, body, allowed_labels(adapter), self.prompt_budget
                ),
                "temperature": 0,
                "max_tokens": 128,
            },
            timeout=180,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["text"]
        if not isinstance(content, str):
            raise TypeError("Endpoint returned no text content.")
        return content


def concurrent_demo(backend: VllmBackend, output: Path) -> list[dict[str, Any]]:
    from email_workshop.evaluation import parse_labels

    examples = [
        ("operations", "Project review", "Please attend tomorrow's team project review."),
        ("finance", "Invoice due", "Please pay the attached invoice by Friday."),
        ("travel", "Flight confirmation", "Your flight and hotel bookings are confirmed."),
    ]

    def request(item: tuple[str, str, str]) -> dict[str, Any]:
        adapter, subject, body = item
        text = backend.generate(subject, body, adapter)
        return {"adapter": adapter, "predicted": parse_labels(text, DOMAINS[adapter])}

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(request, examples))
    write_json(
        output,
        {
            "kind": "concurrent synthetic smoke; not proof of same-batch scheduling",
            "results": results,
        },
    )
    return results
