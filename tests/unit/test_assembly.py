"""Tests for the VNE project assembly pipeline.

Covers:
- project.vne generation with correct fields
- Flow writing produces valid .flow JSON
- Asset organization creates correct directory structure
- Validation catches missing assets and broken references
- Full assembly pipeline with mock data
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vne_cli.config.schema import AssemblyConfig, CinematicConfig
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    Chapter,
    CharacterRef,
    ChoiceOption,
    Scene,
    Story,
    StoryMetadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_story() -> Story:
    """A minimal story with one chapter and two scenes for testing."""
    return Story(
        metadata=StoryMetadata(title="Test Novel", author="Test Author"),
        characters={
            "char_001": CharacterRef(
                id="char_001",
                name="Elena",
                aliases=["Princess Elena"],
                is_protagonist=True,
                description="Silver hair, blue eyes",
                sprite_variants=["neutral", "happy"],
            ),
            "char_002": CharacterRef(
                id="char_002",
                name="Marcus",
                description="Tall, dark hair",
                sprite_variants=["neutral"],
            ),
        },
        chapters=[
            Chapter(
                id="ch_001",
                index=0,
                title="The Beginning",
                synopsis="The story begins.",
                scenes=[
                    Scene(
                        id="ch_001_sc_001",
                        title="The Library",
                        background_description="Ornate castle library",
                        characters_present=["char_001", "char_002"],
                        beats=[
                            Beat(
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                expression="neutral",
                                text="I never expected to find this here.",
                            ),
                            Beat(
                                type=BeatType.NARRATION,
                                text="The dust motes drifted through the amber light.",
                            ),
                        ],
                    ),
                    Scene(
                        id="ch_001_sc_002",
                        title="The Garden",
                        background_description="Castle garden with roses",
                        characters_present=["char_001"],
                        beats=[
                            Beat(
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                expression="happy",
                                text="The garden is beautiful today.",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def branching_story() -> Story:
    """A story with a choice/branch for testing branching flows."""
    return Story(
        metadata=StoryMetadata(title="Branching Story"),
        characters={
            "char_001": CharacterRef(
                id="char_001", name="Elena", is_protagonist=True,
            ),
        },
        chapters=[
            Chapter(
                id="ch_001",
                index=0,
                title="Choices",
                scenes=[
                    Scene(
                        id="ch_001_sc_001",
                        title="The Decision",
                        beats=[
                            Beat(
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                text="What should I do?",
                            ),
                            Beat(
                                type=BeatType.CHOICE,
                                text="Choose wisely",
                                options=[
                                    ChoiceOption(
                                        text="Go left",
                                        target_scene="ch_001_sc_002a",
                                        consequence_tag="went_left",
                                    ),
                                    ChoiceOption(
                                        text="Go right",
                                        target_scene="ch_001_sc_002b",
                                        consequence_tag="went_right",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    Scene(
                        id="ch_001_sc_002a",
                        title="Left Path",
                        branch_info=BranchInfo(
                            is_branch=True,
                            branch_source="ch_001_sc_001",
                            converges_at="ch_001_sc_003",
                        ),
                        beats=[
                            Beat(type=BeatType.NARRATION, text="You went left."),
                        ],
                    ),
                    Scene(
                        id="ch_001_sc_002b",
                        title="Right Path",
                        branch_info=BranchInfo(
                            is_branch=True,
                            branch_source="ch_001_sc_001",
                            converges_at="ch_001_sc_003",
                        ),
                        beats=[
                            Beat(type=BeatType.NARRATION, text="You went right."),
                        ],
                    ),
                    Scene(
                        id="ch_001_sc_003",
                        title="Convergence",
                        beats=[
                            Beat(type=BeatType.NARRATION, text="The paths merge."),
                        ],
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def sample_assets_dir(tmp_path: Path) -> Path:
    """Create a temporary assets directory with some test files."""
    assets = tmp_path / "assets"
    chars = assets / "characters"
    bgs = assets / "backgrounds"
    chars.mkdir(parents=True)
    bgs.mkdir(parents=True)

    # Create dummy asset files.
    (chars / "char_001_neutral.png").write_bytes(b"fake png data")
    (chars / "char_001_happy.png").write_bytes(b"fake png data")
    (chars / "char_002_neutral.png").write_bytes(b"fake png data")
    (bgs / "ch_001_sc_001.png").write_bytes(b"fake png data")
    (bgs / "ch_001_sc_002.png").write_bytes(b"fake png data")

    return assets


# ---------------------------------------------------------------------------
# Test: project_builder
# ---------------------------------------------------------------------------


class TestProjectBuilder:
    """Tests for project.vne generation."""

    def test_build_project_config_has_required_fields(self, sample_story: Story) -> None:
        from vne_cli.assembly.project_builder import build_project_config

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
        )

        assert config["title"] == "Test Novel"
        assert config["entry_flow"] == "application/flow/entry.flow"
        assert config["width_game_window"] == 1920
        assert config["height_game_window"] == 1080
        assert config["default_fullscreen"] is False
        assert config["release_version"] == "1.0.0"
        assert config["project_version"] == "dev"
        assert config["developer"] == "VNE-CLI"
        assert config["icon_path"] == "application/icon/icon.png"
        assert config["is_show_debug_fps"] is False
        assert config["release_mode"] is False
        assert config["editor_zoom_ratio"] == 1.0

    def test_build_project_config_title_override(self, sample_story: Story) -> None:
        from vne_cli.assembly.project_builder import build_project_config

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
            title="Custom Title",
        )
        assert config["title"] == "Custom Title"

    def test_build_project_config_resolution_override(self, sample_story: Story) -> None:
        from vne_cli.assembly.project_builder import build_project_config

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
            width=1280,
            height=720,
        )
        assert config["width_game_window"] == 1280
        assert config["height_game_window"] == 720

    def test_build_project_config_fullscreen(self, sample_story: Story) -> None:
        from vne_cli.assembly.project_builder import build_project_config

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
            fullscreen=True,
        )
        assert config["default_fullscreen"] is True

    def test_build_project_config_fallback_title(self) -> None:
        """When story has no title, falls back to default."""
        from vne_cli.assembly.project_builder import build_project_config

        story = Story()
        config = build_project_config(
            story=story,
            entry_flow_path="application/flow/entry.flow",
        )
        assert config["title"] == "Untitled Visual Novel"

    def test_build_project_config_forward_slashes(self, sample_story: Story) -> None:
        """Entry flow path must use forward slashes."""
        from vne_cli.assembly.project_builder import build_project_config

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application\\flow\\entry.flow",
        )
        assert "\\" not in config["entry_flow"]
        assert config["entry_flow"] == "application/flow/entry.flow"

    def test_write_project_vne_creates_file(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.project_builder import build_project_config, write_project_vne

        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
        )
        vne_path = write_project_vne(config, tmp_path)

        assert vne_path.exists()
        data = json.loads(vne_path.read_text(encoding="utf-8"))
        assert data["title"] == "Test Novel"
        assert data["entry_flow"] == "application/flow/entry.flow"

    def test_create_directory_structure(self, tmp_path: Path) -> None:
        from vne_cli.assembly.project_builder import create_directory_structure

        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        assert (project_dir / "application" / "flow").is_dir()
        assert (project_dir / "application" / "resources" / "characters").is_dir()
        assert (project_dir / "application" / "resources" / "backgrounds").is_dir()
        assert (project_dir / "application" / "resources" / "audio").is_dir()
        assert (project_dir / "application" / "resources" / "fonts").is_dir()
        assert (project_dir / "application" / "icon").is_dir()

    def test_write_main_lua(self, tmp_path: Path) -> None:
        from vne_cli.assembly.project_builder import write_main_lua

        lua_path = write_main_lua(tmp_path)
        assert lua_path.exists()
        assert lua_path.name == "main.lua"
        content = lua_path.read_text(encoding="utf-8")
        assert "VNE-CLI" in content

    def test_create_default_icon(self, tmp_path: Path) -> None:
        from vne_cli.assembly.project_builder import create_default_icon

        icon_path = create_default_icon(tmp_path)
        assert icon_path.exists()
        assert icon_path.name == "icon.png"
        # Should start with PNG signature.
        data = icon_path.read_bytes()
        assert data[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Test: flow_writer
# ---------------------------------------------------------------------------


class TestFlowWriter:
    """Tests for .flow file generation."""

    def test_generate_flows_creates_entry_flow(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        flows = generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        assert len(flows) > 0
        entry_path = flow_dir / "entry.flow"
        assert entry_path.exists()
        assert flows[0] == entry_path

    def test_generate_flows_creates_per_scene_flows(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        flows = generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        # 1 entry + 2 scenes = 3 flows.
        assert len(flows) == 3
        assert (flow_dir / "ch_001_sc_001.flow").exists()
        assert (flow_dir / "ch_001_sc_002.flow").exists()

    def test_generated_flow_is_valid_json(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        flows = generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        for flow_path in flows:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            assert "max_uid" in data
            assert "node_pool" in data
            assert "link_pool" in data
            assert isinstance(data["node_pool"], list)
            assert isinstance(data["link_pool"], list)

    def test_entry_flow_has_entry_node(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        data = json.loads((flow_dir / "entry.flow").read_text(encoding="utf-8"))
        types = [n["type_id"] for n in data["node_pool"]]
        assert "entry" in types
        assert "switch_scene" in types

    def test_scene_flow_contains_dialogue_node(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        data = json.loads((flow_dir / "ch_001_sc_001.flow").read_text(encoding="utf-8"))
        types = [n["type_id"] for n in data["node_pool"]]
        assert "show_dialog_box" in types
        assert "show_subtitle" in types

    def test_branching_story_generates_all_scenes(
        self, branching_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        flows = generate_flows(
            story=branching_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        # 1 entry + 4 scenes.
        assert len(flows) == 5
        assert (flow_dir / "ch_001_sc_001.flow").exists()
        assert (flow_dir / "ch_001_sc_002a.flow").exists()
        assert (flow_dir / "ch_001_sc_002b.flow").exists()
        assert (flow_dir / "ch_001_sc_003.flow").exists()

    def test_cinematic_direction_applied(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        flow_dir = tmp_path / "flow"
        generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=True, tier="base"),
        )

        data = json.loads((flow_dir / "ch_001_sc_001.flow").read_text(encoding="utf-8"))
        types = [n["type_id"] for n in data["node_pool"]]
        assert "transition_fade_in" in types

    def test_empty_story_generates_entry_only(self, tmp_path: Path) -> None:
        from vne_cli.assembly.flow_writer import generate_flows

        story = Story(metadata=StoryMetadata(title="Empty"))
        flow_dir = tmp_path / "flow"
        flows = generate_flows(
            story=story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        assert len(flows) == 1
        assert flows[0].name == "entry.flow"


# ---------------------------------------------------------------------------
# Test: asset_organizer
# ---------------------------------------------------------------------------


class TestAssetOrganizer:
    """Tests for asset organization."""

    def test_organize_copies_characters(
        self, sample_assets_dir: Path, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.asset_organizer import organize_assets

        project = tmp_path / "project"
        report = organize_assets(sample_assets_dir, project)

        chars_dir = project / "application" / "resources" / "characters"
        assert (chars_dir / "char_001_neutral.png").exists()
        assert (chars_dir / "char_001_happy.png").exists()
        assert (chars_dir / "char_002_neutral.png").exists()
        assert report.characters_copied == 3

    def test_organize_copies_backgrounds(
        self, sample_assets_dir: Path, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.asset_organizer import organize_assets

        project = tmp_path / "project"
        report = organize_assets(sample_assets_dir, project)

        bgs_dir = project / "application" / "resources" / "backgrounds"
        assert (bgs_dir / "ch_001_sc_001.png").exists()
        assert (bgs_dir / "ch_001_sc_002.png").exists()
        assert report.backgrounds_copied == 2

    def test_organize_nonexistent_assets_dir(self, tmp_path: Path) -> None:
        from vne_cli.assembly.asset_organizer import organize_assets

        project = tmp_path / "project"
        report = organize_assets(tmp_path / "nonexistent", project)

        assert report.total_copied == 0
        assert len(report.warnings) > 0

    def test_organize_creates_target_directories(
        self, sample_assets_dir: Path, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.asset_organizer import organize_assets

        project = tmp_path / "project"
        organize_assets(sample_assets_dir, project)

        assert (project / "application" / "resources" / "characters").is_dir()
        assert (project / "application" / "resources" / "backgrounds").is_dir()

    def test_organize_loose_files_by_naming_convention(self, tmp_path: Path) -> None:
        """Files at the assets root are organized by name prefix."""
        from vne_cli.assembly.asset_organizer import organize_assets

        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "bg_forest.png").write_bytes(b"fake")
        (assets / "char_hero.png").write_bytes(b"fake")

        project = tmp_path / "project"
        report = organize_assets(assets, project)

        assert (project / "application" / "resources" / "backgrounds" / "bg_forest.png").exists()
        assert (project / "application" / "resources" / "characters" / "char_hero.png").exists()
        assert report.backgrounds_copied == 1
        assert report.characters_copied == 1


# ---------------------------------------------------------------------------
# Test: validator
# ---------------------------------------------------------------------------


class TestValidator:
    """Tests for project validation."""

    def _create_valid_project(self, project_dir: Path, sample_story: Story) -> None:
        """Helper to create a minimal valid project."""
        from vne_cli.assembly.flow_writer import generate_flows
        from vne_cli.assembly.project_builder import (
            build_project_config,
            create_default_icon,
            create_directory_structure,
            write_main_lua,
            write_project_vne,
        )

        create_directory_structure(project_dir)
        flow_dir = project_dir / "application" / "flow"
        generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )
        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
        )
        write_project_vne(config, project_dir)
        write_main_lua(project_dir)
        create_default_icon(project_dir)

    def test_valid_project_passes(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        self._create_valid_project(project, sample_story)

        report = validate_project(project)
        assert report.is_valid, f"Expected valid but got errors: {report.errors}"

    def test_missing_project_vne(self, tmp_path: Path) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        project.mkdir()

        report = validate_project(project)
        assert not report.is_valid
        assert any("project.vne" in e for e in report.errors)

    def test_invalid_project_vne_json(self, tmp_path: Path) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        project.mkdir()
        (project / "project.vne").write_text("not json{{{", encoding="utf-8")

        report = validate_project(project)
        assert not report.is_valid
        assert any("not valid JSON" in e for e in report.errors)

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        project.mkdir()
        (project / "project.vne").write_text('{"title": "Test"}', encoding="utf-8")

        report = validate_project(project)
        assert not report.is_valid
        assert any("entry_flow" in e for e in report.errors)

    def test_missing_entry_flow_file(self, tmp_path: Path) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        project.mkdir()
        config = {
            "title": "Test",
            "entry_flow": "application/flow/entry.flow",
            "width_game_window": 1920,
            "height_game_window": 1080,
        }
        (project / "project.vne").write_text(json.dumps(config), encoding="utf-8")

        report = validate_project(project)
        assert not report.is_valid
        assert any("Entry flow file does not exist" in e for e in report.errors)

    def test_invalid_flow_file(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        self._create_valid_project(project, sample_story)

        # Corrupt one flow file.
        bad_flow = project / "application" / "flow" / "bad.flow"
        bad_flow.write_text("not json", encoding="utf-8")

        report = validate_project(project)
        assert any("bad.flow" in e and "invalid JSON" in e for e in report.errors)

    def test_flow_missing_required_fields(
        self, sample_story: Story, tmp_path: Path
    ) -> None:
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        self._create_valid_project(project, sample_story)

        # Write a flow file missing required fields.
        incomplete_flow = project / "application" / "flow" / "incomplete.flow"
        incomplete_flow.write_text('{"node_pool": []}', encoding="utf-8")

        report = validate_project(project)
        assert any("missing required field" in e for e in report.errors)

    def test_nonexistent_project_dir(self, tmp_path: Path) -> None:
        from vne_cli.assembly.validator import validate_project

        report = validate_project(tmp_path / "nonexistent")
        assert not report.is_valid

    def test_validation_report_summary(self) -> None:
        from vne_cli.assembly.validator import ValidationReport

        report = ValidationReport()
        assert "no issues" in report.summary()

        report.warnings.append("test warning")
        assert "1 warning" in report.summary()

        report.errors.append("test error")
        assert "FAILED" in report.summary()


# ---------------------------------------------------------------------------
# Test: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Integration-style tests for the complete assembly pipeline."""

    def test_full_assembly_produces_valid_project(
        self,
        sample_story: Story,
        sample_assets_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test the complete assembly pipeline end-to-end."""
        from vne_cli.assembly.asset_organizer import organize_assets
        from vne_cli.assembly.flow_writer import generate_flows
        from vne_cli.assembly.project_builder import (
            build_project_config,
            create_default_icon,
            create_directory_structure,
            write_main_lua,
            write_project_vne,
        )
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"

        # 1. Create directory structure.
        create_directory_structure(project)

        # 2. Generate flows.
        flow_dir = project / "application" / "flow"
        flows = generate_flows(
            story=sample_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=True, tier="base"),
        )

        # 3. Organize assets.
        organize_assets(sample_assets_dir, project, flow_dir=flow_dir)

        # 4. Generate project.vne.
        config = build_project_config(
            story=sample_story,
            entry_flow_path="application/flow/entry.flow",
            title="Test Novel",
        )
        write_project_vne(config, project)

        # 5. Write extras.
        write_main_lua(project)
        create_default_icon(project)

        # 6. Validate.
        report = validate_project(project)

        # Assert project structure.
        assert (project / "project.vne").exists()
        assert (project / "main.lua").exists()
        assert (project / "application" / "icon" / "icon.png").exists()
        assert len(flows) == 3  # entry + 2 scenes

        # Verify project.vne content.
        vne_data = json.loads(
            (project / "project.vne").read_text(encoding="utf-8")
        )
        assert vne_data["title"] == "Test Novel"
        assert vne_data["entry_flow"] == "application/flow/entry.flow"

        # Verify flows are valid JSON.
        for flow_path in flows:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            assert "max_uid" in data
            assert "node_pool" in data
            assert isinstance(data["node_pool"], list)
            assert len(data["node_pool"]) > 0

        # Validation should pass (possibly with asset warnings).
        assert report.is_valid, f"Validation errors: {report.errors}"

    def test_assembly_with_branching_story(
        self,
        branching_story: Story,
        tmp_path: Path,
    ) -> None:
        """Test assembly of a story with choice branches."""
        from vne_cli.assembly.flow_writer import generate_flows
        from vne_cli.assembly.project_builder import (
            build_project_config,
            create_directory_structure,
            write_project_vne,
        )
        from vne_cli.assembly.validator import validate_project

        project = tmp_path / "project"
        create_directory_structure(project)

        flow_dir = project / "application" / "flow"
        flows = generate_flows(
            story=branching_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        config = build_project_config(
            story=branching_story,
            entry_flow_path="application/flow/entry.flow",
        )
        write_project_vne(config, project)

        report = validate_project(project)
        assert report.is_valid, f"Validation errors: {report.errors}"

        # Branch scenes have switch_scene to convergence.
        for scene_id in ("ch_001_sc_002a", "ch_001_sc_002b"):
            data = json.loads(
                (flow_dir / f"{scene_id}.flow").read_text(encoding="utf-8")
            )
            types = [n["type_id"] for n in data["node_pool"]]
            assert "switch_scene" in types, f"{scene_id} should switch to convergence scene"

    def test_assembly_with_empty_story(self, tmp_path: Path) -> None:
        """Assembly of an empty story should produce a valid (minimal) project."""
        from vne_cli.assembly.flow_writer import generate_flows
        from vne_cli.assembly.project_builder import (
            build_project_config,
            create_directory_structure,
            write_project_vne,
        )
        from vne_cli.assembly.validator import validate_project

        story = Story(metadata=StoryMetadata(title="Empty Novel"))
        project = tmp_path / "project"
        create_directory_structure(project)

        flow_dir = project / "application" / "flow"
        flows = generate_flows(
            story=story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        config = build_project_config(
            story=story,
            entry_flow_path="application/flow/entry.flow",
        )
        write_project_vne(config, project)

        report = validate_project(project)
        assert report.is_valid, f"Validation errors: {report.errors}"
        assert len(flows) == 1  # Entry only.
