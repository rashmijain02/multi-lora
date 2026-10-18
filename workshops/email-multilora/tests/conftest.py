import pytest

from email_workshop.data import LABELS, prepare, write_json


@pytest.fixture
def prepared(tmp_path):
    rows = [
        {
            "subject": f"{label} example {i}",
            "body": f"Unique message {i} for {label}. Please review the details.",
            "labels": [label],
        }
        for i in range(20)
        for label in LABELS
    ]
    source = tmp_path / "source.json"
    write_json(source, rows)
    root = tmp_path / "run"
    prepare(root, source=source)
    return root
