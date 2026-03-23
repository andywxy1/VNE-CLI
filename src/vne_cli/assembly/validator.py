"""Validate an assembled VNE project for correctness and completeness.

Checks:
- project.vne exists and has valid JSON with all required fields
- entry_flow file exists
- All .flow files are valid JSON with correct structure
- All asset references in .flow files resolve to actual files
- Orphaned assets detection
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from vne_cli.providers.errors import ProjectValidationError

logger = logging.getLogger("vne_cli.assembly.validator")

# Required fields in project.vne.
REQUIRED_PROJECT_FIELDS = {
    "title",
    "entry_flow",
    "width_game_window",
    "height_game_window",
}

# Required top-level fields in a .flow file.
REQUIRED_FLOW_FIELDS = {"max_uid", "node_pool", "link_pool"}


@dataclass
class ValidationReport:
    """Results of project validation."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if there are no errors (warnings are acceptable)."""
        return len(self.errors) == 0

    def summary(self) -> str:
        """Return a human-readable summary."""
        lines = []
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"  [ERROR] {e}")
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  [WARN]  {w}")
        if not self.errors and not self.warnings:
            lines.append("Project validation passed with no issues.")
        elif not self.errors:
            lines.append(f"Project validation passed with {len(self.warnings)} warning(s).")
        else:
            lines.append(
                f"Project validation FAILED: {len(self.errors)} error(s), "
                f"{len(self.warnings)} warning(s)."
            )
        return "\n".join(lines)


def validate_project(project_dir: Path) -> ValidationReport:
    """Validate an assembled VNE project directory.

    Runs all validation checks and returns a report. Does not raise on
    validation failures -- the caller decides how to handle the report.

    Args:
        project_dir: Path to the project directory containing project.vne.

    Returns:
        A ValidationReport with errors and warnings.
    """
    report = ValidationReport()

    if not project_dir.exists():
        report.errors.append(f"Project directory does not exist: {project_dir}")
        return report

    # 1. Validate project.vne.
    project_config = _validate_project_vne(project_dir, report)

    # 2. Validate entry flow exists.
    if project_config is not None:
        _validate_entry_flow(project_dir, project_config, report)

    # 3. Validate all .flow files.
    flow_dir = project_dir / "application" / "flow"
    _validate_flow_files(flow_dir, report)

    # 4. Validate asset references.
    _validate_asset_references(flow_dir, project_dir, report)

    # 5. Check for orphaned assets.
    _check_orphaned_assets(flow_dir, project_dir, report)

    level = "INFO" if report.is_valid else "WARNING"
    logger.log(
        logging.getLevelName(level),
        "Validation complete: %d errors, %d warnings",
        len(report.errors),
        len(report.warnings),
    )
    return report


