"""Convert mail threads from documented formats into reply-conversations.jsonl."""

from __future__ import annotations

import argparse
import csv
import email
import email.policy
import email.utils
import json
import mailbox
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage, Message
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from util.data import DATASET_FILENAME, contains_text, validate_pair_fields, words
from util.paths import display_path, ensure_unlinked_path, restrict_directory

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2

SUPPORTED_FORMATS = ("eml", "mbox", "json", "text", "csv", "jsonl")
MESSAGE_DELIMITER_RE = re.compile(r"(?m)^===\s*MESSAGE\s*===\s*$")
ORIGINAL_MSG_RE = re.compile(
    r"(?im)^[ \t]*-{3,}[ \t]*Original Message[ \t]*-{3,}[ \t]*$"
)
UNDERSCORE_HEADER_RE = re.compile(
    r"(?im)^[ \t]*_{8,}[ \t]*\r?\nFrom:[ \t]+\S+"
)
ON_WROTE_RE = re.compile(r"(?im)^On .+ wrote:[ \t]*$")
HEADER_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$")
MSG_ID_TOKEN_RE = re.compile(r"<[^>]+>|[^\s<>]+")


@dataclass(frozen=True)
class NormalizedMessage:
    message_id: str
    in_reply_to: str | None
    references: tuple[str, ...]
    sender: str
    recipients: str
    cc: str
    subject: str
    timestamp_raw: str
    timestamp_epoch: float | None
    body: str
    thread_id: str | None = None
    is_target: bool = False


@dataclass(frozen=True)
class ConversionSummary:
    status: str
    exit_code: int
    source_format: str
    source_path: str
    output_path: str | None
    accepted: int
    rejected: int
    rejection_reasons: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "format": self.source_format,
            "source": self.source_path,
            "output": self.output_path,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


class ConversionAbortError(ValueError):
    """Raised when conversion cannot proceed and must exit with code 1."""


