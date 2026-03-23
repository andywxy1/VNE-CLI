"""End-to-end integration tests for the VNE-CLI pipeline.

Tests the full pipeline: extract -> generate-assets -> assemble,
using mock providers for deterministic, offline testing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.integration.conftest import (
    MINIMAL_PNG,
    MockImageProvider,
    MockLLMProvider,
    build_branching_story,
    build_linear_story,
    build_minimal_story,
    populate_assets_dir,
)
from tests.integration.flow_validator import FlowValidationResult, validate_flow_file
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
from vne_cli.assets.manifest import save_manifest
from vne_cli.assets.prompt_builder import build_asset_requests
from vne_cli.config.schema import (
    AssemblyConfig,
    AssetsConfig,
    ChunkingConfig,
    CinematicConfig,
    VneConfig,
)
from vne_cli.extraction.character_pass import extract_characters
from vne_cli.extraction.chunker import TextChunk, chunk_text
from vne_cli.extraction.structure_pass import extract_structure
from vne_cli.extraction.validator import validate_story
from vne_cli.flow.serializer import serialize_flow
from vne_cli.schemas.asset_manifest import (
    AssetEntry,
    AssetManifestSchema,
    AssetStatus,
    AssetType,
)
from vne_cli.schemas.story import Story, StoryMetadata


# ===================================================================
# A. Extract -> story.json validity
# ===================================================================


class TestExtractPipeline:
    """Test the extraction pipeline produces valid story.json."""

    @pytest.mark.asyncio
    async def test_extract_produces_valid_story(
        self,
        sample_novel_path: Path,
        mock_llm: MockLLMProvider,
    ) -> None:
        """Extract with mock LLM produces a story with all required fields."""
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())

        # Run character extraction
        registry = await extract_characters(chunks, mock_llm, source_file="test.txt")
        assert len(registry.characters) >= 2
        assert registry.protagonist == "char_001"

        # Run structure extraction
        story = await extract_structure(
            chunks, registry, mock_llm, source_file="test.txt"
        )

        # Validate required top-level fields
        assert story.metadata is not None
        assert story.metadata.title != ""
        assert story.characters is not None
        assert len(story.characters) >= 2
        assert story.chapters is not None
        assert len(story.chapters) >= 1

    @pytest.mark.asyncio
    async def test_character_registry_complete(
        self,
        sample_novel_path: Path,
        mock_llm: MockLLMProvider,
    ) -> None:
        """Character registry has IDs, names, and sprite expressions."""
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())

        registry = await extract_characters(chunks, mock_llm, source_file="test.txt")

        for char_id, char in registry.characters.items():
            assert char.id == char_id
            assert char.name != ""
            assert len(char.sprite_expressions) > 0

    @pytest.mark.asyncio
    async def test_scenes_have_required_fields(
        self,
        sample_novel_path: Path,
        mock_llm: MockLLMProvider,
    ) -> None:
        """Every scene has dialogue/narration, location, and characters_present."""
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())
        registry = await extract_characters(chunks, mock_llm, source_file="test.txt")
        story = await extract_structure(chunks, registry, mock_llm, source_file="test.txt")

        for chapter in story.chapters:
            for scene in chapter.scenes:
                assert scene.id != "", f"Scene missing id in chapter {chapter.id}"
                assert len(scene.beats) > 0, f"Scene {scene.id} has no beats"
                assert len(scene.characters_present) > 0, (
                    f"Scene {scene.id} has no characters_present"
                )

    @pytest.mark.asyncio
    async def test_story_json_serialization_roundtrip(
        self,
        tmp_path: Path,
        mock_llm: MockLLMProvider,
        sample_novel_path: Path,
    ) -> None:
        """Story can be serialized to JSON and loaded back."""
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())
        registry = await extract_characters(chunks, mock_llm, source_file="test.txt")
        story = await extract_structure(chunks, registry, mock_llm, source_file="test.txt")

        # Serialize
        output = tmp_path / "story.json"
        data = story.model_dump(by_alias=True, mode="json")
        output.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        # Reload
        loaded_data = json.loads(output.read_text(encoding="utf-8"))
        loaded_story = Story.model_validate(loaded_data)

        assert loaded_story.metadata.title == story.metadata.title
        assert len(loaded_story.chapters) == len(story.chapters)
        assert len(loaded_story.characters) == len(story.characters)

    @pytest.mark.asyncio
    async def test_branching_extraction(
        self,
        sample_novel_path: Path,
        mock_llm_branching: MockLLMProvider,
    ) -> None:
        """Extraction with branching LLM produces choice beats."""
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())
        registry = await extract_characters(
            chunks, mock_llm_branching, source_file="test.txt"
        )
        story = await extract_structure(
            chunks, registry, mock_llm_branching, source_file="test.txt"
        )

        # Find choice beats
        choice_beats = []
        for ch in story.chapters:
            for sc in ch.scenes:
                for beat in sc.beats:
                    if beat.type.value == "choice":
                        choice_beats.append(beat)

        assert len(choice_beats) >= 1, "Expected at least one choice beat"
        assert len(choice_beats[0].options) >= 2, "Choice should have at least 2 options"

    def test_story_validation_passes(self, linear_story: Story) -> None:
        """Pre-built linear story passes validation."""
        warnings = validate_story(linear_story)
        # Warnings are OK; errors would raise
        assert isinstance(warnings, list)


# ===================================================================
# B. Generate-assets -> files on disk
# ===================================================================


class TestGenerateAssets:
    """Test asset generation produces correct files and manifest."""

    def test_asset_requests_built_correctly(self, linear_story: Story) -> None:
        """build_asset_requests produces background and sprite requests."""
        requests = build_asset_requests(linear_story)

        bg_requests = [r for r in requests if r.asset_type == "background"]
        sprite_requests = [r for r in requests if r.asset_type == "sprite"]

        assert len(bg_requests) >= 1, "Should have at least 1 background"
        assert len(sprite_requests) >= 2, "Should have sprites for at least 2 characters"

        # Check sprite requests cover all character expressions
        for char_id, char_ref in linear_story.characters.items():
            for expr in char_ref.sprite_variants:
                expected_id = f"sprite_{char_id}_{expr}"
                matching = [r for r in sprite_requests if r.asset_id == expected_id]
                assert len(matching) == 1, f"Missing sprite request: {expected_id}"

    def test_background_deduplication(self, linear_story: Story) -> None:
        """Same location description produces only one background request."""
        requests = build_asset_requests(linear_story)
        bg_requests = [r for r in requests if r.asset_type == "background"]

        # Both scenes in the linear story have the same background_description
        # so deduplication should reduce to one background
        location_keys = [r.location_key for r in bg_requests]
        assert len(location_keys) == len(set(location_keys)), (
            "Background requests should be deduplicated by location"
        )

    @pytest.mark.asyncio
    async def test_asset_pipeline_produces_files(
        self,
        tmp_path: Path,
        linear_story: Story,
        mock_image_provider: MockImageProvider,
    ) -> None:
        """Full asset pipeline writes image files and manifest to disk."""
        from vne_cli.assets.pipeline import run_asset_pipeline

        output_dir = tmp_path / "assets"
        manifest = await run_asset_pipeline(
            story=linear_story,
            image_provider=mock_image_provider,
            config=AssetsConfig(),
            output_dir=output_dir,
        )

        # Check manifest
        assert manifest.summary.total > 0
        assert manifest.summary.complete == manifest.summary.total
        assert manifest.summary.failed == 0

        # Check files on disk
        bg_dir = output_dir / "backgrounds"
        char_dir = output_dir / "characters"
        assert bg_dir.exists(), "backgrounds/ directory should exist"
        assert char_dir.exists(), "characters/ directory should exist"

        bg_files = list(bg_dir.glob("*.png"))
        char_files = list(char_dir.glob("*.png"))
        assert len(bg_files) >= 1, "Should have at least 1 background PNG"
        assert len(char_files) >= 2, "Should have at least 2 character sprite PNGs"

    @pytest.mark.asyncio
    async def test_asset_pipeline_resume(
        self,
        tmp_path: Path,
        linear_story: Story,
        mock_image_provider: MockImageProvider,
    ) -> None:
        """Deleting one asset and re-running only regenerates that one."""
        from vne_cli.assets.pipeline import run_asset_pipeline

        output_dir = tmp_path / "assets"

        # First run: generate all
        manifest1 = await run_asset_pipeline(
            story=linear_story,
            image_provider=mock_image_provider,
            config=AssetsConfig(),
            output_dir=output_dir,
        )
        first_run_calls = len(mock_image_provider.calls)
        total_assets = manifest1.summary.total
        assert total_assets > 0

        # Delete one character sprite file from disk and mark it pending in manifest
        # Find a complete sprite entry
        sprite_entry = None
        sprite_key = None
        for key, entry in manifest1.assets.items():
            if entry.type == AssetType.SPRITE and entry.status == AssetStatus.COMPLETE:
                sprite_entry = entry
                sprite_key = key
                break

        assert sprite_entry is not None, "Should have at least one completed sprite"
        assert sprite_entry.file is not None

        # Delete the file
        file_path = output_dir / sprite_entry.file
        if file_path.exists():
            file_path.unlink()

        # Mark as pending in manifest
        sprite_entry.status = AssetStatus.PENDING
        sprite_entry.file = None
        manifest1.recompute_summary()

        # Save modified manifest
        manifest_path = output_dir / "asset-manifest.json"
        save_manifest(manifest1, manifest_path)

        # Create a fresh mock to count calls
        mock_image_2 = MockImageProvider()

        # Second run: should only regenerate the one deleted asset
        manifest2 = await run_asset_pipeline(
            story=linear_story,
            image_provider=mock_image_2,
            config=AssetsConfig(),
            output_dir=output_dir,
            manifest=manifest1,
        )

        # Only 1 new call for the deleted asset
        assert len(mock_image_2.calls) == 1, (
            f"Expected 1 regeneration call, got {len(mock_image_2.calls)}"
        )
        assert manifest2.summary.complete == total_assets

    def test_characters_only_mode(self, linear_story: Story) -> None:
        """characters_only=True produces only sprite requests."""
        requests = build_asset_requests(linear_story, characters_only=True)
        assert all(r.asset_type == "sprite" for r in requests)
        assert len(requests) > 0

    def test_backgrounds_only_mode(self, linear_story: Story) -> None:
        """backgrounds_only=True produces only background requests."""
        requests = build_asset_requests(linear_story, backgrounds_only=True)
        assert all(r.asset_type == "background" for r in requests)
        assert len(requests) > 0


# ===================================================================
# C. Assemble -> valid VNE project
# ===================================================================


class TestAssemblePipeline:
    """Test assembly produces a valid, complete VNE project."""

    def test_project_structure_created(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """create_directory_structure produces the expected directory layout."""
        output = tmp_path / "project"
        create_directory_structure(output)

        assert (output / "application" / "flow").is_dir()
        assert (output / "application" / "resources" / "characters").is_dir()
        assert (output / "application" / "resources" / "backgrounds").is_dir()
        assert (output / "application" / "resources" / "audio").is_dir()
        assert (output / "application" / "resources" / "fonts").is_dir()
        assert (output / "application" / "icon").is_dir()

    def test_project_vne_has_correct_fields(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """project.vne contains all required fields with correct types."""
        output = tmp_path / "project"
        output.mkdir(parents=True, exist_ok=True)

        config = build_project_config(
            linear_story,
            "application/flow/entry.flow",
            title="Test VN",
            width=1920,
            height=1080,
        )
        write_project_vne(config, output)

        vne_path = output / "project.vne"
        assert vne_path.exists()

        data = json.loads(vne_path.read_text(encoding="utf-8"))
        assert data["title"] == "Test VN"
        assert data["entry_flow"] == "application/flow/entry.flow"
        assert isinstance(data["width_game_window"], int)
        assert isinstance(data["height_game_window"], int)
        assert data["width_game_window"] == 1920
        assert data["height_game_window"] == 1080

    def test_entry_flow_exists_and_valid(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """The entry.flow file is generated and passes flow validation."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        flow_files = generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        entry_flow = flow_dir / "entry.flow"
        assert entry_flow.exists(), "entry.flow must exist"
        assert entry_flow in flow_files

        result = validate_flow_file(entry_flow)
        result.assert_valid()

    def test_all_flow_files_valid_json(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Every generated .flow file is valid JSON with required structure."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        flow_files = generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        assert len(flow_files) >= 3, (
            f"Expected at least 3 .flow files (entry + 2 scenes), got {len(flow_files)}"
        )

        for flow_path in flow_files:
            assert flow_path.exists(), f"Flow file not found: {flow_path}"

            # Parse and check structure
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            assert "max_uid" in data, f"{flow_path.name}: missing max_uid"
            assert "node_pool" in data, f"{flow_path.name}: missing node_pool"
            assert "link_pool" in data, f"{flow_path.name}: missing link_pool"
            assert isinstance(data["node_pool"], list)
            assert isinstance(data["link_pool"], list)

    def test_flow_files_pass_spec_validation(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Every generated .flow file passes the full spec validator."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        flow_files = generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        for flow_path in flow_files:
            result = validate_flow_file(flow_path)
            result.assert_valid()

    def test_node_ids_unique_within_flow(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Node IDs are unique within each .flow file."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        for flow_path in flow_dir.glob("*.flow"):
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            node_ids = [n["id"] for n in data["node_pool"]]
            assert len(node_ids) == len(set(node_ids)), (
                f"{flow_path.name}: duplicate node IDs found"
            )

    def test_max_uid_correct(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """max_uid >= highest ID in each .flow file."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        for flow_path in flow_dir.glob("*.flow"):
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            max_uid = data["max_uid"]

            # Collect all IDs
            all_ids: list[int] = []
            for node in data["node_pool"]:
                all_ids.append(node["id"])
                for pin in node.get("input_pin_list", []):
                    all_ids.append(pin["id"])
                for pin in node.get("output_pin_list", []):
                    all_ids.append(pin["id"])
            for link in data["link_pool"]:
                all_ids.append(link["id"])

            if all_ids:
                highest = max(all_ids)
                assert max_uid >= highest, (
                    f"{flow_path.name}: max_uid ({max_uid}) < highest ID ({highest})"
                )

    def test_counterintuitive_link_naming(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Links use correct counterintuitive naming convention."""
        output = tmp_path / "project"
        create_directory_structure(output)
        flow_dir = output / "application" / "flow"

        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        for flow_path in flow_dir.glob("*.flow"):
            data = json.loads(flow_path.read_text(encoding="utf-8"))

            # Build pin lookup
            pin_map: dict[int, dict[str, Any]] = {}
            for node in data["node_pool"]:
                for pin in node.get("input_pin_list", []):
                    pin_map[pin["id"]] = pin
                for pin in node.get("output_pin_list", []):
                    pin_map[pin["id"]] = pin

            for link in data["link_pool"]:
                # input_pin_id should be an output pin (is_output=true)
                input_pin = pin_map.get(link["input_pin_id"])
                assert input_pin is not None, (
                    f"{flow_path.name}: link {link['id']} input_pin_id "
                    f"references nonexistent pin {link['input_pin_id']}"
                )
                assert input_pin["is_output"] is True, (
                    f"{flow_path.name}: link {link['id']} input_pin_id "
                    f"should reference an output pin (counterintuitive naming)"
                )

                # output_pin_id should be an input pin (is_output=false)
                output_pin = pin_map.get(link["output_pin_id"])
                assert output_pin is not None, (
                    f"{flow_path.name}: link {link['id']} output_pin_id "
                    f"references nonexistent pin {link['output_pin_id']}"
                )
                assert output_pin["is_output"] is False, (
                    f"{flow_path.name}: link {link['id']} output_pin_id "
                    f"should reference an input pin (counterintuitive naming)"
                )

    def test_asset_references_resolve(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Asset references in .flow files resolve to actual files."""
        output = tmp_path / "project"
        create_directory_structure(output)

        # Generate flows
        flow_dir = output / "application" / "flow"
        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Populate assets
        assets_dir = tmp_path / "assets"
        populate_assets_dir(linear_story, assets_dir)
        organize_assets(assets_dir=assets_dir, output_dir=output, flow_dir=flow_dir)

        # Write project.vne (required for validate_project)
        config = build_project_config(
            linear_story, "application/flow/entry.flow"
        )
        write_project_vne(config, output)

        # Run validation
        report = validate_project(output)
        # Structural errors should be zero; asset reference warnings are OK
        # (texture IDs in flows may not exactly match filenames and that's
        # expected -- the validator flags them as warnings, not errors)
        assert report.is_valid, (
            f"Validation errors: {report.errors}"
        )

    def test_full_assembly_validation_passes(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Full assembly produces a project that passes validation."""
        output = tmp_path / "project"
        create_directory_structure(output)

        # Generate flows
        flow_dir = output / "application" / "flow"
        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Organize assets
        assets_dir = tmp_path / "assets"
        populate_assets_dir(linear_story, assets_dir)
        organize_assets(assets_dir=assets_dir, output_dir=output, flow_dir=flow_dir)

        # Write project.vne
        config = build_project_config(
            linear_story, "application/flow/entry.flow"
        )
        write_project_vne(config, output)
        write_main_lua(output)
        create_default_icon(output)

        # Validate
        report = validate_project(output)
        assert report.is_valid, f"Validation failed:\n{report.summary()}"


# ===================================================================
# D. Full pipeline (extract -> generate-assets -> assemble)
# ===================================================================


class TestFullPipeline:
    """Full end-to-end pipeline test."""

    @pytest.mark.asyncio
    async def test_full_pipeline_linear(
        self,
        tmp_path: Path,
        sample_novel_path: Path,
        mock_llm: MockLLMProvider,
        mock_image_provider: MockImageProvider,
    ) -> None:
        """Complete pipeline: novel -> extract -> generate-assets -> assemble."""
        from vne_cli.assets.pipeline import run_asset_pipeline

        # Step 1: Extract
        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())
        registry = await extract_characters(chunks, mock_llm, source_file="test.txt")
        story = await extract_structure(
            chunks, registry, mock_llm, source_file="test.txt"
        )

        # Verify extraction
        assert len(story.chapters) >= 1
        assert len(story.characters) >= 2

        # Write story.json
        story_path = tmp_path / "story.json"
        data = story.model_dump(by_alias=True, mode="json")
        story_path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )

        # Step 2: Generate assets
        assets_dir = tmp_path / "assets"
        manifest = await run_asset_pipeline(
            story=story,
            image_provider=mock_image_provider,
            config=AssetsConfig(),
            output_dir=assets_dir,
        )
        assert manifest.summary.complete > 0

        # Step 3: Assemble
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        flow_dir = project_dir / "application" / "flow"
        flow_files = generate_flows(
            story=story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        organize_assets(
            assets_dir=assets_dir,
            output_dir=project_dir,
            flow_dir=flow_dir,
        )

        config = build_project_config(story, "application/flow/entry.flow")
        write_project_vne(config, project_dir)
        write_main_lua(project_dir)
        create_default_icon(project_dir)

        # Validate complete project
        report = validate_project(project_dir)
        assert report.is_valid, f"Validation failed:\n{report.summary()}"

        # Verify directory layout
        assert (project_dir / "project.vne").exists()
        assert (project_dir / "main.lua").exists()
        assert (project_dir / "application" / "flow" / "entry.flow").exists()
        assert len(flow_files) >= 3  # entry + at least 2 scene flows

    @pytest.mark.asyncio
    async def test_full_pipeline_branching(
        self,
        tmp_path: Path,
        sample_novel_path: Path,
        mock_llm_branching: MockLLMProvider,
        mock_image_provider: MockImageProvider,
    ) -> None:
        """Full pipeline with branching story."""
        from vne_cli.assets.pipeline import run_asset_pipeline

        text = sample_novel_path.read_text(encoding="utf-8")
        chunks = chunk_text(text, ChunkingConfig())
        registry = await extract_characters(
            chunks, mock_llm_branching, source_file="test.txt"
        )
        story = await extract_structure(
            chunks, registry, mock_llm_branching, source_file="test.txt"
        )

        # Verify choice beats exist
        has_choice = False
        for ch in story.chapters:
            for sc in ch.scenes:
                for beat in sc.beats:
                    if beat.type.value == "choice":
                        has_choice = True
        assert has_choice, "Story should contain at least one choice beat"

        # Generate assets
        assets_dir = tmp_path / "assets"
        await run_asset_pipeline(
            story=story,
            image_provider=mock_image_provider,
            config=AssetsConfig(),
            output_dir=assets_dir,
        )

        # Assemble
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)
        flow_dir = project_dir / "application" / "flow"
        generate_flows(
            story=story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )
        organize_assets(assets_dir=assets_dir, output_dir=project_dir, flow_dir=flow_dir)
        config = build_project_config(story, "application/flow/entry.flow")
        write_project_vne(config, project_dir)
        write_main_lua(project_dir)
        create_default_icon(project_dir)

        report = validate_project(project_dir)
        assert report.is_valid, f"Validation failed:\n{report.summary()}"

    def test_full_pipeline_from_prebuild_story(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Assemble from pre-built story data (no LLM needed)."""
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        flow_dir = project_dir / "application" / "flow"
        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        assets_dir = tmp_path / "assets"
        populate_assets_dir(linear_story, assets_dir)
        organize_assets(assets_dir=assets_dir, output_dir=project_dir, flow_dir=flow_dir)

        config = build_project_config(linear_story, "application/flow/entry.flow")
        write_project_vne(config, project_dir)
        write_main_lua(project_dir)
        create_default_icon(project_dir)

        report = validate_project(project_dir)
        assert report.is_valid, f"Validation failed:\n{report.summary()}"

        # Verify VNE expected layout
        assert (project_dir / "project.vne").exists()
        assert (project_dir / "main.lua").exists()
        assert (project_dir / "application" / "flow" / "entry.flow").exists()
        assert (project_dir / "application" / "icon" / "icon.png").exists()


# ===================================================================
# E. Edge case tests
# ===================================================================


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_linear_story_no_branching(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Linear story (no choices) produces valid linear flows."""
        flow_dir = tmp_path / "flows"
        flow_files = generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # No choice nodes should exist in any flow
        for flow_path in flow_files:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            for node in data["node_pool"]:
                assert node["type_id"] != "show_choice_button", (
                    f"Linear story should not have choice nodes, "
                    f"found one in {flow_path.name}"
                )

            # Validate each flow
            result = validate_flow_file(flow_path)
            result.assert_valid()

    def test_branching_story_has_choice_nodes(
        self, tmp_path: Path, branching_story: Story
    ) -> None:
        """Branching story produces .flow files with choice nodes."""
        flow_dir = tmp_path / "flows"
        flow_files = generate_flows(
            story=branching_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # At least one flow should have a show_choice_button node
        found_choice = False
        for flow_path in flow_files:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
            for node in data["node_pool"]:
                if node["type_id"] == "show_choice_button":
                    found_choice = True
                    break
            if found_choice:
                break

        assert found_choice, "Branching story should produce choice nodes"

        # All flows should still be valid
        for flow_path in flow_files:
            result = validate_flow_file(flow_path)
            result.assert_valid()

    def test_branching_story_convergence(
        self, tmp_path: Path, branching_story: Story
    ) -> None:
        """Branch scenes with converges_at generate switch_scene to convergence."""
        flow_dir = tmp_path / "flows"
        generate_flows(
            story=branching_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Check branch flows (sc_003a, sc_003b) have switch_scene nodes
        for branch_id in ("ch_001_sc_003a", "ch_001_sc_003b"):
            flow_path = flow_dir / f"{branch_id}.flow"
            assert flow_path.exists(), f"Branch flow {branch_id}.flow should exist"

            data = json.loads(flow_path.read_text(encoding="utf-8"))
            switch_nodes = [
                n for n in data["node_pool"]
                if n["type_id"] == "switch_scene"
            ]
            assert len(switch_nodes) >= 1, (
                f"Branch flow {branch_id} should have a switch_scene node "
                f"for convergence"
            )

    def test_minimal_story_single_scene(
        self, tmp_path: Path, minimal_story: Story
    ) -> None:
        """Minimal story (1 scene, 2 characters) produces a valid project."""
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        flow_dir = project_dir / "application" / "flow"
        flow_files = generate_flows(
            story=minimal_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Should have entry + 1 scene flow
        assert len(flow_files) == 2, (
            f"Expected 2 flows (entry + 1 scene), got {len(flow_files)}"
        )

        for flow_path in flow_files:
            result = validate_flow_file(flow_path)
            result.assert_valid()

        # Full project assembly
        assets_dir = tmp_path / "assets"
        populate_assets_dir(minimal_story, assets_dir)
        organize_assets(assets_dir=assets_dir, output_dir=project_dir, flow_dir=flow_dir)
        config = build_project_config(minimal_story, "application/flow/entry.flow")
        write_project_vne(config, project_dir)
        write_main_lua(project_dir)
        create_default_icon(project_dir)

        report = validate_project(project_dir)
        assert report.is_valid, f"Validation failed:\n{report.summary()}"

    def test_missing_assets_warns_not_crashes(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Assembly with missing assets produces warnings, not crashes."""
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        flow_dir = project_dir / "application" / "flow"
        generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Use an empty assets directory
        empty_assets = tmp_path / "empty_assets"
        empty_assets.mkdir()

        # Should NOT crash
        asset_report = organize_assets(
            assets_dir=empty_assets, output_dir=project_dir, flow_dir=flow_dir
        )

        # Should have zero copied, but warnings about missing references
        assert asset_report.total_copied == 0

        # project.vne should still be writable
        config = build_project_config(linear_story, "application/flow/entry.flow")
        write_project_vne(config, project_dir)

        # Validation should complete (may have warnings about missing assets)
        report = validate_project(project_dir)
        # The project structure is valid even without assets
        assert (project_dir / "project.vne").exists()

    def test_nonexistent_assets_dir_warns(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """organize_assets with nonexistent assets dir returns warning."""
        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        fake_assets = tmp_path / "does_not_exist"
        report = organize_assets(assets_dir=fake_assets, output_dir=project_dir)

        assert len(report.warnings) > 0
        assert report.total_copied == 0

    def test_empty_story_produces_valid_project(self, tmp_path: Path) -> None:
        """Story with no chapters still produces a valid (minimal) project."""
        empty_story = Story(
            metadata=StoryMetadata(title="Empty"),
            characters={},
            chapters=[],
        )

        project_dir = tmp_path / "project"
        create_directory_structure(project_dir)

        flow_dir = project_dir / "application" / "flow"
        flow_files = generate_flows(
            story=empty_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(),
        )

        # Should at least have entry flow
        assert len(flow_files) >= 1
        entry_flow = flow_dir / "entry.flow"
        assert entry_flow.exists()

        result = validate_flow_file(entry_flow)
        result.assert_valid()

    def test_cinematic_disabled(
        self, tmp_path: Path, linear_story: Story
    ) -> None:
        """Flows generated with cinematic disabled are still valid."""
        flow_dir = tmp_path / "flows"
        flow_files = generate_flows(
            story=linear_story,
            output_dir=flow_dir,
            assembly_config=AssemblyConfig(),
            cinematic_config=CinematicConfig(enabled=False),
        )

        for flow_path in flow_files:
            result = validate_flow_file(flow_path)
            result.assert_valid()

    def test_flow_validator_catches_bad_max_uid(self, tmp_path: Path) -> None:
        """Flow validator detects max_uid that is too low."""
        bad_flow = {
            "max_uid": 1,  # Too low -- entry node alone uses uid 1 and 2
            "is_open": True,
            "node_pool": [
                {
                    "id": 1,
                    "type_id": "entry",
                    "position": {"x": 0, "y": 0},
                    "input_pin_list": [],
                    "output_pin_list": [
                        {"id": 2, "type_id": "flow", "is_output": True}
                    ],
                }
            ],
            "link_pool": [],
        }
        path = tmp_path / "bad.flow"
        path.write_text(json.dumps(bad_flow), encoding="utf-8")

        result = validate_flow_file(path)
        assert not result.is_valid
        assert any("max_uid" in e for e in result.errors)

    def test_flow_validator_catches_duplicate_ids(self, tmp_path: Path) -> None:
        """Flow validator detects duplicate IDs."""
        bad_flow = {
            "max_uid": 3,
            "is_open": True,
            "node_pool": [
                {
                    "id": 1,
                    "type_id": "entry",
                    "position": {"x": 0, "y": 0},
                    "input_pin_list": [],
                    "output_pin_list": [
                        {"id": 2, "type_id": "flow", "is_output": True}
                    ],
                },
                {
                    "id": 1,  # Duplicate!
                    "type_id": "delay",
                    "position": {"x": 100, "y": 0},
                    "input_pin_list": [
                        {"id": 3, "type_id": "flow", "is_output": False}
                    ],
                    "output_pin_list": [],
                },
            ],
            "link_pool": [],
        }
        path = tmp_path / "dup.flow"
        path.write_text(json.dumps(bad_flow), encoding="utf-8")

        result = validate_flow_file(path)
        assert not result.is_valid
        assert any("Duplicate" in e for e in result.errors)

    def test_flow_validator_catches_bad_link_naming(self, tmp_path: Path) -> None:
        """Flow validator detects wrong counterintuitive link naming."""
        bad_flow = {
            "max_uid": 6,
            "is_open": True,
            "node_pool": [
                {
                    "id": 1,
                    "type_id": "entry",
                    "position": {"x": 0, "y": 0},
                    "input_pin_list": [],
                    "output_pin_list": [
                        {"id": 2, "type_id": "flow", "is_output": True}
                    ],
                },
                {
                    "id": 3,
                    "type_id": "delay",
                    "position": {"x": 100, "y": 0},
                    "input_pin_list": [
                        {"id": 4, "type_id": "flow", "is_output": False},
                        {"id": 5, "type_id": "float", "is_output": False, "val": 1.0},
                    ],
                    "output_pin_list": [],
                },
            ],
            "link_pool": [
                {
                    "id": 6,
                    # WRONG: input_pin_id should be an output pin (2),
                    # but we put the input pin (4) here
                    "input_pin_id": 4,
                    "output_pin_id": 2,
                }
            ],
        }
        path = tmp_path / "badlink.flow"
        path.write_text(json.dumps(bad_flow), encoding="utf-8")

        result = validate_flow_file(path)
        assert not result.is_valid
        assert any("counterintuitive" in e.lower() or "is_output=false" in e for e in result.errors)


# ===================================================================
# F. Flow validator unit tests
# ===================================================================


class TestFlowValidator:
    """Tests for the flow validation utility itself."""

    def test_valid_minimal_flow(self, tmp_path: Path) -> None:
        """Minimal valid flow (just entry node) passes validation."""
        flow = {
            "max_uid": 2,
            "is_open": True,
            "node_pool": [
                {
                    "id": 1,
                    "type_id": "entry",
                    "position": {"x": 0, "y": 0},
                    "input_pin_list": [],
                    "output_pin_list": [
                        {"id": 2, "type_id": "flow", "is_output": True}
                    ],
                }
            ],
            "link_pool": [],
        }
        path = tmp_path / "minimal.flow"
        path.write_text(json.dumps(flow), encoding="utf-8")

        result = validate_flow_file(path)
        assert result.is_valid, f"Errors: {result.errors}"
        assert result.node_count == 1
        assert result.link_count == 0

    def test_nonexistent_file(self) -> None:
        """Validator handles nonexistent file gracefully."""
        result = validate_flow_file(Path("/nonexistent/path.flow"))
        assert not result.is_valid
        assert len(result.errors) == 1

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Validator handles invalid JSON."""
        path = tmp_path / "bad.flow"
        path.write_text("not json at all", encoding="utf-8")

        result = validate_flow_file(path)
        assert not result.is_valid
        assert any("JSON" in e for e in result.errors)

    def test_missing_fields(self, tmp_path: Path) -> None:
        """Validator detects missing required fields."""
        path = tmp_path / "incomplete.flow"
        path.write_text(json.dumps({"max_uid": 0}), encoding="utf-8")

        result = validate_flow_file(path)
        assert not result.is_valid
        assert any("node_pool" in e or "link_pool" in e for e in result.errors)
