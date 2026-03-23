"""Project assembly: .flow generation, project.vne creation, asset organization, validation."""

from vne_cli.assembly.asset_organizer import organize_assets
from vne_cli.assembly.flow_writer import generate_flows
from vne_cli.assembly.project_builder import build_project_config, write_project_vne
from vne_cli.assembly.validator import validate_project, ValidationReport

__all__ = [
    "build_project_config",
    "generate_flows",
    "organize_assets",
    "validate_project",
    "ValidationReport",
    "write_project_vne",
]
