"""Homepage: alle Seiten gebaut, keine offenen Platzhalter, kein Inline-JavaScript, Registrierung nur mit Impressum."""

import datetime as dt
import re

from tools import site

LEGAL = {"owner_name": "Alex Kulow", "owner_address": "Weg 1\n12345 Ort", "owner_email": "k@example.de"}


def build(tmp_path, **site_cfg):
    cfg = {"github": "Kulow00/AkustikMess", "site": site_cfg}
    return site.build(tmp_path, cfg, today=dt.date(2026, 10, 16)), tmp_path


def test_all_pages_and_wiki(tmp_path):
    warnings, out = build(tmp_path, **LEGAL)
    assert warnings == []
    pages = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html"))
    for name in ("index.html", "registrieren.html", "datenschutz.html", "impressum.html", "wiki/index.html",
                 "wiki/erste-schritte.html", "wiki/lizenz.html", "wiki/fehlerbehebung.html"):
        assert name in pages
    for p in out.rglob("*.html"):
        text = p.read_text(encoding="utf-8")
        assert "{{" not in text, p
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text), f"Inline-Script in {p}"   # CSP
        assert " style=" not in text, f"Inline-Style in {p}"
        assert "https://github.com/Kulow00/AkustikMess-Feedback" in text
    imp = (out / "impressum.html").read_text(encoding="utf-8")
    assert "Weg 1<br>12345 Ort" in imp and "mailto:k@example.de" in imp
    wiki = (out / "wiki" / "echtzeit.html").read_text(encoding="utf-8")
    assert "<table>" in wiki or "<h2>" in wiki
    assert 'href="../assets/style.css"' in wiki and 'class="on"' in wiki


def test_registration_needs_legal_info(tmp_path):
    warnings, out = build(tmp_path / "a", registration=True)
    assert warnings and 'data-enabled="false"' in (out / "registrieren.html").read_text(encoding="utf-8")
    assert "werden gerade ergänzt" in (out / "impressum.html").read_text(encoding="utf-8")
    warnings, out = build(tmp_path / "b", registration=True, **LEGAL)
    assert not warnings and 'data-enabled="true"' in (out / "registrieren.html").read_text(encoding="utf-8")
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "Lizenz anfragen" in idx and "Ich habe eine Lizenz" in idx and "/api/file/" not in idx


def test_config_values_are_escaped(tmp_path):
    _, out = build(tmp_path, **dict(LEGAL, owner_name="<script>x</script>"))
    assert "<script>x</script>" not in (out / "impressum.html").read_text(encoding="utf-8")