def _validate_project_vne(
    project_dir: Path,
    report: ValidationReport,
) -> dict | None:
    """Validate project.vne exists and has valid structure.

    Returns:
        Parsed project config dict, or None if invalid.
    """
    vne_path = project_dir / "project.vne"
    if not vne_path.exists():
        report.errors.append("project.vne not found in project directory.")
        return None

    try:
        data = json.loads(vne_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.errors.append(f"project.vne is not valid JSON: {e}")
        return None

    if not isinstance(data, dict):
        report.errors.append("project.vne root must be a JSON object.")
        return None

    # Check required fields.
    for field_name in REQUIRED_PROJECT_FIELDS:
        if field_name not in data:
            report.errors.append(f"project.vne missing required field: {field_name}")

    # Type checks on known fields.
    if "width_game_window" in data and not isinstance(data["width_game_window"], int):
        report.errors.append("project.vne: width_game_window must be an integer.")
    if "height_game_window" in data and not isinstance(data["height_game_window"], int):
        report.errors.append("project.vne: height_game_window must be an integer.")
    if "entry_flow" in data and not isinstance(data["entry_flow"], str):
        report.errors.append("project.vne: entry_flow must be a string.")
    if "title" in data and not isinstance(data["title"], str):
        report.errors.append("project.vne: title must be a string.")

    return data


def _validate_entry_flow(
    project_dir: Path,
    project_config: dict,
    report: ValidationReport,
) -> None:
    """Check that the entry_flow referenced in project.vne exists."""
    entry_flow = project_config.get("entry_flow", "")
    if not entry_flow:
        report.errors.append("project.vne: entry_flow is empty.")
        return

    entry_path = project_dir / entry_flow.replace("/", str(Path("/"))).lstrip(str(Path("/")))
    # Normalize: handle both forward and OS-native separators.
    entry_path = project_dir / Path(entry_flow)
    if not entry_path.exists():
        report.errors.append(
            f"Entry flow file does not exist: {entry_flow} "
            f"(expected at {entry_path})"
        )


def _validate_flow_files(
    flow_dir: Path,
    report: ValidationReport,
) -> None:
    """Validate all .flow files in the flow directory."""
    if not flow_dir.exists():
        report.warnings.append("Flow directory does not exist: application/flow/")
        return

    flow_files = list(flow_dir.glob("*.flow"))
    if not flow_files:
        report.warnings.append("No .flow files found in application/flow/")
        return

    for flow_file in flow_files:
        _validate_single_flow(flow_file, report)


def _validate_single_flow(flow_file: Path, report: ValidationReport) -> None:
    """Validate a single .flow file."""
    try:
        data = json.loads(flow_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.errors.append(f"{flow_file.name}: invalid JSON: {e}")
        return

    if not isinstance(data, dict):
        report.errors.append(f"{flow_file.name}: root must be a JSON object.")
        return

    # Check required fields.
    for field_name in REQUIRED_FLOW_FIELDS:
        if field_name not in data:
            report.errors.append(f"{flow_file.name}: missing required field: {field_name}")

    # Validate max_uid.
    max_uid = data.get("max_uid")
    if max_uid is not None:
        if not isinstance(max_uid, int) or max_uid < 0:
            report.errors.append(f"{flow_file.name}: max_uid must be a non-negative integer.")

    # Validate node_pool.
    node_pool = data.get("node_pool", [])
    if not isinstance(node_pool, list):
        report.errors.append(f"{flow_file.name}: node_pool must be an array.")
    else:
        seen_ids: set[int] = set()
        for node in node_pool:
            if not isinstance(node, dict):
                report.errors.append(f"{flow_file.name}: node_pool item must be an object.")
                continue
            node_id = node.get("id")
            if node_id is not None:
                if node_id in seen_ids:
                    report.errors.append(f"{flow_file.name}: duplicate node ID {node_id}.")
                seen_ids.add(node_id)
            if "type_id" not in node:
                report.errors.append(f"{flow_file.name}: node missing type_id.")

    # Validate link_pool.
    link_pool = data.get("link_pool", [])
    if not isinstance(link_pool, list):
        report.errors.append(f"{flow_file.name}: link_pool must be an array.")
    else:
        for link in link_pool:
            if not isinstance(link, dict):
                report.errors.append(f"{flow_file.name}: link_pool item must be an object.")
                continue
            for req_field in ("id", "input_pin_id", "output_pin_id"):
                if req_field not in link:
                    report.errors.append(
                        f"{flow_file.name}: link missing required field: {req_field}"
                    )

    # Check that an entry node exists.
    has_entry = any(
        isinstance(n, dict) and n.get("type_id") == "entry"
        for n in node_pool
        if isinstance(node_pool, list)
    )
    if not has_entry:
        report.warnings.append(f"{flow_file.name}: no 'entry' node found.")


def _validate_asset_references(
    flow_dir: Path,
    project_dir: Path,
    report: ValidationReport,
) -> None:
    """Check that asset references in .flow files resolve to actual files."""
    if not flow_dir.exists():
        return

    asset_pin_types = {"texture", "audio", "video", "font"}
    referenced: set[str] = set()

    for flow_file in flow_dir.glob("*.flow"):
        try:
            data = json.loads(flow_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for node in data.get("node_pool", []):
            for pin_list_key in ("input_pin_list", "output_pin_list"):
                for pin in node.get(pin_list_key, []):
                    if pin.get("type_id") in asset_pin_types:
                        val = pin.get("val", "")
                        if val and isinstance(val, str):
                            referenced.add(val)

    # Build set of available asset identifiers.
    available: set[str] = set()
    resources_dir = project_dir / "application" / "resources"
    if resources_dir.exists():
        for f in resources_dir.rglob("*"):
            if f.is_file():
                available.add(f.stem)
                available.add(f.name)
                rel = str(f.relative_to(project_dir)).replace("\\", "/")
                available.add(rel)

    for ref in sorted(referenced):
        if ref not in available:
            report.warnings.append(f"Asset reference not resolved: '{ref}'")


def _check_orphaned_assets(
    flow_dir: Path,
    project_dir: Path,
    report: ValidationReport,
) -> None:
    """Find asset files that no .flow file references."""
    if not flow_dir.exists():
        return

    # Collect all referenced asset IDs.
    asset_pin_types = {"texture", "audio", "video", "font"}
    referenced: set[str] = set()

    for flow_file in flow_dir.glob("*.flow"):
        try:
            data = json.loads(flow_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for node in data.get("node_pool", []):
            for pin_list_key in ("input_pin_list", "output_pin_list"):
                for pin in node.get(pin_list_key, []):
                    if pin.get("type_id") in asset_pin_types:
                        val = pin.get("val", "")
                        if val and isinstance(val, str):
                            referenced.add(val)

    # Check each asset file.
    resources_dir = project_dir / "application" / "resources"
    if not resources_dir.exists():
        return

    for f in resources_dir.rglob("*"):
        if not f.is_file():
            continue
        stem = f.stem
        name = f.name
        rel = str(f.relative_to(project_dir)).replace("\\", "/")
        if stem not in referenced and name not in referenced and rel not in referenced:
            report.warnings.append(f"Orphaned asset (not referenced by any flow): {name}")
