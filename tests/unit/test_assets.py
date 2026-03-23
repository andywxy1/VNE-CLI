"""Tests for the asset generation pipeline.

Covers:
- Manifest persistence and resume logic
- Prompt builder output for characters and backgrounds
- Background deduplication
- Pipeline orchestration with mock ImageProvider
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vne_cli.assets.downloader import save_background, save_image, save_sprite
from vne_cli.assets.manifest import load_manifest, save_manifest
from vne_cli.assets.pipeline import (
    _get_pending_requests,
    _init_manifest,
    build_dry_run_plan,
    run_asset_pipeline,
)
from vne_cli.assets.prompt_builder import (
    AssetRequest,
    build_asset_requests,
    build_background_prompt,
    build_sprite_prompt,
    _make_location_key,
)
from vne_cli.config.schema import AssetsConfig
from vne_cli.schemas.asset_manifest import (
    AssetEntry,
    AssetManifestSchema,
    AssetStatus,
    AssetType,
)
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    Chapter,
    CharacterRef,
    Scene,
    Story,
    StoryMetadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_character(
    char_id: str = "char_001",
    name: str = "Elena",
    description: str = "Tall woman with silver hair and blue eyes",
    sprite_variants: list[str] | None = None,
) -> CharacterRef:
    return CharacterRef(
        id=char_id,
        name=name,
        description=description,
        sprite_variants=["neutral", "happy", "sad"] if sprite_variants is None else sprite_variants,
    )


def _make_scene(
    scene_id: str = "ch_001_sc_001",
    location: str = "Castle Library",
    time_of_day: str = "evening",
    background_description: str = "Ornate castle library with tall bookshelves",
) -> Scene:
    return Scene(
        id=scene_id,
        title="The Library",
        location=location,
        time_of_day=time_of_day,
        background_description=background_description,
        characters_present=["char_001"],
        beats=[
            Beat(type=BeatType.DIALOGUE, character="char_001", text="Hello"),
        ],
    )


def _make_story(
    characters: dict[str, CharacterRef] | None = None,
    scenes: list[Scene] | None = None,
) -> Story:
    if characters is None:
        characters = {"char_001": _make_character()}
    if scenes is None:
        scenes = [_make_scene()]
    return Story(
        metadata=StoryMetadata(title="Test Story"),
        characters=characters,
        chapters=[
            Chapter(id="ch_001", title="Chapter 1", scenes=scenes),
        ],
    )


@pytest.fixture
def sample_story() -> Story:
    return _make_story()


@pytest.fixture
def assets_config() -> AssetsConfig:
    return AssetsConfig(
        style="anime style, visual novel art",
        background_size=(1920, 1080),
        sprite_size=(800, 1200),
        output_format="png",
    )


class MockImageProvider:
    """Mock image provider that returns minimal valid PNG bytes."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self._calls: list[dict[str, Any]] = []
        self._fail_on = fail_on or set()

    @property
    def name(self) -> str:
        return "mock-image"

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        self._calls.append({
            "prompt": prompt,
            "width": width,
            "height": height,
            "style": style,
        })
        # Check if we should fail for this prompt
        for fail_key in self._fail_on:
            if fail_key in prompt:
                raise ConnectionError(f"Simulated failure for: {fail_key}")

        # Return a minimal valid PNG (1x1 pixel, red)
        return _minimal_png()

    async def close(self) -> None:
        pass


def _minimal_png() -> bytes:
    """Create a minimal valid PNG image using Pillow."""
    import io
    from PIL import Image

    img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===========================================================================
# Prompt Builder Tests
# ===========================================================================


class TestSpritePrompt:
    def test_includes_description(self) -> None:
        char = _make_character(description="Tall woman with silver hair")
        prompt = build_sprite_prompt(char, "neutral", "anime style")
        assert "Tall woman with silver hair" in prompt

    def test_includes_expression(self) -> None:
        char = _make_character()
        prompt = build_sprite_prompt(char, "happy", "anime style")
        assert "happy expression" in prompt

    def test_includes_sprite_directives(self) -> None:
        char = _make_character()
        prompt = build_sprite_prompt(char, "neutral", "anime style")
        assert "front-facing portrait" in prompt
        assert "transparent background" in prompt

    def test_includes_style_prefix(self) -> None:
        char = _make_character()
        prompt = build_sprite_prompt(char, "neutral", "watercolor, soft lighting")
        assert "watercolor, soft lighting" in prompt


