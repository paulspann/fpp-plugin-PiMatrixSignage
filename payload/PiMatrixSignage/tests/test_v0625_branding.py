from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_customer_header_branding_is_hardware_neutral():
    for template in ("index.html", "login.html"):
        html = (ROOT / "templates" / template).read_text(encoding="utf-8")
        assert "P5/P10 LED signage controller" in html
        assert "Hanson rPI-MFC · P5/P10 LED display controller" not in html


def test_release_version_is_v0625_or_later():
    version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
    assert version >= (0, 6, 25)