def parse_field_map(entries: list[str] | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in entries or []:
        if "=" not in entry:
            raise ConversionAbortError(
                f"Invalid --field-map entry {entry!r}; expected CANONICAL=SOURCE_COLUMN."
            )
        canonical, source_col = entry.split("=", 1)
        canonical = canonical.strip()
        source_col = source_col.strip()
        if not canonical or not source_col:
            raise ConversionAbortError(
                f"Invalid --field-map entry {entry!r}; both sides must be non-empty."
            )
        mapping[canonical] = source_col
    return mapping


def _normalize_msg_id(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    tokens = MSG_ID_TOKEN_RE.findall(stripped)
    if not tokens:
        return None
    tok = tokens[0].strip()
    return tok if tok else None


def _normalize_references(raw: object) -> tuple[str, ...]:
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            norm = _normalize_msg_id(item)
            if norm:
                out.append(norm)
        return tuple(out)
    if isinstance(raw, str) and raw.strip():
        return tuple(tok.strip() for tok in MSG_ID_TOKEN_RE.findall(raw) if tok.strip())
    return ()


def _parse_timestamp(raw: object) -> tuple[str, float | None]:
    if raw is None:
        return "", None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        dt = datetime.fromtimestamp(float(raw), tz=UTC)
        return dt.isoformat(), float(raw)
    if not isinstance(raw, str):
        return "", None
    text = raw.strip()
    if not text:
        return "", None
    try:
        iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return text, dt.timestamp()
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return text, dt.timestamp()
    except (TypeError, ValueError, IndexError):
        return text, None


def _truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "target"}
    return False


def split_authored_and_quoted(body: str) -> tuple[str, str, str | None]:
    """Return (authored_text, trailing_quoted_text, error_reason).

    Rejects bodies that start directly with quoted history or interleave unquoted
    paragraphs after a `>` quote block so ambiguous inline replies are never guessed.
    """
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return "", "", "empty_authored_reply"

    earliest_idx: int | None = None
    for pattern in (ORIGINAL_MSG_RE, UNDERSCORE_HEADER_RE):
        match = pattern.search(normalized)
        if match and (earliest_idx is None or match.start() < earliest_idx):
            earliest_idx = match.start()

    on_wrote = ON_WROTE_RE.search(normalized)
    if on_wrote:
        tail_after = normalized[on_wrote.end() :].lstrip("\n")
        if tail_after.startswith(">") and (earliest_idx is None or on_wrote.start() < earliest_idx):
            earliest_idx = on_wrote.start()

    head = normalized[:earliest_idx] if earliest_idx is not None else normalized
    quoted_tail = normalized[earliest_idx:] if earliest_idx is not None else ""

    lines = head.split("\n")
    first_quote_line: int | None = None
    seen_quote_block = False
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(">"):
            if first_quote_line is None:
                first_quote_line = idx
            seen_quote_block = True
        elif seen_quote_block and stripped:
            return "", "", "ambiguous_authored_reply"

    if first_quote_line is not None:
        authored = "\n".join(lines[:first_quote_line]).strip()
        extra_quote = "\n".join(lines[first_quote_line:])
        quoted_tail = f"{extra_quote}\n{quoted_tail}".strip() if quoted_tail else extra_quote
    else:
        authored = head.strip()

    if not authored:
        return "", quoted_tail, "ambiguous_authored_reply"
    return authored, quoted_tail, None


def render_context_message(msg: NormalizedMessage, authored_body: str) -> str:
    header_lines = ["-----Original Message-----"]
    if msg.sender:
        header_lines.append(f"From: {msg.sender}")
    if msg.timestamp_raw:
        header_lines.append(f"Sent: {msg.timestamp_raw}")
    if msg.recipients:
        header_lines.append(f"To: {msg.recipients}")
    if msg.cc:
        header_lines.append(f"Cc: {msg.cc}")
    header_lines.append(f"Subject: {msg.subject}")
    return "\n".join(header_lines) + "\n\n" + authored_body.strip()


def _sender_matches(msg_sender: str, target_sender: str) -> bool:
    needle = target_sender.strip().lower()
    if not needle:
        return False
    hay = msg_sender.strip().lower()
    _, addr = email.utils.parseaddr(msg_sender)
    return needle == hay or (bool(addr) and needle == addr.lower()) or needle in hay


def extract_pairs_from_messages(
    messages: list[NormalizedMessage],
    *,
    require_explicit_links: bool,
    target_ids: set[str],
    target_sender: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    """Build validated (conversation, reply) pairs from normalized message records."""
    if not messages:
        reasons["empty_source"] += 1
        return []

    by_id: dict[str, NormalizedMessage] = {}
    for msg in messages:
        if not msg.message_id:
            reasons["missing_message_id"] += 1
            continue
        if msg.message_id in by_id:
            reasons["duplicate_message_id"] += 1
            return []
        by_id[msg.message_id] = msg

    valid_messages = [m for m in messages if m.message_id in by_id]
    if not valid_messages:
        return []

    selected_targets: list[NormalizedMessage] = []
    if target_ids:
        for tid in sorted(target_ids):
            found = by_id.get(tid)
            if found is None:
                reasons["target_not_found"] += 1
            else:
                selected_targets.append(found)
    elif target_sender:
        selected_targets = [m for m in valid_messages if _sender_matches(m.sender, target_sender)]
        if not selected_targets:
            reasons["target_not_found"] += 1
            return []
    elif any(m.is_target for m in valid_messages):
        selected_targets = [m for m in valid_messages if m.is_target]
    elif target_selection == "latest":
        selected_targets = _select_latest_targets(
            valid_messages, by_id, require_explicit_links=require_explicit_links, reasons=reasons
        )
    else:
        reasons["missing_target_selection"] += 1
        return []

    pairs: list[tuple[str, str]] = []
    for target in selected_targets:
        authored_reply, _, err = split_authored_and_quoted(target.body)
        if err is not None:
            reasons[err] += 1
            continue

        ancestors, link_err = _resolve_context_chain(
            target,
            valid_messages,
            by_id,
            require_explicit_links=require_explicit_links,
        )
        if link_err is not None:
            reasons[link_err] += 1
            continue

        rendered_blocks: list[str] = []
        leak_detected = False
        reply_words = words(authored_reply)
        for anc in ancestors:
            anc_authored, _, anc_err = split_authored_and_quoted(anc.body)
            anc_text = anc_authored if anc_err is None else anc.body.strip()
            if not anc_text:
                leak_detected = True
                reasons["empty_context_message"] += 1
                break
            if len(reply_words) >= 4 and contains_text(words(anc_text), reply_words):
                leak_detected = True
                reasons["target_leak_in_context"] += 1
                break
            rendered_blocks.append(render_context_message(anc, anc_text))

        if leak_detected or not rendered_blocks:
            if not leak_detected and not rendered_blocks:
                reasons["missing_preceding_context"] += 1
            continue

        conversation = "\n\n".join(rendered_blocks)
        validated, val_err = validate_pair_fields({"conversation": conversation, "reply": authored_reply})
        if val_err is not None or validated is None:
            reasons[val_err or "invalid_pair"] += 1
            continue
        pairs.append((validated[0], validated[1]))

    return pairs


def _select_latest_targets(
    messages: list[NormalizedMessage],
    by_id: dict[str, NormalizedMessage],
    *,
    require_explicit_links: bool,
    reasons: Counter[str],
) -> list[NormalizedMessage]:
    groups: dict[str, list[NormalizedMessage]] = {}
    if any(m.thread_id for m in messages):
        for msg in messages:
            if not msg.thread_id:
                reasons["missing_thread_boundary"] += 1
                return []
            groups.setdefault(msg.thread_id, []).append(msg)
    elif require_explicit_links:
        parent_ids = {m.in_reply_to for m in messages if m.in_reply_to in by_id}
        leaves = [
            m
            for m in messages
            if m.message_id not in parent_ids and (m.in_reply_to or m.references)
        ]
        if len(leaves) != 1:
            reasons["ambiguous_target_selection"] += 1
            return []
        return leaves
    else:
        reasons["missing_target_selection"] += 1
        return []

    chosen: list[NormalizedMessage] = []
    for group_msgs in groups.values():
        parent_ids = {m.in_reply_to for m in group_msgs if m.in_reply_to}
        leaves = [m for m in group_msgs if m.message_id not in parent_ids]
        if len(leaves) == 1 and leaves[0].in_reply_to:
            chosen.append(leaves[0])
            continue
        if all(m.timestamp_epoch is not None for m in group_msgs) and len(group_msgs) >= 2:
            ordered = sorted(group_msgs, key=lambda m: float(m.timestamp_epoch or 0.0))
            if ordered[-1].timestamp_epoch == ordered[-2].timestamp_epoch:
                reasons["ambiguous_target_selection"] += 1
                continue
            chosen.append(ordered[-1])
        else:
            reasons["ambiguous_target_selection"] += 1
    return chosen


def _resolve_context_chain(
    target: NormalizedMessage,
    all_messages: list[NormalizedMessage],
    by_id: dict[str, NormalizedMessage],
    *,
    require_explicit_links: bool,
) -> tuple[list[NormalizedMessage], str | None]:
    """Return newest-first preceding context messages or an explicit rejection reason."""
    parent_id = target.in_reply_to or (target.references[-1] if target.references else None)
    if parent_id is not None:
        ancestors: list[NormalizedMessage] = []
        visited = {target.message_id}
        cur_id: str | None = parent_id
        child_epoch = target.timestamp_epoch
        while cur_id is not None:
            if cur_id in visited:
                return [], "reply_cycle"
            visited.add(cur_id)
            parent = by_id.get(cur_id)
            if parent is None:
                return [], "missing_parent_context"
            if (
                child_epoch is not None
                and parent.timestamp_epoch is not None
                and parent.timestamp_epoch > child_epoch
            ):
                return [], "later_context_timestamp"
            ancestors.append(parent)
            if parent.timestamp_epoch is not None:
                child_epoch = parent.timestamp_epoch
            cur_id = parent.in_reply_to or (parent.references[-1] if parent.references else None)
        return ancestors, None

    if require_explicit_links or not target.thread_id:
        return [], "missing_explicit_reply_link"

    same_thread = [m for m in all_messages if m.thread_id == target.thread_id]
    if len(same_thread) < 2:
        return [], "missing_preceding_context"
    if target.timestamp_epoch is None or any(m.timestamp_epoch is None for m in same_thread):
        return [], "missing_chronology_for_thread"

    preceding: list[NormalizedMessage] = []
    for msg in same_thread:
        if msg.message_id == target.message_id:
            continue
        assert msg.timestamp_epoch is not None
        if msg.timestamp_epoch == target.timestamp_epoch:
            return [], "ambiguous_timestamp_order"
        if msg.timestamp_epoch < target.timestamp_epoch:
            preceding.append(msg)

    if not preceding:
        return [], "missing_preceding_context"
    preceding.sort(key=lambda m: float(m.timestamp_epoch or 0.0), reverse=True)
    return preceding, None


def _extract_mime_plain_body(msg: Message) -> tuple[str | None, str | None]:
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            if disposition == "attachment" or part.get_filename():
                continue
            if part.get_content_type() != "text/plain":
                continue
            text = _decode_mime_part(part)
            if text and text.strip():
                parts.append(text)
        if not parts:
            return None, "missing_plain_body"
        return "\n\n".join(parts), None

    disposition = (msg.get_content_disposition() or "").lower()
    if disposition == "attachment" or msg.get_filename():
        return None, "attachment_only_message"
    if msg.get_content_type() != "text/plain":
        return None, "missing_plain_body"
    text = _decode_mime_part(msg)
    if not text or not text.strip():
        return None, "missing_plain_body"
    return text, None


def _decode_mime_part(part: Message) -> str:
    if isinstance(part, EmailMessage):
        content = part.get_content()
        if isinstance(content, str):
            return content
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    raw = part.get_payload()
    return raw if isinstance(raw, str) else ""


def _mime_to_normalized(
    msg: Message, fallback_id: str, reasons: Counter[str]
) -> NormalizedMessage | None:
    body, err = _extract_mime_plain_body(msg)
    if err is not None or body is None:
        reasons[err or "missing_plain_body"] += 1
        return None
    msg_id = _normalize_msg_id(msg.get("Message-ID"))
    if not msg_id:
        reasons["missing_message_id"] += 1
        return None
    in_reply_to = _normalize_msg_id(msg.get("In-Reply-To"))
    references = _normalize_references(msg.get("References"))
    ts_raw, ts_epoch = _parse_timestamp(msg.get("Date"))
    return NormalizedMessage(
        message_id=msg_id or fallback_id,
        in_reply_to=in_reply_to,
        references=references,
        sender=str(msg.get("From", "")).strip(),
        recipients=str(msg.get("To", "")).strip(),
        cc=str(msg.get("Cc", "")).strip(),
        subject=str(msg.get("Subject", "")).strip(),
        timestamp_raw=ts_raw,
        timestamp_epoch=ts_epoch,
        body=body,
    )


def load_eml_pairs(
    source: Path,
    *,
    target_ids: set[str],
    target_sender: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    files = (
        sorted(p for p in source.rglob("*.eml") if p.is_file())
        if source.is_dir()
        else [source]
    )
    if not files:
        reasons["empty_source"] += 1
        return []
    messages: list[NormalizedMessage] = []
    for idx, path in enumerate(files):
        raw_bytes = path.read_bytes().removeprefix(b"\xef\xbb\xbf")
        parsed = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        norm = _mime_to_normalized(parsed, f"eml-{idx}", reasons)
        if norm is not None:
            messages.append(norm)
    return extract_pairs_from_messages(
        messages,
        require_explicit_links=True,
        target_ids=target_ids,
        target_sender=target_sender,
        target_selection=target_selection,
        reasons=reasons,
    )


def load_mbox_pairs(
    source: Path,
    *,
    target_ids: set[str],
    target_sender: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    if source.is_dir():
        raise ConversionAbortError("--format mbox requires a mailbox file path, not a directory.")
    messages: list[NormalizedMessage] = []
    box = mailbox.mbox(
        source,
        factory=lambda f: email.message_from_bytes(
            f.read().removeprefix(b"\xef\xbb\xbf"), policy=email.policy.default
        ),
        create=False,
    )
    try:
        for idx, msg in enumerate(box):
            norm = _mime_to_normalized(msg, f"mbox-{idx}", reasons)
            if norm is not None:
                messages.append(norm)
    finally:
        box.close()
    return extract_pairs_from_messages(
        messages,
        require_explicit_links=True,
        target_ids=target_ids,
        target_sender=target_sender,
        target_selection=target_selection,
        reasons=reasons,
    )


def _map_get(
    record: dict[str, object], canonical: str, field_map: dict[str, str], default_key: str
) -> object:
    key = field_map.get(canonical, default_key)
    return record.get(key)


def _dict_to_normalized_message(
    record: object,
    *,
    field_map: dict[str, str],
    default_thread_id: str | None,
    target_flag_field: str | None,
    reasons: Counter[str],
) -> NormalizedMessage | None:
    if not isinstance(record, dict):
        reasons["malformed_message_record"] += 1
        return None
    msg_id_raw = _map_get(record, "message_id", field_map, "message_id")
    msg_id = _normalize_msg_id(str(msg_id_raw)) if msg_id_raw is not None else None
    if not msg_id:
        reasons["missing_message_id"] += 1
        return None
    body_raw = _map_get(record, "body", field_map, "body")
    if not isinstance(body_raw, str) or not body_raw.strip():
        reasons["empty_message_body"] += 1
        return None
    in_reply_raw = _map_get(record, "in_reply_to", field_map, "in_reply_to")
    in_reply_to = _normalize_msg_id(str(in_reply_raw)) if in_reply_raw is not None else None
    refs_raw = _map_get(record, "references", field_map, "references")
    references = _normalize_references(refs_raw)
    sender_raw = _map_get(record, "sender", field_map, "sender")
    recip_raw = _map_get(record, "recipients", field_map, "recipients")
    if isinstance(recip_raw, list):
        recipients = ", ".join(str(x) for x in recip_raw if str(x).strip())
    else:
        recipients = str(recip_raw or "").strip()
    cc_raw = _map_get(record, "cc", field_map, "cc")
    cc = ", ".join(str(x) for x in cc_raw) if isinstance(cc_raw, list) else str(cc_raw or "").strip()
    subj_raw = _map_get(record, "subject", field_map, "subject")
    ts_val = _map_get(record, "timestamp", field_map, "timestamp")
    ts_raw, ts_epoch = _parse_timestamp(ts_val)
    thread_val = _map_get(record, "thread_id", field_map, "thread_id")
    thread_id = (
        str(thread_val).strip()
        if thread_val is not None and str(thread_val).strip()
        else default_thread_id
    )
    flag_key = target_flag_field or field_map.get("is_target", "is_target")
    is_target = _truthy_flag(record.get(flag_key))
    return NormalizedMessage(
        message_id=msg_id,
        in_reply_to=in_reply_to,
        references=references,
        sender=str(sender_raw or "").strip(),
        recipients=recipients,
        cc=cc,
        subject=str(subj_raw or "").strip(),
        timestamp_raw=ts_raw,
        timestamp_epoch=ts_epoch,
        body=body_raw,
        thread_id=thread_id,
        is_target=is_target,
    )


def load_json_pairs(
    source: Path,
    *,
    field_map: dict[str, str],
    target_ids: set[str],
    target_sender: str | None,
    target_flag_field: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    files = sorted(p for p in source.rglob("*.json") if p.is_file()) if source.is_dir() else [source]
    if not files:
        reasons["empty_source"] += 1
        return []

    pairs: list[tuple[str, str]] = []
    threads_key = field_map.get("threads", "threads")
    messages_key = field_map.get("messages", "messages")
    target_id_key = field_map.get("target_message_id", "target_message_id")
    thread_id_key = field_map.get("thread_id", "thread_id")

    for file_idx, path in enumerate(files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            reasons["malformed_json"] += 1
            continue

        thread_objs: list[dict[str, object]] = []
        if isinstance(payload, dict) and isinstance(payload.get(threads_key), list):
            for item in payload[threads_key]:
                if isinstance(item, dict):
                    thread_objs.append(item)
                else:
                    reasons["malformed_thread_record"] += 1
        elif isinstance(payload, dict) and isinstance(payload.get(messages_key), list):
            thread_objs.append(payload)
        elif isinstance(payload, list):
            if all(isinstance(item, dict) and messages_key in item for item in payload) and payload:
                thread_objs.extend(item for item in payload if isinstance(item, dict))
            else:
                thread_objs.append(
                    {
                        thread_id_key: f"json-list-{file_idx}",
                        messages_key: payload,
                        "_unbounded_list": True,
                    }
                )
        else:
            raise ConversionAbortError(
                f"Unsupported structured JSON root in {display_path(path)}; expected an object with "
                f"'{threads_key}'/'{messages_key}' or a list of threads/messages."
            )

        for t_idx, thread_obj in enumerate(thread_objs):
            raw_msgs = thread_obj.get(messages_key)
            if not isinstance(raw_msgs, list):
                reasons["missing_messages_list"] += 1
                continue
            unbounded = bool(thread_obj.get("_unbounded_list"))
            explicit_tid_val = thread_obj.get(thread_id_key)
            default_tid = (
                None
                if unbounded
                else (
                    str(explicit_tid_val).strip()
                    if explicit_tid_val is not None
                    else f"thread-{file_idx}-{t_idx}"
                )
            )
            norm_msgs: list[NormalizedMessage] = []
            for raw_m in raw_msgs:
                nm = _dict_to_normalized_message(
                    raw_m,
                    field_map=field_map,
                    default_thread_id=default_tid,
                    target_flag_field=target_flag_field,
                    reasons=reasons,
                )
                if nm is not None:
                    norm_msgs.append(nm)

            local_targets = set(target_ids)
            embedded_target = thread_obj.get(target_id_key)
            if not local_targets and isinstance(embedded_target, str) and embedded_target.strip():
                norm_tid = _normalize_msg_id(embedded_target)
                if norm_tid:
                    local_targets.add(norm_tid)

            if norm_msgs:
                pairs.extend(
                    extract_pairs_from_messages(
                        norm_msgs,
                        require_explicit_links=unbounded,
                        target_ids=local_targets,
                        target_sender=target_sender,
                        target_selection=target_selection,
                        reasons=reasons,
                    )
                )
    return pairs


def _parse_delimited_text_thread(
    raw_text: str,
    *,
    default_thread_id: str,
    target_ids: set[str],
    target_sender: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    chunks = [chunk.strip("\r\n") for chunk in MESSAGE_DELIMITER_RE.split(raw_text)]
    if chunks and not chunks[0].strip():
        chunks = chunks[1:]
    if not chunks:
        reasons["empty_source"] += 1
        return []

    messages: list[NormalizedMessage] = []
    for chunk in chunks:
        lines = chunk.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        headers: dict[str, str] = {}
        body_start: int | None = None
        for idx, line in enumerate(lines):
            if not line.strip():
                body_start = idx + 1
                break
            match = HEADER_LINE_RE.match(line)
            if not match:
                reasons["malformed_delimited_header"] += 1
                body_start = None
                break
            headers[match.group(1).lower()] = match.group(2).strip()
        if body_start is None:
            if "malformed_delimited_header" not in reasons:
                reasons["malformed_delimited_header"] += 1
            continue
        body = "\n".join(lines[body_start:]).strip()
        msg_id = _normalize_msg_id(headers.get("message-id") or headers.get("id"))
        if not msg_id:
            reasons["missing_message_id"] += 1
            continue
        if not body:
            reasons["empty_message_body"] += 1
            continue
        ts_raw, ts_epoch = _parse_timestamp(headers.get("sent") or headers.get("date"))
        messages.append(
            NormalizedMessage(
                message_id=msg_id,
                in_reply_to=_normalize_msg_id(headers.get("in-reply-to")),
                references=_normalize_references(headers.get("references")),
                sender=headers.get("from", ""),
                recipients=headers.get("to", ""),
                cc=headers.get("cc", ""),
                subject=headers.get("subject", ""),
                timestamp_raw=ts_raw,
                timestamp_epoch=ts_epoch,
                body=body,
                thread_id=headers.get("thread-id", default_thread_id),
                is_target=_truthy_flag(headers.get("target") or headers.get("role")),
            )
        )

    if not messages:
        return []
    return extract_pairs_from_messages(
        messages,
        require_explicit_links=False,
        target_ids=target_ids,
        target_sender=target_sender,
        target_selection=target_selection,
        reasons=reasons,
    )


def _parse_quoted_reply_text(raw_text: str, reasons: Counter[str]) -> list[tuple[str, str]]:
    authored, quoted_tail, err = split_authored_and_quoted(raw_text)
    if err is not None:
        reasons[err] += 1
        return []
    if not quoted_tail.strip():
        reasons["missing_quoted_context_boundary"] += 1
        return []

    cleaned_context = quoted_tail.strip()
    if ON_WROTE_RE.match(cleaned_context):
        lines = cleaned_context.split("\n")
        header_line = lines[0].strip()
        unquoted = [
            line.lstrip()[1:].lstrip(" ") if line.lstrip().startswith(">") else line
            for line in lines[1:]
        ]
        body_text = "\n".join(unquoted).strip()
        if not body_text:
            reasons["missing_preceding_context"] += 1
            return []
        cleaned_context = f"-----Original Message-----\nFrom: {header_line}\n\n{body_text}"
    elif cleaned_context.lstrip().startswith(">"):
        reasons["ambiguous_thread_boundary"] += 1
        return []

    validated, val_err = validate_pair_fields({"conversation": cleaned_context, "reply": authored})
    if val_err is not None or validated is None:
        reasons[val_err or "invalid_pair"] += 1
        return []
    return [(validated[0], validated[1])]


def load_text_pairs(
    source: Path,
    *,
    text_contract: str,
    target_ids: set[str],
    target_sender: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    files = sorted(p for p in source.rglob("*.txt") if p.is_file()) if source.is_dir() else [source]
    if not files:
        reasons["empty_source"] += 1
        return []
    pairs: list[tuple[str, str]] = []
    for idx, path in enumerate(files):
        raw_text = path.read_text(encoding="utf-8-sig")
        has_delimiter = bool(MESSAGE_DELIMITER_RE.search(raw_text))
        chosen_contract = text_contract
        if chosen_contract == "auto":
            chosen_contract = "delimited" if has_delimiter else "quoted-reply"

        if chosen_contract == "delimited":
            if not has_delimiter:
                reasons["missing_message_delimiter"] += 1
                continue
            pairs.extend(
                _parse_delimited_text_thread(
                    raw_text,
                    default_thread_id=f"text-{idx}",
                    target_ids=target_ids,
                    target_sender=target_sender,
                    target_selection=target_selection,
                    reasons=reasons,
                )
            )
        elif chosen_contract == "quoted-reply":
            if has_delimiter:
                reasons["unexpected_delimited_input"] += 1
                continue
            pairs.extend(_parse_quoted_reply_text(raw_text, reasons))
        else:
            raise ConversionAbortError(f"Unsupported --text-contract value: {text_contract!r}")
    return pairs


def load_tabular_pairs(
    source: Path,
    *,
    source_format: str,
    mode: str,
    field_map: dict[str, str],
    target_ids: set[str],
    target_sender: str | None,
    target_flag_field: str | None,
    target_selection: str,
    reasons: Counter[str],
) -> list[tuple[str, str]]:
    if source.is_dir():
        raise ConversionAbortError(
            f"--format {source_format} requires a file path, not a directory."
        )

    rows: list[dict[str, object]] = []
    if source_format == "csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                reasons["empty_source"] += 1
                return []
            available_cols = set(reader.fieldnames)
            for row in reader:
                if None in row:
                    reasons["malformed_csv_row"] += 1
                    continue
                rows.append(dict(row))
    else:
        available_cols = set()
        with source.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    reasons["blank_line"] += 1
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    reasons["malformed_json"] += 1
                    continue
                if not isinstance(item, dict):
                    reasons["non_object_row"] += 1
                    continue
                available_cols.update(item.keys())
                rows.append(item)

    if not rows and not reasons:
        reasons["empty_source"] += 1
        return []

    conv_col = field_map.get("conversation", "conversation")
    reply_col = field_map.get("reply", "reply")
    msg_id_col = field_map.get("message_id", "message_id")
    body_col = field_map.get("body", "body")

    resolved_mode = mode
    if resolved_mode == "auto":
        has_paired = conv_col in available_cols and reply_col in available_cols
        has_messages = msg_id_col in available_cols and body_col in available_cols
        if has_paired and not has_messages:
            resolved_mode = "paired"
        elif has_messages and not has_paired:
            resolved_mode = "messages"
        elif has_paired and has_messages:
            raise ConversionAbortError(
                "Ambiguous tabular columns contain both paired and message fields; "
                "specify --mode paired or --mode messages explicitly."
            )
        else:
            raise ConversionAbortError(
                f"Missing required mapped columns in {display_path(source)}: expected paired "
                f"({conv_col!r}, {reply_col!r}) or message ({msg_id_col!r}, {body_col!r}) fields."
            )

    if resolved_mode == "paired":
        if rows and (conv_col not in available_cols or reply_col not in available_cols):
            raise ConversionAbortError(
                f"Paired mode requires columns {conv_col!r} and {reply_col!r} in "
                f"{display_path(source)}."
            )
        paired_out: list[tuple[str, str]] = []
        for row in rows:
            validated, err = validate_pair_fields(
                {"conversation": row.get(conv_col), "reply": row.get(reply_col)}
            )
            if err is not None or validated is None:
                reasons[err or "invalid_pair"] += 1
                continue
            paired_out.append((validated[0], validated[1]))
        return paired_out

    if resolved_mode == "messages":
        if rows and (msg_id_col not in available_cols or body_col not in available_cols):
            raise ConversionAbortError(
                f"Messages mode requires columns {msg_id_col!r} and {body_col!r} in "
                f"{display_path(source)}."
            )
        norm_msgs: list[NormalizedMessage] = []
        for row in rows:
            nm = _dict_to_normalized_message(
                row,
                field_map=field_map,
                default_thread_id=None,
                target_flag_field=target_flag_field,
                reasons=reasons,
            )
            if nm is not None:
                norm_msgs.append(nm)
        if not norm_msgs:
            return []
        has_explicit_threads = all(bool(m.thread_id) for m in norm_msgs)
        return extract_pairs_from_messages(
            norm_msgs,
            require_explicit_links=not has_explicit_threads,
            target_ids=target_ids,
            target_sender=target_sender,
            target_selection=target_selection,
            reasons=reasons,
        )

    raise ConversionAbortError(f"Unsupported --mode value: {mode!r}")


def _validate_paths(
    source_arg: str | Path, output_dir_arg: str | Path, *, cwd: Path
) -> tuple[Path, Path, Path]:
    src_candidate = Path(source_arg)
    if not src_candidate.is_absolute():
        src_candidate = cwd / src_candidate
    ensure_unlinked_path(src_candidate)
    source = src_candidate.resolve()
    if not source.exists():
        raise ConversionAbortError(f"Source path does not exist: {display_path(source)}")

    out_candidate = Path(output_dir_arg)
    if not out_candidate.is_absolute():
        out_candidate = cwd / out_candidate
    ensure_unlinked_path(out_candidate)
    out_dir = out_candidate.resolve()
    if out_dir.exists() and not out_dir.is_dir():
        raise ConversionAbortError(
            f"Destination --output-dir is not a directory: {display_path(out_dir)}"
        )

    dest_file = out_dir / DATASET_FILENAME
    ensure_unlinked_path(dest_file)
    if source == dest_file or source == out_dir:
        raise ConversionAbortError(
            f"Source and destination collide: {display_path(source)} vs {display_path(dest_file)}"
        )
    if source.is_dir() and (out_dir == source or source in out_dir.parents):
        raise ConversionAbortError(
            "Destination --output-dir must not be inside the source directory."
        )
    if dest_file.exists():
        raise ConversionAbortError(
            f"Refusing to overwrite existing dataset: {display_path(dest_file)}"
        )
    return source, out_dir, dest_file


def convert_threads(
    *,
    source_format: str,
    source_path: str | Path,
    output_dir: str | Path,
    mode: str = "auto",
    field_map: dict[str, str] | None = None,
    target_message_ids: list[str] | None = None,
    target_sender: str | None = None,
    target_flag_field: str | None = None,
    target_selection: str = "explicit",
    text_contract: str = "auto",
    cwd: Path | None = None,
) -> ConversionSummary:
    if source_format not in SUPPORTED_FORMATS:
        raise ConversionAbortError(f"Unsupported format: {source_format!r}")

    base_cwd = (cwd or Path.cwd()).resolve()
    source, out_dir, dest_file = _validate_paths(source_path, output_dir, cwd=base_cwd)
    fmap = field_map or {}
    target_ids: set[str] = set()
    for raw_id in target_message_ids or []:
        norm = _normalize_msg_id(raw_id)
        if norm:
            target_ids.add(norm)

    reasons: Counter[str] = Counter()
    if source_format == "eml":
        raw_pairs = load_eml_pairs(
            source,
            target_ids=target_ids,
            target_sender=target_sender,
            target_selection=target_selection,
            reasons=reasons,
        )
    elif source_format == "mbox":
        raw_pairs = load_mbox_pairs(
            source,
            target_ids=target_ids,
            target_sender=target_sender,
            target_selection=target_selection,
            reasons=reasons,
        )
    elif source_format == "json":
        raw_pairs = load_json_pairs(
            source,
            field_map=fmap,
            target_ids=target_ids,
            target_sender=target_sender,
            target_flag_field=target_flag_field,
            target_selection=target_selection,
            reasons=reasons,
        )
    elif source_format == "text":
        raw_pairs = load_text_pairs(
            source,
            text_contract=text_contract,
            target_ids=target_ids,
            target_sender=target_sender,
            target_selection=target_selection,
            reasons=reasons,
        )
    else:
        raw_pairs = load_tabular_pairs(
            source,
            source_format=source_format,
            mode=mode,
            field_map=fmap,
            target_ids=target_ids,
            target_sender=target_sender,
            target_flag_field=target_flag_field,
            target_selection=target_selection,
            reasons=reasons,
        )

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for conv, rep in raw_pairs:
        key = (words(conv), words(rep))
        if key in seen:
            reasons["duplicate_pair"] += 1
            continue
        seen.add(key)
        deduped.append((conv, rep))

    rejected_total = sum(reasons.values())
    if not deduped:
        return ConversionSummary(
            status="failed",
            exit_code=EXIT_FAILED,
            source_format=source_format,
            source_path=display_path(source),
            output_path=None,
            accepted=0,
            rejected=rejected_total,
            rejection_reasons=dict(reasons),
        )

    created_dir = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    restrict_directory(out_dir)
    tmp_file = out_dir / f".{DATASET_FILENAME}.{os.getpid()}.tmp"
    try:
        with tmp_file.open("x", encoding="utf-8") as handle:
            for conv, rep in deduped:
                handle.write(
                    json.dumps({"conversation": conv, "reply": rep}, ensure_ascii=False) + "\n"
                )
            handle.flush()
        if dest_file.exists():
            raise ConversionAbortError(
                f"Refusing to overwrite existing dataset: {display_path(dest_file)}"
            )
        tmp_file.replace(dest_file)
    except OSError as exc:
        tmp_file.unlink(missing_ok=True)
        if created_dir and not any(out_dir.iterdir()):
            out_dir.rmdir()
        raise ConversionAbortError(f"Failed writing prepared dataset: {exc}") from exc
    except Exception:
        tmp_file.unlink(missing_ok=True)
        raise

    exit_code = EXIT_PARTIAL if rejected_total > 0 else EXIT_OK
    status = "partial" if rejected_total > 0 else "ok"
    return ConversionSummary(
        status=status,
        exit_code=exit_code,
        source_format=source_format,
        source_path=display_path(source),
        output_path=display_path(dest_file),
        accepted=len(deduped),
        rejected=rejected_total,
        rejection_reasons=dict(reasons),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        dest="source_format",
        choices=SUPPORTED_FORMATS,
        required=True,
        help="Input mail-thread or paired-dataset format contract.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source file or directory to convert (left untouched).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Explicit destination directory where reply-conversations.jsonl will be created.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "paired", "messages"),
        default="auto",
        help="Tabular interpretation mode for csv/jsonl inputs.",
    )
    parser.add_argument(
        "--field-map",
        action="append",
        default=[],
        metavar="CANONICAL=SOURCE",
        help="Map canonical field names to source columns/keys (repeatable).",
    )
    parser.add_argument(
        "--target-message-id",
        action="append",
        default=[],
        help="Explicit Message-ID(s) to convert as target replies.",
    )
    parser.add_argument(
        "--target-sender",
        default=None,
        help="Select replies authored by this sender address or display name.",
    )
    parser.add_argument(
        "--target-flag-field",
        default=None,
        help="Boolean/flag field marking target reply messages in json/csv/jsonl.",
    )
    parser.add_argument(
        "--target-selection",
        choices=("explicit", "latest"),
        default="explicit",
        help="Require explicit target markers/IDs or select the unambiguous latest reply per thread.",
    )
    parser.add_argument(
        "--text-contract",
        choices=("auto", "delimited", "quoted-reply"),
        default="auto",
        help="Plain-text boundary contract for --format text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fmap = parse_field_map(args.field_map)
        summary = convert_threads(
            source_format=args.source_format,
            source_path=args.source,
            output_dir=args.output_dir,
            mode=args.mode,
            field_map=fmap,
            target_message_ids=args.target_message_id,
            target_sender=args.target_sender,
            target_flag_field=args.target_flag_field,
            target_selection=args.target_selection,
            text_contract=args.text_contract,
        )
    except ConversionAbortError as exc:
        error_payload = {
            "status": "error",
            "exit_code": EXIT_FAILED,
            "format": args.source_format,
            "error": str(exc),
        }
        print(json.dumps(error_payload, indent=2))
        return EXIT_FAILED

    print(json.dumps(summary.to_dict(), indent=2))
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
