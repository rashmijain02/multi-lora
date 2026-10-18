from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient

from email_workshop.data import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts" / "notebook-validation"
    reports = []
    for path in sorted((root / "notebooks").glob("*.ipynb")):
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type != "code":
                continue
            tree = ast.parse(cell.source, filename=f"{path.name}:{index}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Name)
                            and target.id
                            in {
                                "RUN_TRAINING",
                                "RUN_EVALUATION",
                                "RUN_VLLM_DEMO",
                                "RUN_TOKENIZATION_CHECK",
                            }
                            and not (
                                isinstance(node.value, ast.Constant) and node.value.value is False
                            )
                        ):
                            raise ValueError(
                                f"{path.name} has an enabled costly/external execution gate."
                            )
        if args.execute:
            os.environ["EMAIL_WORKSHOP_RUN"] = str(artifacts / "run")
            client = NotebookClient(
                notebook,
                timeout=180,
                kernel_name="email-multilora",
                resources={"metadata": {"path": str(root)}},
            )
            client.execute()
            artifacts.mkdir(parents=True, exist_ok=True)
            nbformat.write(notebook, artifacts / path.name)
        reports.append(
            {"notebook": path.name, "cells": len(notebook.cells), "executed": args.execute}
        )
    write_json(artifacts / "report.json", reports)
    for report in reports:
        print(report)


if __name__ == "__main__":
    main()
