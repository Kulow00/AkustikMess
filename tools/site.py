"""Homepage bauen: Startseite mit Download, Wiki (aus docs/wiki/*.md), Lizenz/Registrierung,
Datenschutz und Impressum. Ergebnis: statische Dateien im Veröffentlichungsordner.

Einstellungen in release_config.json unter "site"::

    "site": {
      "owner_name": "Alex Kulow",
      "owner_address": "Straße 1\\n12345 Ort",
      "owner_email": "kontakt@alex-kulow.de",
      "mail_provider": "den E-Mail-Dienst von … (Auftragsverarbeitung)",
      "registration": false          # erst einschalten, wenn der Lizenzserver läuft
    }

Solange Impressum-Angaben fehlen, zeigen Impressum/Datenschutz einen Hinweis und die Registrierung bleibt aus.
Seiten enthalten kein Inline-JavaScript (strenge Content-Security-Policy möglich).
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
WIKI_DIR = ROOT / "docs" / "wiki"
LEGAL_KEYS = ("owner_name", "owner_address", "owner_email")


def settings(cfg: dict) -> dict:
    s = dict(cfg.get("site") or {})
    s.setdefault("mail_provider", "unseren E-Mail-Anbieter")
    s.setdefault("log_days", 7)
    s.setdefault("registration", False)
    return s


def missing_legal(cfg: dict) -> list[str]:
    s = settings(cfg)
    return [k for k in LEGAL_KEYS if not str(s.get(k, "")).strip()]


def _meta(page: str) -> tuple[dict, str]:
    meta = {}
    for m in re.finditer(r"^<!--\s*(\w+)(?::\s*(.*?))?\s*-->\s*$", page, re.M):
        meta[m.group(1)] = m.group(2) if m.group(2) is not None else True
    body = re.sub(r"^<!--\s*\w+(?::.*?)?\s*-->\s*\n", "", page, flags=re.M)
    return meta, body


def _fill(text: str, values: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def _render(layout: str, body: str, meta: dict, values: dict, root: str, nav: str) -> str:
    scripts = "".join(f'<script src="{root}{html.escape(s.strip())}" defer></script>'
                      for s in str(meta.get("scripts", "") or "").split(",") if s.strip())
    page_values = dict(values, root=root, title=html.escape(str(meta.get("title", "AkustikMess"))),
                       scripts=scripts, main_class=" narrow" if meta.get("narrow") else "",
                       nav_download="", nav_wiki="", nav_register="")
    if nav:
        page_values[f"nav_{nav}"] = ' class="on"'
    page_values["content"] = _fill(body, page_values)
    out = _fill(layout, page_values)
    leftover = re.findall(r"\{\{\w+\}\}", out)
    if leftover:
        raise ValueError(f"Platzhalter ohne Wert: {sorted(set(leftover))}")
    return out


def wiki_pages(wiki_dir: Path = WIKI_DIR) -> list[dict]:
    pages = []
    for f in sorted(wiki_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), f.stem)
        first = next((p.strip() for p in text.split("\n\n")[1:] if p.strip() and not p.startswith(("#", "|", "-", "`"))), "")
        pages.append({"slug": re.sub(r"^\d+-", "", f.stem), "title": title, "md": text,
                      "summary": re.sub(r"[*`\[\]]|\(.*?\)", "", first.replace("\n", " "))[:160]})
    return pages


def build(out: Path, cfg: dict, today: dt.date | None = None) -> list[str]:
    """Baut die Seite nach ``out``. Liefert Warnungen (z. B. fehlende Impressum-Angaben)."""
    import markdown  # noqa: PLC0415 – nur für das Release-Werkzeug nötig

    s = settings(cfg)
    warnings = []
    missing = missing_legal(cfg)
    if missing:
        warnings.append("Impressum/Datenschutz unvollständig (release_config.json → site: "
                        + ", ".join(missing) + ") – Registrierung bleibt ausgeschaltet.")
    registration = bool(s["registration"]) and not missing
    repo = cfg.get("github", "")
    esc = {k: html.escape(str(s.get(k, "") or "")) for k in LEGAL_KEYS}
    values = {
        "repo": repo,
        "repo_url": f"https://github.com/{repo}" if repo else "https://github.com",
        "feedback_url": "https://github.com/" + (cfg.get("feedback_repo") or "Kulow00/AkustikMess-Feedback"),
        "owner_name": esc["owner_name"] or "AkustikMess",
        "owner_address": esc["owner_address"].replace("\n", "<br>") or "–",
        "owner_email": (f'<a href="mailto:{esc["owner_email"]}">{esc["owner_email"]}</a>'
                        if esc["owner_email"] else "–"),
        "mail_provider": html.escape(str(s["mail_provider"])),
        "log_days": html.escape(str(s["log_days"])),
        "today": (today or dt.date.today()).strftime("%d.%m.%Y"),
        "legal_notice": ('<p class="notice">Die Angaben auf dieser Seite werden gerade ergänzt.</p>'
                         if missing else ""),
        "registration_enabled": "true" if registration else "false",
        "register_teaser": "",
    }
    layout = (SITE_DIR / "layout.html").read_text(encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)

    nav_of = {"index": "download", "registrieren": "register"}
    for f in sorted((SITE_DIR / "pages").glob("*.html")):
        meta, body = _meta(f.read_text(encoding="utf-8"))
        (out / f.name).write_text(_render(layout, body, meta, values, "", nav_of.get(f.stem, "")), encoding="utf-8")

    # Nutzungsbedingungen direkt aus der LICENSE-Datei (eine Quelle für Programm, Bundle und Website)
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8").replace("{{", "&#123;&#123;")
    body = f'<h1>Nutzungsbedingungen</h1><pre class="license">{html.escape(lic)}</pre>'
    (out / "nutzungsbedingungen.html").write_text(
        _render(layout, body, {"title": "Nutzungsbedingungen", "narrow": True}, values, "", ""), encoding="utf-8")

    # Wiki
    pages = wiki_pages()
    wdir = out / "wiki"
    wdir.mkdir(exist_ok=True)

    def wiki_nav(active: str) -> str:
        links = [f'<a href="index.html"{" class=\"on\"" if active == "index" else ""}>Übersicht</a>']
        links += [f'<a href="{p["slug"]}.html"{" class=\"on\"" if p["slug"] == active else ""}>'
                  f'{html.escape(p["title"])}</a>' for p in pages]
        return "<nav>" + "".join(links) + "</nav>"

    for p in pages:
        md_text = p["md"].replace("{{repo}}", repo)
        body_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"], output_format="html5")
        body = f'<div class="wiki">{wiki_nav(p["slug"])}<article>{body_html.replace("{{", "&#123;&#123;")}</article></div>'
        (wdir / f'{p["slug"]}.html').write_text(_render(layout, body, {"title": p["title"]}, values, "../", "wiki"),
                                                encoding="utf-8")
    overview = "".join(f'<div class="card"><h3><a href="{p["slug"]}.html">{html.escape(p["title"])}</a></h3>'
                       f'{html.escape(p["summary"])}</div>' for p in pages)
    body = (f'<div class="wiki">{wiki_nav("index")}<article><h1>Wiki</h1><p class="lead">Anleitungen und Antworten '
            f'rund um AkustikMess.</p><div class="grid">{overview}</div></article></div>')
    (wdir / "index.html").write_text(_render(layout, body, {"title": "Wiki"}, values, "../", "wiki"), encoding="utf-8")

    assets = out / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(SITE_DIR / "assets", assets)
    return warnings