class TestBackgroundPrompt:
    def test_includes_background_description(self) -> None:
        scene = _make_scene(background_description="Dark forest with twisted trees")
        prompt = build_background_prompt(scene, "anime style")
        assert "Dark forest with twisted trees" in prompt

    def test_falls_back_to_location(self) -> None:
        scene = _make_scene(
            location="Royal Palace",
            background_description="",
        )
        prompt = build_background_prompt(scene, "anime style")
        assert "Royal Palace" in prompt

    def test_includes_time_of_day_lighting(self) -> None:
        scene = _make_scene(time_of_day="night")
        prompt = build_background_prompt(scene, "anime style")
        assert "moonlight" in prompt

    def test_evening_lighting(self) -> None:
        scene = _make_scene(time_of_day="evening")
        prompt = build_background_prompt(scene, "anime style")
        assert "warm evening light" in prompt

    def test_includes_no_characters_directive(self) -> None:
        scene = _make_scene()
        prompt = build_background_prompt(scene, "anime style")
        assert "no characters" in prompt

    def test_includes_style(self) -> None:
        scene = _make_scene()
        prompt = build_background_prompt(scene, "pixel art, retro")
        assert "pixel art, retro" in prompt


class TestBuildAssetRequests:
    def test_generates_backgrounds_and_sprites(self, sample_story: Story) -> None:
        requests = build_asset_requests(sample_story)
        bg_reqs = [r for r in requests if r.asset_type == "background"]
        sprite_reqs = [r for r in requests if r.asset_type == "sprite"]
        assert len(bg_reqs) >= 1
        assert len(sprite_reqs) >= 1

    def test_characters_only(self, sample_story: Story) -> None:
        requests = build_asset_requests(sample_story, characters_only=True)
        assert all(r.asset_type == "sprite" for r in requests)

    def test_backgrounds_only(self, sample_story: Story) -> None:
        requests = build_asset_requests(sample_story, backgrounds_only=True)
        assert all(r.asset_type == "background" for r in requests)

    def test_sprite_per_expression(self) -> None:
        char = _make_character(sprite_variants=["neutral", "happy", "angry"])
        story = _make_story(characters={"char_001": char})
        requests = build_asset_requests(story, backgrounds_only=False, characters_only=False)
        sprite_reqs = [r for r in requests if r.asset_type == "sprite"]
        expressions = {r.expression for r in sprite_reqs}
        assert expressions == {"neutral", "happy", "angry"}

    def test_default_expression_when_none(self) -> None:
        char = _make_character(sprite_variants=[])
        story = _make_story(characters={"char_001": char})
        requests = build_asset_requests(story, characters_only=True)
        assert len(requests) == 1
        assert requests[0].expression == "neutral"


class TestBackgroundDeduplication:
    def test_same_location_deduplicates(self) -> None:
        """Same background_description + time_of_day = one background."""
        scene1 = _make_scene(
            scene_id="sc_001",
            background_description="Castle library",
            time_of_day="evening",
        )
        scene2 = _make_scene(
            scene_id="sc_002",
            background_description="Castle library",
            time_of_day="evening",
        )
        story = _make_story(scenes=[scene1, scene2])
        requests = build_asset_requests(story, characters_only=False)
        bg_reqs = [r for r in requests if r.asset_type == "background"]
        assert len(bg_reqs) == 1

    def test_different_time_creates_separate_bg(self) -> None:
        """Same location with different time_of_day = separate backgrounds."""
        scene1 = _make_scene(
            scene_id="sc_001",
            background_description="Castle library",
            time_of_day="morning",
        )
        scene2 = _make_scene(
            scene_id="sc_002",
            background_description="Castle library",
            time_of_day="night",
        )
        story = _make_story(scenes=[scene1, scene2])
        requests = build_asset_requests(story, characters_only=False)
        bg_reqs = [r for r in requests if r.asset_type == "background"]
        assert len(bg_reqs) == 2

    def test_different_locations_not_deduplicated(self) -> None:
        scene1 = _make_scene(
            scene_id="sc_001",
            background_description="Castle library",
            time_of_day="evening",
        )
        scene2 = _make_scene(
            scene_id="sc_002",
            background_description="Dark forest",
            time_of_day="evening",
        )
        story = _make_story(scenes=[scene1, scene2])
        requests = build_asset_requests(story, characters_only=False)
        bg_reqs = [r for r in requests if r.asset_type == "background"]
        assert len(bg_reqs) == 2


class TestLocationKey:
    def test_deterministic(self) -> None:
        key1 = _make_location_key("Castle Library", "evening")
        key2 = _make_location_key("Castle Library", "evening")
        assert key1 == key2

    def test_case_insensitive(self) -> None:
        key1 = _make_location_key("Castle Library", "Evening")
        key2 = _make_location_key("castle library", "evening")
        assert key1 == key2

    def test_different_inputs_different_keys(self) -> None:
        key1 = _make_location_key("Castle Library", "evening")
        key2 = _make_location_key("Dark Forest", "evening")
        assert key1 != key2


# ===========================================================================
# Manifest Tests
# ===========================================================================


class TestManifestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        manifest = AssetManifestSchema(
            generated_at=datetime.now(timezone.utc),
            provider="test-provider",
            style="anime",
        )
        manifest.assets["bg_001"] = AssetEntry(
            type=AssetType.BACKGROUND,
            prompt="test prompt",
            status=AssetStatus.COMPLETE,
            file="backgrounds/bg_001.png",
            width=1920,
            height=1080,
        )
        manifest.recompute_summary()

        path = tmp_path / "manifest.json"
        save_manifest(manifest, path)
        loaded = load_manifest(path)

        assert loaded.provider == "test-provider"
        assert loaded.style == "anime"
        assert "bg_001" in loaded.assets
        assert loaded.assets["bg_001"].status == AssetStatus.COMPLETE
        assert loaded.summary.total == 1
        assert loaded.summary.complete == 1

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        from vne_cli.providers.errors import ManifestError

        with pytest.raises(ManifestError):
            load_manifest(path)

    def test_summary_recomputation(self) -> None:
        manifest = AssetManifestSchema()
        manifest.assets["a"] = AssetEntry(
            type=AssetType.SPRITE, status=AssetStatus.COMPLETE
        )
        manifest.assets["b"] = AssetEntry(
            type=AssetType.SPRITE, status=AssetStatus.PENDING
        )
        manifest.assets["c"] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.FAILED
        )
        manifest.recompute_summary()
        assert manifest.summary.total == 3
        assert manifest.summary.complete == 1
        assert manifest.summary.pending == 1
        assert manifest.summary.failed == 1


class TestManifestResume:
    def test_init_manifest_preserves_completed(
        self, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        """Already-completed assets are not overwritten when re-initializing."""
        requests = build_asset_requests(sample_story, style_prefix=assets_config.style)
        assert len(requests) > 0

        # Pre-populate one asset as complete
        existing = AssetManifestSchema(provider="test", style="anime")
        first_id = requests[0].asset_id
        existing.assets[first_id] = AssetEntry(
            type=AssetType.BACKGROUND,
            status=AssetStatus.COMPLETE,
            file="backgrounds/test.png",
        )

        manifest = _init_manifest(
            sample_story, assets_config, "test", requests, existing
        )
        assert manifest.assets[first_id].status == AssetStatus.COMPLETE

    def test_pending_requests_skips_complete(self) -> None:
        manifest = AssetManifestSchema()
        manifest.assets["bg_001"] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.COMPLETE
        )
        manifest.assets["bg_002"] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.PENDING
        )

        requests = [
            AssetRequest(
                asset_id="bg_001", asset_type="background",
                prompt="p1", negative_prompt="", width=1920, height=1080,
            ),
            AssetRequest(
                asset_id="bg_002", asset_type="background",
                prompt="p2", negative_prompt="", width=1920, height=1080,
            ),
        ]

        pending = _get_pending_requests(manifest, requests)
        assert len(pending) == 1
        assert pending[0].asset_id == "bg_002"

    def test_failed_assets_retried_by_default(self) -> None:
        manifest = AssetManifestSchema()
        manifest.assets["bg_001"] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.FAILED
        )
        requests = [
            AssetRequest(
                asset_id="bg_001", asset_type="background",
                prompt="p1", negative_prompt="", width=1920, height=1080,
            ),
        ]
        pending = _get_pending_requests(manifest, requests, retry_failed=True)
        assert len(pending) == 1

    def test_failed_assets_skipped_when_retry_disabled(self) -> None:
        manifest = AssetManifestSchema()
        manifest.assets["bg_001"] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.FAILED
        )
        requests = [
            AssetRequest(
                asset_id="bg_001", asset_type="background",
                prompt="p1", negative_prompt="", width=1920, height=1080,
            ),
        ]
        pending = _get_pending_requests(manifest, requests, retry_failed=False)
        assert len(pending) == 0


# ===========================================================================
# Downloader Tests
# ===========================================================================


class TestDownloader:
    def test_save_background_creates_file(self, tmp_path: Path) -> None:
        png_bytes = _minimal_png()
        rel_path = save_background(
            png_bytes, "bg_test", tmp_path, width=1920, height=1080
        )
        full_path = tmp_path / rel_path
        assert full_path.exists()
        assert full_path.suffix == ".png"
        assert "backgrounds" in str(rel_path)

    def test_save_sprite_creates_file(self, tmp_path: Path) -> None:
        png_bytes = _minimal_png()
        rel_path = save_sprite(
            png_bytes, "char_001", "neutral", tmp_path, width=800, height=1200
        )
        full_path = tmp_path / rel_path
        assert full_path.exists()
        assert full_path.suffix == ".png"
        assert "characters" in str(rel_path)

    def test_save_image_creates_parent_dirs(self, tmp_path: Path) -> None:
        png_bytes = _minimal_png()
        output = tmp_path / "deep" / "nested" / "image.png"
        save_image(png_bytes, output)
        assert output.exists()

    def test_save_image_resizes(self, tmp_path: Path) -> None:
        from PIL import Image
        import io

        png_bytes = _minimal_png()  # 10x10 image
        output = tmp_path / "resized.png"
        save_image(png_bytes, output, target_width=20, target_height=20)
        img = Image.open(output)
        assert img.size == (20, 20)


