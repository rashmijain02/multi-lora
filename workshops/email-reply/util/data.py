"""Load, validate, and group two-field conversation/reply datasets."""

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .paths import (
    DATASET_FILENAME,
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_ROOT,
    ensure_unlinked_path,
    prepare_stage_dir,
)

SOURCE = DEFAULT_INPUT_DIR / DATASET_FILENAME
OUTPUT = DEFAULT_OUTPUT_ROOT / "sft"

THREAD_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd)(?:\[\d+\])?:\s*)+", re.IGNORECASE)
QUOTE_START = re.compile(
    r"(?im)^\s*(?:-{2,}\s*(?:original message|forwarded by).*|on .+ wrote:)\s*$"
)
HEADER = re.compile(r"(?im)^[ \t]*(from|to|cc|sent|subject|date):[ \t]*([^\r\n]*)")
ADDRESS = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)


@dataclass(frozen=True)
class ReplyPair:
    line: int
    conversation: str
    reply: str


def words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w@.-]+", text.casefold()))


def contains_text(text: tuple[str, ...], excerpt: tuple[str, ...]) -> bool:
    return bool(excerpt) and f" {' '.join(excerpt)} " in f" {' '.join(text)} "


def validate_pair_fields(
    row: object,
) -> tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]] | None, str | None]:
    if not isinstance(row, dict) or any(
        not isinstance(row.get(key), str) for key in ("conversation", "reply")
    ):
        return None, "malformed"
    conversation, reply = row["conversation"].strip(), row["reply"].strip()
    quoted, answer = words(conversation), words(reply)
    if not quoted or not answer:
        return None, "empty"
    if len(answer) >= 8 and contains_text(quoted, answer):
        return None, "target_in_conversation"
    return (conversation, reply, quoted, answer), None


def load_pairs(path: Path = SOURCE) -> tuple[list[ReplyPair], dict[str, int], str]:
    rows: list[ReplyPair] = []
    counts: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    with path.open("rb") as file:
        for line, raw in enumerate(file, 1):
            fingerprint.update(raw)
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                counts["malformed"] += 1
                continue
            validated, reason = validate_pair_fields(row)
            if reason is not None or validated is None:
                counts[reason or "malformed"] += 1
                continue
            conversation, reply, quoted, answer = validated
            if (quoted, answer) in seen:
                counts["duplicate"] += 1
            else:
                seen.add((quoted, answer))
                rows.append(ReplyPair(line, conversation, reply))
    if not rows:
        raise ValueError(f"No usable conversation/reply pairs: {dict(counts)}.")
    return rows, dict(counts), fingerprint.hexdigest()


def quoted_blocks(conversation: str) -> list[str]:
    return [chunk.strip() for chunk in QUOTE_START.split(conversation) if chunk.strip()]


def quote_text(block: str) -> tuple[str, ...]:
    block = HEADER.sub("", block)
    block = re.split(
        r"(?im)^[ \t]*(?:--[ \t]*$|confidentiality notice\b|this (?:e-mail|email) (?:and|is intended)\b)",
        block,
        maxsplit=1,
    )[0]
    return words(block)


