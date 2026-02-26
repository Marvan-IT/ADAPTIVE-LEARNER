"""
JSON Exporter — saves pipeline output as structured JSON files.
"""

import json
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import PipelineOutput


def export_full_output(output: PipelineOutput, output_path: Path) -> None:
    """
    Export the combined JSON with all four sections:
    {
      "concept_blocks": [...],
      "dependency_edges": [...],
      "validation_report": [...],
      "mathpix_plan": [...]
    }
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = output.to_dict()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Exported full output to {output_path}")


def export_individual_files(output: PipelineOutput, output_dir: Path) -> None:
    """
    Export each section to its own JSON file for easier inspection.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = output.to_dict()

    # Concept blocks
    _write_json(output_dir / "concept_blocks.json", data["concept_blocks"])

    # Dependency edges
    _write_json(output_dir / "dependency_edges.json", data["dependency_edges"])

    # Validation report
    _write_json(output_dir / "validation_report.json", data["validation_report"])

    # Mathpix plan
    _write_json(output_dir / "mathpix_plan.json", data["mathpix_plan"])

    print(f"Exported individual files to {output_dir}")


def _write_json(path: Path, data) -> None:
    """Write a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