# ===========================================================================
# Pipeline Integration Tests (with Mock Provider)
# ===========================================================================


class TestPipeline:
    def test_full_pipeline_with_mock_provider(
        self, tmp_path: Path, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        provider = MockImageProvider()

        manifest = asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                concurrency=2,
                max_retries=0,
            )
        )

        assert manifest.summary.total > 0
        assert manifest.summary.complete == manifest.summary.total
        assert manifest.summary.failed == 0

        # Verify files were created
        bg_dir = tmp_path / "backgrounds"
        char_dir = tmp_path / "characters"
        assert bg_dir.exists()
        assert char_dir.exists()

        # At least one of each
        bg_files = list(bg_dir.glob("*.png"))
        char_files = list(char_dir.glob("*.png"))
        assert len(bg_files) >= 1
        assert len(char_files) >= 1

    def test_pipeline_saves_manifest(
        self, tmp_path: Path, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        provider = MockImageProvider()

        asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                concurrency=1,
                max_retries=0,
            )
        )

        manifest_path = tmp_path / "asset-manifest.json"
        assert manifest_path.exists()

        loaded = load_manifest(manifest_path)
        assert loaded.summary.complete > 0

    def test_pipeline_resume_skips_completed(
        self, tmp_path: Path, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        """Second run should skip already-completed assets."""
        provider = MockImageProvider()

        # First run
        manifest1 = asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                concurrency=1,
                max_retries=0,
            )
        )
        calls_first = len(provider._calls)

        # Second run with same manifest
        provider2 = MockImageProvider()
        manifest2 = asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider2,
                config=assets_config,
                output_dir=tmp_path,
                manifest=manifest1,
                concurrency=1,
                max_retries=0,
            )
        )

        # No new API calls on second run
        assert len(provider2._calls) == 0
        assert manifest2.summary.complete == manifest1.summary.complete

    def test_pipeline_handles_partial_failure(
        self, tmp_path: Path, assets_config: AssetsConfig
    ) -> None:
        """Assets that fail are marked as failed, others succeed."""
        char1 = _make_character(
            char_id="char_001",
            name="Elena",
            description="Silver hair",
            sprite_variants=["neutral"],
        )
        char2 = _make_character(
            char_id="char_002",
            name="Marcus",
            description="Dark hair, tall, FAIL_THIS_ASSET",
            sprite_variants=["neutral"],
        )
        story = _make_story(
            characters={"char_001": char1, "char_002": char2},
            scenes=[_make_scene()],
        )

        provider = MockImageProvider(fail_on={"FAIL_THIS_ASSET"})

        manifest = asyncio.run(
            run_asset_pipeline(
                story=story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                concurrency=1,
                max_retries=0,
            )
        )

        assert manifest.summary.failed >= 1
        assert manifest.summary.complete >= 1

    def test_pipeline_characters_only(
        self, tmp_path: Path, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        provider = MockImageProvider()
        manifest = asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                characters_only=True,
                concurrency=1,
                max_retries=0,
            )
        )
        # All assets should be sprites
        for entry in manifest.assets.values():
            assert entry.type == AssetType.SPRITE

    def test_pipeline_backgrounds_only(
        self, tmp_path: Path, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        provider = MockImageProvider()
        manifest = asyncio.run(
            run_asset_pipeline(
                story=sample_story,
                image_provider=provider,
                config=assets_config,
                output_dir=tmp_path,
                backgrounds_only=True,
                concurrency=1,
                max_retries=0,
            )
        )
        for entry in manifest.assets.values():
            assert entry.type == AssetType.BACKGROUND


class TestDryRunPlan:
    def test_returns_all_requests(
        self, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        plan = build_dry_run_plan(sample_story, assets_config)
        assert len(plan) > 0

    def test_filters_by_manifest(
        self, sample_story: Story, assets_config: AssetsConfig
    ) -> None:
        # Get full plan
        full_plan = build_dry_run_plan(sample_story, assets_config)
        assert len(full_plan) > 0

        # Create manifest with first asset complete
        manifest = AssetManifestSchema()
        manifest.assets[full_plan[0].asset_id] = AssetEntry(
            type=AssetType.BACKGROUND, status=AssetStatus.COMPLETE
        )

        filtered = build_dry_run_plan(sample_story, assets_config, manifest=manifest)
        assert len(filtered) == len(full_plan) - 1
