"""Configuration persistence tests."""

from pathlib import Path

from aorctodss_service.configuration import ServiceConfiguration


def test_configuration_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    config = ServiceConfiguration(
        workspace=str(tmp_path / "work"),
        cache=str(tmp_path / "cache"),
        max_concurrent_downloads=3,
    )
    config.save(path)
    loaded = ServiceConfiguration.load(path)
    assert loaded == config
    loaded.ensure_directories()
    assert Path(loaded.workspace).is_dir()
    assert Path(loaded.cache).is_dir()
