from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_supports_fpp_plugin_dependency_mode():
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "PIMATRIX_SKIP_DEPENDENCY_INSTALL" in script
    assert "Dependency installation already handled by the FPP Plugin Manager" in script


def test_release_version_is_066_or_later():
    version = tuple(int(x) for x in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[:3])
    assert version >= (0, 6, 6)
