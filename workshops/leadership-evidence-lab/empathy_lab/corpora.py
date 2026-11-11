"""Pinned public-data acquisition, task conversion, split checks, and prepared snapshots."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import tarfile
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ModelConfig, config_from_mapping
from .dataset import SPLITS, load_dataset
from .tasks import EMOTIONS, TASKS, TaskRecord, emotion_record, fictional_record, validate_records

WORKSHOP_ROOT = Path(__file__).resolve().parents[1]
ED_URL = "https://dl.fbaipublicfiles.com/parlai/empatheticdialogues/empatheticdialogues.tar.gz"
GO_ID = "google-research-datasets/go_emotions"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def workshop_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("data paths must be workshop-relative without parent traversal")
    resolved = (WORKSHOP_ROOT / path).resolve()
    if not resolved.is_relative_to(WORKSHOP_ROOT):
        raise ValueError("data path escapes the workshop")
    return resolved


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    task: str
    model: ModelConfig
    dataset: dict[str, Any]
    limits: dict[str, int | None]
    seed: int

    @property
    def data_spec(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "task": self.task,
            "dataset": self.dataset,
            "limits": self.limits,
            "seed": self.seed,
        }

    @property
    def prepared_dir(self) -> Path:
        return WORKSHOP_ROOT / "data" / "prepared" / canonical_hash(self.data_spec)[:16]

    def run_dir(self, run: str | None = None) -> Path:
        name = run if run is not None else self.name
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
            raise ValueError("run names must contain only letters, digits, hyphens, underscores")
        path = (WORKSHOP_ROOT / "artifacts" / "experiments" / name).resolve()
        if not path.is_relative_to(WORKSHOP_ROOT):
            raise ValueError("run directory escapes workshop")
        return path


def load_experiment(path: str | Path) -> ExperimentConfig:
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema", "name", "task", "model_profile", "dataset", "limits", "seed"}
    if (
        not isinstance(raw, dict)
        or set(raw) - (required | {"model_overrides"})
        or required - set(raw)
    ):
        raise ValueError("experiment requires schema/name/task/model_profile/dataset/limits/seed")
    if type(raw["schema"]) is not int or raw["schema"] != 1 or raw["task"] not in TASKS:
        raise ValueError("unsupported experiment schema or task")
    if type(raw["seed"]) is not int or raw["seed"] < 0:
        raise ValueError("seed must be a non-negative integer")
    limits = raw["limits"]
    if (
        not isinstance(limits, dict)
        or set(limits) != set(SPLITS)
        or any(
            value is not None and (type(value) is not int or value < 1) for value in limits.values()
        )
    ):
        raise ValueError("limits must specify positive integers or null for all three splits")
    dataset = raw["dataset"]
    if not isinstance(dataset, dict):
        raise TypeError("dataset must be an object")
    if raw["task"] == "fictional_empathy":
        if set(dataset) != {"path"} or not isinstance(dataset["path"], str):
            raise ValueError("fictional dataset requires its workshop-relative path")
        workshop_path(dataset["path"])
    else:
        length = 40 if raw["task"] == "go_emotions" else 64
        if (
            set(dataset) != {"revision"}
            or not isinstance(dataset["revision"], str)
            or not re.fullmatch(rf"[0-9a-f]{{{length}}}", dataset["revision"])
        ):
            raise ValueError(
                "public dataset revision must be an immutable commit or archive SHA256"
            )
    if not isinstance(raw["model_profile"], str) or Path(raw["model_profile"]).is_absolute():
        raise ValueError("model_profile must be relative to the experiment configuration")
    model_path = (path.parent / raw["model_profile"]).resolve()
    if not model_path.is_relative_to(WORKSHOP_ROOT):
        raise ValueError("model profile escapes workshop")
    model_raw = json.loads(model_path.read_text(encoding="utf-8"))
    overrides = raw.get("model_overrides", {})
    if not isinstance(overrides, dict):
        raise TypeError("model_overrides must be an object")
    config = ExperimentConfig(
        raw["name"],
        raw["task"],
        config_from_mapping({**model_raw, **overrides}),
        dataset,
        limits,
        raw["seed"],
    )
    config.run_dir()
    return config


def dialogue_records(
    stream: Iterable[dict[str, str]], split: str, *, audit: dict[str, int] | None = None
) -> list[TaskRecord]:
    conversations: dict[str, list[tuple[int, str]]] = {}
    for row in stream:
        if audit is not None:
            audit["input_rows"] = audit.get("input_rows", 0) + 1
            audit["rows_with_extra_metadata_columns"] = audit.get(
                "rows_with_extra_metadata_columns", 0
            ) + int(None in row)
        identifier = row.get("conv_id", "")
        utterance = row.get("utterance", "")
        try:
            index = int(row.get("utterance_idx", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("dialogue row requires an integer utterance index") from exc
        if (
            not isinstance(identifier, str)
            or not identifier.strip()
            or not isinstance(utterance, str)
            or not utterance.strip()
            or index < 1
        ):
            raise ValueError("dialogue row requires conversation ID and non-empty utterance")
        identifier = identifier.strip()
        conversations.setdefault(identifier, []).append((index, utterance.replace("_comma_", ",")))
    records = []
    for identifier, turns in conversations.items():
        turns.sort()
        if [index for index, _ in turns] != list(range(1, len(turns) + 1)):
            if audit is not None:
                audit["incomplete_conversations_dropped"] = (
                    audit.get("incomplete_conversations_dropped", 0) + 1
                )
                audit["incomplete_utterances_dropped"] = audit.get(
                    "incomplete_utterances_dropped", 0
                ) + len(turns)
                continue
            raise ValueError("dialogue utterance indices must be unique and contiguous from one")
        messages: list[dict[str, str]] = []
        for index, text in turns:
            if index % 2 == 0:
                records.append(
                    TaskRecord(
                        f"{identifier}:{index}",
                        identifier,
                        split,
                        list(messages),
                        text,
                    )
                )
            messages.append({"role": "user" if index % 2 else "assistant", "content": text})
    return records


def validate_shards(files: list[Path], split: str) -> None:
    parts = [re.fullmatch(rf"{split}-(\d+)-of-(\d+)\.parquet", path.name) for path in files]
    if not files or any(part is None for part in parts):
        raise ValueError("source requires a complete numbered Parquet shard set")
    totals = {int(part[2]) for part in parts}
    indices = {int(part[1]) for part in parts}
    if (
        len(totals) != 1
        or len(files) != next(iter(totals))
        or len(indices) != len(files)
        or min(indices) != 0
        or max(indices) != len(files) - 1
    ):
        raise ValueError("incomplete or inconsistent Parquet shards; acquire all files")


def validate_emotion_schema(path: Path) -> None:
    from pyarrow import parquet

    metadata = parquet.read_schema(path).metadata or {}
    try:
        features = json.loads(metadata[b"huggingface"])["info"]["features"]
        names = features["labels"]["feature"]["names"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("GoEmotions shard lacks label-index metadata") from exc
    if names != list(EMOTIONS):
        raise ValueError("GoEmotions label-index order does not match the task contract")


def _read_sources(config: ExperimentConfig, download: bool) -> tuple[list[TaskRecord], dict]:
    if config.task == "fictional_empathy":
        path = workshop_path(config.dataset["path"])
        return [fictional_record(item) for item in load_dataset(path)], {
            "source": config.dataset["path"],
            "files": {path.name: digest(path)},
            "license": "original fictional teaching fixtures",
        }
    if config.task == "go_emotions":
        from huggingface_hub import snapshot_download

        directory = WORKSHOP_ROOT / "data" / "external" / "go_emotions"
        directory = directory / config.dataset["revision"]
        if download:
            snapshot_download(
                GO_ID,
                repo_type="dataset",
                revision=config.dataset["revision"],
                local_dir=directory,
                allow_patterns=["simplified/*.parquet", "README.md"],
            )
        from pyarrow import parquet

        records = []
        hashes = {}
        for split in SPLITS:
            files = sorted((directory / "simplified").glob(f"{split}-*.parquet"))
            if not files:
                raise FileNotFoundError("GoEmotions files missing; run prepare with --download")
            validate_shards(files, split)
            for path in files:
                validate_emotion_schema(path)
                hashes[path.name] = digest(path)
                for row in parquet.read_table(path).to_pylist():
                    if not isinstance(row.get("id"), str) or not row["id"].strip():
                        raise ValueError("GoEmotions row requires a comment ID")
                    if not isinstance(row.get("text"), str) or not row["text"].strip():
                        raise ValueError("GoEmotions row requires non-empty text")
                    records.append(emotion_record(row["id"], split, row["text"], row["labels"]))
        return records, {
            "source": f"https://huggingface.co/datasets/{GO_ID}",
            "revision": config.dataset["revision"],
            "files": hashes,
            "license": "Apache-2.0",
            "label_names": list(EMOTIONS),
        }
    directory = WORKSHOP_ROOT / "data" / "external" / "empathetic_dialogues"
    archive = directory / "empatheticdialogues.tar.gz"
    if not archive.exists():
        if not download:
            raise FileNotFoundError("dialogue archive missing; run prepare with --download")
        directory.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix(".download")
        try:
            with (
                urllib.request.urlopen(ED_URL, timeout=60) as response,
                temporary.open("wb") as out,
            ):
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    out.write(chunk)
            if digest(temporary) != config.dataset["revision"]:
                raise ValueError("dialogue archive checksum mismatch")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if digest(archive) != config.dataset["revision"]:
        raise ValueError("dialogue archive checksum mismatch")
    records = []
    audits = {}
    with tarfile.open(archive, "r:gz") as handle:
        for split, filename in (
            ("train", "train.csv"),
            ("validation", "valid.csv"),
            ("test", "test.csv"),
        ):
            member = handle.getmember(f"empatheticdialogues/{filename}")
            if not member.isfile() or member.size > 256 * 1024 * 1024:
                raise ValueError("unexpected archive member type or size")
            with handle.extractfile(member) as binary:
                reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8"))
                audits[split] = {}
                records.extend(dialogue_records(reader, split, audit=audits[split]))
    return records, {
        "source": ED_URL,
        "files": {archive.name: digest(archive)},
        "license": "CC BY-NC 4.0",
        "dialogue_audit": audits,
    }


def deduplicate_splits(records: list[TaskRecord]) -> tuple[list[TaskRecord], dict[str, int]]:
    """Keep earlier train/validation/test ownership of identical normalized inputs."""
    seen: dict[str, str] = {}
    retained = []
    dropped = dict.fromkeys(SPLITS, 0)
    for split in SPLITS:
        for record in records:
            if record.split != split:
                continue
            fingerprint = canonical_hash(
                [
                    {"role": item["role"], "content": " ".join(item["content"].split()).casefold()}
                    for item in record.messages
                ]
            )
            previous = seen.setdefault(fingerprint, split)
            if previous != split:
                dropped[split] += 1
            else:
                retained.append(record)
    return retained, dropped


def prepare(config: ExperimentConfig, *, download: bool = False) -> dict[str, Any]:
    records, source = _read_sources(config, download)
    source_counts = validate_records(records, config.task)
    records, dropped = deduplicate_splits(records)
    admitted_counts = validate_records(records, config.task)
    selected = []
    for split in SPLITS:
        items = [item for item in records if item.split == split]
        limit = config.limits[split]
        if limit is not None and limit < len(items):
            items = random.Random(config.seed).sample(items, limit)
        selected.extend(sorted(items, key=lambda item: item.id))
    counts = validate_records(selected, config.task)
    directory = config.prepared_dir
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for split in SPLITS:
        path = directory / f"{split}.jsonl"
        content = "".join(
            json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
            for item in selected
            if item.split == split
        )
        path.write_text(content, encoding="utf-8")
        files[path.name] = digest(path)
    manifest = {
        "spec": config.data_spec,
        "source": source,
        "source_counts": source_counts,
        "dropped_cross_split_duplicate_inputs": dropped,
        "admitted_counts": admitted_counts,
        "selected_counts": counts,
        "files": files,
        "data_fingerprint": canonical_hash(files),
        "split_policy": "official groups; drop later split duplicate inputs, then seeded row sampling",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_prepared(
    config: ExperimentConfig, splits: tuple[str, ...] = SPLITS
) -> tuple[list[TaskRecord], dict[str, Any]]:
    directory = config.prepared_dir
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["spec"] != config.data_spec:
        raise ValueError("prepared data configuration mismatch; prepare a new snapshot")
    if canonical_hash(manifest["files"]) != manifest["data_fingerprint"]:
        raise ValueError("prepared manifest fingerprint mismatch")
    records = []
    for split in splits:
        if split not in SPLITS:
            raise ValueError("unknown requested split")
        path = directory / f"{split}.jsonl"
        if digest(path) != manifest["files"][path.name]:
            raise ValueError("prepared data checksum mismatch; do not train on modified snapshots")
        items = [
            TaskRecord(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        if any(item.split != split for item in items):
            raise ValueError("prepared split file contains records from another split")
        if len(items) != manifest["selected_counts"][split]:
            raise ValueError("prepared split count mismatch")
        records.extend(items)
    validate_records(records, config.task, require_all_splits=set(splits) == set(SPLITS))
    return records, manifest
