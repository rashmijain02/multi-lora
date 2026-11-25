import contextlib
import csv
import hashlib
import io
import json
import mailbox
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from tools import prepare_input
from util.data import load_pairs
from util.paths import resolve_input_dir


def _build_eml(
    *,
    msg_id: str,
    sender: str,
    to: str,
    subject: str,
    date: str,
    body: str,
    in_reply_to: str | None = None,
    attachment_text: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Message-ID"] = msg_id
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = date
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg.set_content(body)
    if attachment_text is not None:
        msg.add_attachment(
            attachment_text.encode("utf-8"),
            maintype="text",
            subtype="plain",
            filename="secret-attachment.txt",
        )
    return msg


class PrepareInputTests(unittest.TestCase):
    def test_all_five_formats_produce_shared_loader_compatible_datasets(self):
        with tempfile.TemporaryDirectory() as tmp, patch("tools.prepare_input.restrict_directory"):
            root = Path(tmp)

            # 1. EML directory with attachment exclusion and stripped quoted tail
            eml_src = root / "eml_src"
            eml_src.mkdir()
            m1 = _build_eml(
                msg_id="<m1@example.test>",
                sender="Alice <alice@example.test>",
                to="Bob <bob@example.test>",
                subject="Q3 forecast",
                date="Mon, 01 Oct 2024 09:00:00 +0000",
                body="Can you confirm the Q3 forecast deadline?",
                attachment_text="DO_NOT_INCLUDE_ATTACHMENT_TOKEN",
            )
            m2 = _build_eml(
                msg_id="<m2@example.test>",
                sender="Bob <bob@example.test>",
                to="Alice <alice@example.test>",
                subject="Re: Q3 forecast",
                date="Mon, 01 Oct 2024 09:30:00 +0000",
                in_reply_to="<m1@example.test>",
                body=(
                    "Friday at 4 PM Central.\n\n"
                    "-----Original Message-----\n"
                    "From: Alice\n"
                    "Can you confirm the Q3 forecast deadline?"
                ),
            )
            (eml_src / "01.eml").write_bytes(m1.as_bytes())
            (eml_src / "02.eml").write_bytes(m2.as_bytes())
            eml_out = root / "out_eml"
            res_eml = prepare_input.convert_threads(
                source_format="eml",
                source_path=eml_src,
                output_dir=eml_out,
                target_message_ids=["<m2@example.test>"],
            )
            self.assertEqual(res_eml.exit_code, 0)
            pairs_eml, bad_eml, _ = load_pairs(eml_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_eml), 1)
            self.assertEqual(sum(bad_eml.values()), 0)
            self.assertEqual(pairs_eml[0].reply, "Friday at 4 PM Central.")
            self.assertNotIn("DO_NOT_INCLUDE_ATTACHMENT_TOKEN", pairs_eml[0].conversation)

            # 2. MBOX with 3 messages + later forward excluded
            mbox_path = root / "threads.mbox"
            box = mailbox.mbox(mbox_path)
            m3 = _build_eml(
                msg_id="<m3@example.test>",
                sender="Carol <carol@example.test>",
                to="Team <team@example.test>",
                subject="Fwd: Q3 forecast",
                date="Mon, 01 Oct 2024 11:00:00 +0000",
                in_reply_to="<m2@example.test>",
                body="FYI: Bob confirmed Friday at 4 PM Central.",
            )
            box.add(m1)
            box.add(m2)
            box.add(m3)
            box.flush()
            box.close()
            mbox_out = root / "out_mbox"
            res_mbox = prepare_input.convert_threads(
                source_format="mbox",
                source_path=mbox_path,
                output_dir=mbox_out,
                target_message_ids=["<m2@example.test>"],
            )
            self.assertEqual(res_mbox.exit_code, 0)
            pairs_mbox, _, _ = load_pairs(mbox_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_mbox), 1)
            self.assertNotIn("FYI: Bob confirmed", pairs_mbox[0].conversation)

            # 3. Structured JSON with custom field mapping and newest-first ancestor ordering
            json_path = root / "threads.json"
            json_payload = {
                "items": [
                    {
                        "tid": "t-100",
                        "chosen_id": "msg-3",
                        "posts": [
                            {
                                "id": "msg-1",
                                "author": "ops@example.test",
                                "sent_at": "2024-10-02T08:00:00Z",
                                "subj": "Maintenance window",
                                "content": "Initial proposal is Saturday 02:00 UTC.",
                            },
                            {
                                "id": "msg-2",
                                "parent": "msg-1",
                                "author": "lead@example.test",
                                "sent_at": "2024-10-02T08:15:00Z",
                                "subj": "Re: Maintenance window",
                                "content": "Does database failover finish within 30 minutes?",
                            },
                            {
                                "id": "msg-3",
                                "parent": "msg-2",
                                "author": "ops@example.test",
                                "sent_at": "2024-10-02T08:30:00Z",
                                "subj": "Re: Maintenance window",
                                "content": "Yes, dry-run failover completed in 14 minutes.",
                            },
                        ],
                    }
                ]
            }
            json_path.write_text(json.dumps(json_payload), encoding="utf-8")
            json_out = root / "out_json"
            res_json = prepare_input.convert_threads(
                source_format="json",
                source_path=json_path,
                output_dir=json_out,
                field_map={
                    "threads": "items",
                    "thread_id": "tid",
                    "target_message_id": "chosen_id",
                    "messages": "posts",
                    "message_id": "id",
                    "in_reply_to": "parent",
                    "sender": "author",
                    "timestamp": "sent_at",
                    "subject": "subj",
                    "body": "content",
                },
            )
            self.assertEqual(res_json.exit_code, 0)
            pairs_json, _, _ = load_pairs(json_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_json), 1)
            conv_json = pairs_json[0].conversation
            self.assertLess(
                conv_json.index("failover finish within 30 minutes"),
                conv_json.index("Initial proposal is Saturday"),
            )

            # 4. Plain/quoted text (both delimited and quoted-reply files)
            txt_dir = root / "txt_src"
            txt_dir.mkdir()
            (txt_dir / "delimited.txt").write_text(
                "=== MESSAGE ===\n"
                "Message-ID: <t1@example.test>\n"
                "From: Dana <dana@example.test>\n"
                "Sent: 2024-10-03T10:00:00Z\n"
                "Subject: Vendor contract\n\n"
                "Please confirm whether legal approved clause 4.\n"
                "=== MESSAGE ===\n"
                "Message-ID: <t2@example.test>\n"
                "In-Reply-To: <t1@example.test>\n"
                "From: Eli <eli@example.test>\n"
                "Sent: 2024-10-03T10:20:00Z\n"
                "Subject: Re: Vendor contract\n"
                "Target: true\n\n"
                "Legal approved clause 4 without redlines.\n",
                encoding="utf-8",
            )
            (txt_dir / "quoted.txt").write_text(
                "We can host the review in Room 402.\n\n"
                "On Thu, Oct 3, 2024 at 11:00 AM Sam wrote:\n"
                "> Which conference room is free for the design review?\n",
                encoding="utf-8",
            )
            txt_out = root / "out_txt"
            res_txt = prepare_input.convert_threads(
                source_format="text",
                source_path=txt_dir,
                output_dir=txt_out,
            )
            self.assertEqual(res_txt.exit_code, 0)
            pairs_txt, _, _ = load_pairs(txt_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_txt), 2)

            # 5. CSV (paired mapped columns) and JSONL (message rows)
            csv_path = root / "paired.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["thread_context", "draft_reply"])
                writer.writeheader()
                writer.writerow(
                    {
                        "thread_context": "-----Original Message-----\nFrom: Pat\nSubject: Invoice\n\nDid invoice 884 clear?",
                        "draft_reply": "Invoice 884 cleared this morning.",
                    }
                )
            csv_out = root / "out_csv"
            res_csv = prepare_input.convert_threads(
                source_format="csv",
                source_path=csv_path,
                output_dir=csv_out,
                field_map={"conversation": "thread_context", "reply": "draft_reply"},
            )
            self.assertEqual(res_csv.exit_code, 0)
            pairs_csv, _, _ = load_pairs(csv_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_csv), 1)
            resolved_dir, _ = resolve_input_dir(csv_out)
            self.assertEqual(resolved_dir, csv_out.resolve())

            jsonl_path = root / "messages.jsonl"
            jsonl_rows = [
                {
                    "message_id": "jm-1",
                    "thread_id": "jt-1",
                    "sender": "kim@example.test",
                    "timestamp": "2024-10-04T14:00:00Z",
                    "subject": "Ship check",
                    "body": "Are release notes ready for review?",
                },
                {
                    "message_id": "jm-2",
                    "thread_id": "jt-1",
                    "in_reply_to": "jm-1",
                    "sender": "lee@example.test",
                    "timestamp": "2024-10-04T14:12:00Z",
                    "subject": "Re: Ship check",
                    "body": "Posted the draft link in the release ticket.",
                    "selected": True,
                },
            ]
            jsonl_path.write_text(
                "\n".join(json.dumps(r) for r in jsonl_rows) + "\n",
                encoding="utf-8",
            )
            jsonl_out = root / "out_jsonl"
            res_jsonl = prepare_input.convert_threads(
                source_format="jsonl",
                source_path=jsonl_path,
                output_dir=jsonl_out,
                target_flag_field="selected",
            )
            self.assertEqual(res_jsonl.exit_code, 0)
            pairs_jsonl, _, _ = load_pairs(jsonl_out / "reply-conversations.jsonl")
            self.assertEqual(len(pairs_jsonl), 1)

    def test_rejects_subject_only_links_ambiguous_inline_quotes_later_context_and_leaks(self):
        with tempfile.TemporaryDirectory() as tmp, patch("tools.prepare_input.restrict_directory"):
            root = Path(tmp)

            # Subject-only .eml messages without In-Reply-To MUST NOT be linked
            eml_dir = root / "subject_only"
            eml_dir.mkdir()
            (eml_dir / "a.eml").write_bytes(
                _build_eml(
                    msg_id="<s1@example.test>",
                    sender="a@example.test",
                    to="b@example.test",
                    subject="Budget sync",
                    date="Mon, 01 Oct 2024 09:00:00 +0000",
                    body="Can we review the Q4 sheet?",
                ).as_bytes()
            )
            (eml_dir / "b.eml").write_bytes(
                _build_eml(
                    msg_id="<s2@example.test>",
                    sender="b@example.test",
                    to="a@example.test",
                    subject="Re: Budget sync",
                    date="Mon, 01 Oct 2024 09:05:00 +0000",
                    body="Sure, let us meet at 2 PM.",
                ).as_bytes()
            )
            res_subj = prepare_input.convert_threads(
                source_format="eml",
                source_path=eml_dir,
                output_dir=root / "out_subj",
                target_message_ids=["<s2@example.test>"],
            )
            self.assertEqual(res_subj.exit_code, 1)
            self.assertEqual(res_subj.accepted, 0)
            self.assertIn("missing_explicit_reply_link", res_subj.rejection_reasons)
            self.assertFalse((root / "out_subj" / "reply-conversations.jsonl").exists())

            # Interleaved inline reply after '>' quote block + later parent timestamp + target leak
            txt_dir = root / "mixed_batch"
            txt_dir.mkdir()
            (txt_dir / "01_valid.txt").write_text(
                "Approved for Tuesday morning.\n\n"
                "-----Original Message-----\n"
                "From: Nora\n"
                "Subject: Change request\n\n"
                "Can we deploy Tuesday morning?\n",
                encoding="utf-8",
            )
            (txt_dir / "02_interleaved.txt").write_text(
                "See comments inline:\n"
                "> Question one?\n"
                "Answer one.\n",
                encoding="utf-8",
            )
            (txt_dir / "03_leak.txt").write_text(
                "Exact secret phrasing repeated verbatim inside the earlier thread history.\n\n"
                "-----Original Message-----\n"
                "From: Nora\n"
                "Subject: Leak\n\n"
                "Exact secret phrasing repeated verbatim inside the earlier thread history.\n",
                encoding="utf-8",
            )
            (txt_dir / "04_later_parent.txt").write_text(
                "=== MESSAGE ===\n"
                "Message-ID: <p1@example.test>\n"
                "From: A\n"
                "Sent: 2024-10-05T12:00:00Z\n"
                "Subject: Clock skew\n\n"
                "Parent appears later than reply.\n"
                "=== MESSAGE ===\n"
                "Message-ID: <p2@example.test>\n"
                "In-Reply-To: <p1@example.test>\n"
                "From: B\n"
                "Sent: 2024-10-05T11:00:00Z\n"
                "Subject: Re: Clock skew\n"
                "Target: true\n\n"
                "Reply timestamp precedes parent.\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = prepare_input.main(
                    [
                        "--format",
                        "text",
                        "--source",
                        str(txt_dir),
                        "--output-dir",
                        str(root / "out_mixed"),
                    ]
                )
            self.assertEqual(code, 2)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["accepted"], 1)
            self.assertEqual(report["rejected"], 3)
            self.assertIn("ambiguous_authored_reply", report["rejection_reasons"])
            self.assertIn("target_in_conversation", report["rejection_reasons"])
            self.assertIn("later_context_timestamp", report["rejection_reasons"])
            # Ensure private message text never leaks into conversion reports
            self.assertNotIn("Approved for Tuesday", stdout.getvalue())
            self.assertNotIn("Exact secret phrasing", stdout.getvalue())

    def test_refuses_overwrite_collision_missing_mappings_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_jsonl = root / "source.jsonl"
            raw_content = (
                json.dumps(
                    {
                        "conversation": "-----Original Message-----\nFrom: A\n\nNeed status update.",
                        "reply": "Status update sent.",
                    }
                )
                + "\n"
            )
            src_jsonl.write_text(raw_content, encoding="utf-8")
            before_sha = hashlib.sha256(src_jsonl.read_bytes()).hexdigest()

            out_dir = root / "prepared_out"
            with patch("tools.prepare_input.restrict_directory") as restrict_mock, contextlib.redirect_stdout(io.StringIO()):
                code1 = prepare_input.main(
                    [
                        "--format",
                        "jsonl",
                        "--source",
                        str(src_jsonl),
                        "--output-dir",
                        str(out_dir),
                    ]
                )
            self.assertEqual(code1, 0)
            restrict_mock.assert_called_once_with(out_dir.resolve())
            self.assertEqual(hashlib.sha256(src_jsonl.read_bytes()).hexdigest(), before_sha)

            # Second run to same destination refuses overwrite with exit code 1
            stdout_dup = io.StringIO()
            with contextlib.redirect_stdout(stdout_dup):
                code2 = prepare_input.main(
                    [
                        "--format",
                        "jsonl",
                        "--source",
                        str(src_jsonl),
                        "--output-dir",
                        str(out_dir),
                    ]
                )
            self.assertEqual(code2, 1)
            self.assertIn("Refusing to overwrite", stdout_dup.getvalue())

            # Source/destination collision fails with exit code 1
            stdout_col = io.StringIO()
            with contextlib.redirect_stdout(stdout_col):
                code3 = prepare_input.main(
                    [
                        "--format",
                        "jsonl",
                        "--source",
                        str(out_dir / "reply-conversations.jsonl"),
                        "--output-dir",
                        str(out_dir),
                    ]
                )
            self.assertEqual(code3, 1)

            # Missing required column mapping fails with exit code 1
            bad_csv = root / "unmapped.csv"
            bad_csv.write_text("col_a,col_b\nx,y\n", encoding="utf-8")
            stdout_map = io.StringIO()
            with contextlib.redirect_stdout(stdout_map):
                code4 = prepare_input.main(
                    [
                        "--format",
                        "csv",
                        "--source",
                        str(bad_csv),
                        "--output-dir",
                        str(root / "out_unmapped"),
                    ]
                )
            self.assertEqual(code4, 1)
            self.assertFalse((root / "out_unmapped" / "reply-conversations.jsonl").exists())