def conversation_groups(rows: list[ReplyPair]) -> list[list[ReplyPair]]:
    parents = list(range(len(rows)))
    keys: dict[tuple, int] = {}
    reply_prefixes: dict[tuple[str, ...], list[tuple[int, tuple[str, ...]]]] = defaultdict(list)

    def root(index: int) -> int:
        while parents[index] != index:
            index, parents[index] = parents[index], parents[parents[index]]
        return index

    def connect(left: int, right: int) -> None:
        a, b = root(left), root(right)
        if a != b:
            parents[max(a, b)] = min(a, b)

    for i, row in enumerate(rows):
        answer = words(row.reply)
        if len(answer) >= 8:
            reply_prefixes[answer[:8]].append((i, answer))

    for i, row in enumerate(rows):
        for block in quoted_blocks(row.conversation):
            headers: dict[str, list[str]] = defaultdict(list)
            for name, value in HEADER.findall(block):
                headers[name.lower()].append(value)
            subjects = headers["subject"]
            participants = tuple(
                sorted(set(ADDRESS.findall(" ".join(headers["from"] + headers["to"]).casefold())))
            )
            if subjects and len(participants) >= 2:
                subject = words(THREAD_PREFIX.sub("", subjects[0]))
                if subject:
                    key = ("thread", subject, participants)
                    connect(i, keys.setdefault(key, i))
            quoted = quote_text(block)
            if len(quoted) >= 12:
                for start in range(len(quoted) - 11):
                    key = ("quote", quoted[start : start + 12])
                    connect(i, keys.setdefault(key, i))
            for start in range(len(quoted) - 7):
                for other, answer in reply_prefixes.get(quoted[start : start + 8], ()):
                    if quoted[start : start + len(answer)] == answer:
                        connect(i, other)

    groups: dict[int, list[ReplyPair]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[root(i)].append(row)
    return list(groups.values())


def split_pairs(rows: list[ReplyPair], seed: int = 42) -> dict[str, list[ReplyPair]]:
    groups = conversation_groups(rows)
    if len(groups) < 3:
        raise ValueError("At least three independent conversation groups are needed.")
    random.Random(seed).shuffle(groups)

    def take(target: int, reserve: int) -> list[ReplyPair]:
        selected: list[ReplyPair] = []
        i = 0
        while i < len(groups) and len(groups) > reserve:
            group = groups[i]
            remaining = target - len(selected)
            if len(group) <= remaining:
                selected.extend(groups.pop(i))
            else:
                i += 1
        if not selected:
            smallest = min(range(len(groups)), key=lambda index: len(groups[index]))
            selected = groups.pop(smallest)
        return selected

    holdout = take(max(1, round(len(rows) * 0.1)), 2)
    validation = take(max(1, round((len(rows) - len(holdout)) * 0.1)), 1)
    train = [row for group in groups for row in group]
    return {
        name: sorted(split, key=lambda row: row.line)
        for name, split in (("train", train), ("validation", validation), ("holdout", holdout))
    }


def private_output(output_root: Path | None = None) -> Path:
    if output_root is None:
        if OUTPUT.resolve() != OUTPUT:
            raise ValueError("Use the private output tree without symbolic links or junctions.")
        return prepare_stage_dir(OUTPUT.parent, OUTPUT.name)
    return prepare_stage_dir(output_root, "sft")


def _manifest_digest(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def save_split(path: Path, splits: dict[str, list[ReplyPair]], digest: str, seed: int) -> str:
    manifest = {
        "version": 1,
        "source_sha256": digest,
        "seed": seed,
        "splits": {key: [row.line for row in entries] for key, entries in splits.items()},
    }
    if path.resolve() != path.absolute():
        raise ValueError("Do not use a linked split manifest.")
    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError("Existing split manifest does not match this dataset and seed.") from None
    return _manifest_digest(manifest)


def load_frozen_split(
    path: Path,
    rows: list[ReplyPair],
    digest: str,
) -> tuple[dict[str, list[ReplyPair]], dict, str]:
    candidate = ensure_unlinked_path(path)
    if not candidate.is_file():
        raise ValueError(f"Split manifest does not exist: {candidate.name}")
    manifest = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Unsupported split manifest version.")
    if manifest.get("source_sha256") != digest:
        raise ValueError("Prepared dataset SHA-256 does not match the frozen split manifest.")
    raw_splits = manifest.get("splits")
    required = ("train", "validation", "holdout")
    if not isinstance(raw_splits, dict) or set(raw_splits) != set(required):
        raise ValueError("Frozen split manifest must define train, validation, and holdout partitions.")
    by_line = {row.line: row for row in rows}
    seen_lines: set[int] = set()
    resolved: dict[str, list[ReplyPair]] = {}
    for name in required:
        lines = raw_splits[name]
        if not isinstance(lines, list) or not lines or any(type(item) is not int for item in lines):
            raise ValueError(f"Frozen split partition '{name}' must contain valid line numbers.")
        line_set = set(lines)
        if len(line_set) != len(lines) or (seen_lines & line_set):
            raise ValueError("Frozen split partitions must not duplicate or overlap line numbers.")
        missing = line_set - set(by_line)
        if missing:
            raise ValueError("Frozen split manifest references lines absent from the dataset.")
        seen_lines |= line_set
        resolved[name] = [by_line[line] for line in sorted(lines)]
    if seen_lines != set(by_line):
        raise ValueError("Frozen split manifest does not cover the accepted dataset rows.")
    return resolved, manifest, _manifest_digest(manifest)
