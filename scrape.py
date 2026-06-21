#!/usr/bin/env python3
"""CESI-Scraper — récupère un bloc de cours CESI (Scenari/Opale) → Markdown propre dans le vault Obsidian.

Mécanique (constatée, cf. AGENTS.md) :
  - Chaque bloc vit sous https://scenari.cesi.fr/scenari/cas/{SLUG}/
  - index.html porte le menu <nav id="outCat"> (ordre + titres des pages du bloc).
  - TOUT le contenu textuel du bloc tient dans un seul JSON `session.txt`,
    indexé par page → section (classe CSS) → {text|url, date}.
    Le HTML des pages n'est qu'un squelette ; le JS `fragments.js` réinjecte
    les `text` dans les `.part_co`. Ce script reproduit cette logique côté Python.
  - Auth = un unique cookie de session `distTk`.

Usage CLI :
  python scrape.py "<url_index_du_bloc>"            # écrit dans le vault
  python scrape.py "<url>" --vault /tmp/test --dry-run
  python scrape.py                                   # url déduite de auth.curl

Réutilisable par gui.py : parse_curl_text(), scrape(..., log=callback), ScrapeError.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
DEFAULT_VAULT = "/mnt/x/Obsidian/Obsidian Vault"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# data-lang MIME (CodeMirror) → langage de bloc fence Markdown
MIME2LANG = {
    "text/javascript": "js", "application/javascript": "js",
    "text/x-sql": "sql", "text/x-sh": "bash", "application/x-sh": "bash",
    "application/json": "json", "text/x-yaml": "yaml", "application/x-yaml": "yaml",
    "text/html": "html", "text/css": "css",
    "text/x-python": "python", "text/x-java": "java", "text/x-csrc": "c",
    "text/x-c++src": "cpp", "text/x-stex": "", "text/plain": "",
}

# Squelette de note de bloc (miroir de Templates/Bloc CESI.md ; secours si le
# template du vault est introuvable).
BLOC_TEMPLATE = """\
---
type: bloc
year:
program:
status: not-started
source_url:
updated:
tags: [cesi, cours]
---

## Vue d'ensemble
Durée, modalité (mini-prosit, workshop…), modalité d'évaluation.

## Plan du bloc
Liste complète des séances / mini-boucles du bloc.
-

## Synthèse
Notions clés, rédigées à partir des pages dans `_src/`.

## À revoir / questions ouvertes
-
"""
PLAN_ANCHOR = "Liste complète des séances / mini-boucles du bloc.\n-"

# Soup vierge servant d'usine à balises (création de <p> placeholder).
_FACTORY = BeautifulSoup("", "html.parser")


class ScrapeError(Exception):
    """Erreur métier remontée à l'appelant (CLI ou GUI) plutôt que sys.exit."""


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def parse_curl_text(raw: str) -> tuple[str | None, str, str | None]:
    """Extrait (distTk, user_agent, url_index) d'un texte « Copier comme cURL »."""
    m = re.search(r"distTk=([^;'\"\s]+)", raw)
    disttk = m.group(1) if m else None
    m = re.search(r"-H\s+['\"]User-Agent:\s*([^'\"]+)['\"]", raw, re.I)
    ua = m.group(1).strip() if m else DEFAULT_UA
    m = re.search(r"curl\s+['\"](https?://[^'\"]+)['\"]", raw)
    if not m:  # secours : n'importe quelle URL Scenari du texte
        m = re.search(r"(https?://scenari\.cesi\.fr/[^'\"\s]+)", raw)
    url = m.group(1) if m else None
    return disttk, ua, url


def load_auth(curl_path: Path) -> tuple[str, str, str | None]:
    """(distTk, user_agent, url) depuis l'env puis auth.curl. sys.exit si pas de token (CLI)."""
    disttk = os.environ.get("SCENARI_DISTTK")
    ua = os.environ.get("SCENARI_UA", DEFAULT_UA)
    url = None
    if curl_path.exists():
        d, u, url = parse_curl_text(curl_path.read_text(encoding="utf-8", errors="replace"))
        disttk = disttk or d
        ua = u or ua
    if not disttk:
        sys.exit("✗ Aucun token `distTk`. Renseigne auth.curl (cf. auth.curl.example) "
                 "ou export SCENARI_DISTTK=…")
    return disttk, ua, url


def make_session(disttk: str, ua: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("distTk", disttk, domain="scenari.cesi.fr")
    s.headers.update({"User-Agent": ua,
                      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    return s


def fetch(session: requests.Session, url: str, *, binary: bool = False):
    r = session.get(url, timeout=30)
    if r.status_code == 403:
        raise ScrapeError(f"403 sur {url} — cookie `distTk` expiré ou invalide. "
                          "Recolle un « Copier comme cURL » frais.")
    r.raise_for_status()
    # Les ressources Scenari sont en UTF-8 ; requests retombe sinon en latin-1 (mojibake).
    return r.content if binary else r.content.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Slug & métadonnées
# --------------------------------------------------------------------------- #
def parse_slug(index_url: str) -> dict:
    """year / program / filière depuis le SLUG de l'URL.

    Variantes : Etudiant_PGE_A3_FISE_Sciences_..._2526  et  PGE_A3_FISA_INFO_Developpement_..._ETU
    """
    parts = urlparse(index_url).path.rstrip("/").split("/")
    slug = parts[-2] if parts[-1].endswith(".html") else parts[-1]
    tokens = slug.split("_")
    year = next((t.lower() for t in tokens if re.fullmatch(r"[Aa]\d", t)), "")
    formation = next((t.lower() for t in tokens if t.upper() in ("FISE", "FISA")), "")
    program = "-".join(p for p in ("pge", year, formation) if p)
    filiere = ""
    try:
        i = [t.upper() for t in tokens].index(formation.upper())
        nxt = tokens[i + 1]
        if re.fullmatch(r"[A-Z]{2,6}", nxt):
            filiere = nxt.lower()
    except (ValueError, IndexError):
        pass
    return {"slug": slug, "year": year, "program": program, "filiere": filiere}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "page"


def safe_name(text: str) -> str:
    """Nom de fichier/dossier lisible (garde accents) sans caractères interdits."""
    return re.sub(r'[\\/:*?"<>|]', "-", text).strip().rstrip(".")


# --------------------------------------------------------------------------- #
# Menu & assemblage (port de fragments.js / displayBlocks)
# --------------------------------------------------------------------------- #
def parse_menu(index_soup: BeautifulSoup, bloc_title: str) -> list[tuple[str, str]]:
    """[(href, label)] des pages du bloc, dans l'ordre du menu outCat."""
    nav = index_soup.find("nav", id="outCat")
    items = []
    for a in nav.select("li > a") if nav else []:
        href = a.get("href", "")
        if not href or "confPrj" in href or "~config" in href:
            continue
        label = bloc_title if href.endswith("index.html") else a.get_text(strip=True)
        items.append((href, label))
    return items


def fill(scope: Tag, page: str, session_data: dict) -> None:
    """Réinjecte récursivement le contenu de `page` dans les `.part_co` de `scope`."""
    entry = session_data.get(page)
    if not isinstance(entry, dict):
        return
    for key, info in entry.items():
        if not key or not isinstance(info, dict):
            continue
        section = scope.find(class_=key)
        if section is None:
            continue
        part_co = section.find(class_="part_co")
        if part_co is None:
            continue
        text = info.get("text")
        if text:
            frag = BeautifulSoup(text, "html.parser")
            for article in frag.find_all("article"):
                for child in list(article.children):
                    part_co.append(child.extract() if isinstance(child, Tag) else child)
        elif "phase" in key and info.get("url"):
            fill(part_co, info["url"], session_data)


def prune_empty(content: Tag) -> None:
    """Supprime les sections dont le corps reste vide après assemblage."""
    for section in content.select("section.part"):
        co = section.find(class_="part_co")
        if co is not None and not co.get_text(strip=True) and not co.find(["img", "figure", "table"]):
            section.decompose()


# --------------------------------------------------------------------------- #
# HTML → Markdown
# --------------------------------------------------------------------------- #
class Converter:
    def __init__(self, base_url: str, downloader):
        self.base = base_url
        self.download = downloader
        self._ph: dict[str, str] = {}

    def _token(self, md: str) -> str:
        tok = f"@@CESIPH{len(self._ph)}@@"
        self._ph[tok] = md
        return tok

    def _block(self, el: Tag, md: str) -> None:
        p = _FACTORY.new_tag("p")
        p.string = self._token(md)
        el.replace_with(p)

    def run(self, content: Tag) -> str:
        self._code(content)
        self._math(content)
        self._figures(content)
        self._links(content)
        md = markdownify(str(content), heading_style="ATX", bullets="-",
                         escape_asterisks=False, escape_underscores=False,
                         strip=["script", "style"])
        for tok, val in self._ph.items():
            md = md.replace(tok, val)
        # Liens d'ancre internes vides [texte](#…) → texte seul (inutiles dans Obsidian)
        md = re.sub(r"(?<!!)\[([^\]]+)\]\(#[^)]*\)", r"\1", md)
        return tidy(md)

    def _code(self, content: Tag) -> None:
        for div in content.select("div.code"):
            static = div.find(attrs={"data-lang": True})
            lang = MIME2LANG.get(static["data-lang"], "") if static else ""
            lines = [pre.get_text() for pre in div.select(".CodeMirror-line > pre")]
            code = "\n".join(lines).rstrip() if lines else div.get_text("\n").rstrip()
            self._block(div, f"```{lang}\n{code}\n```")

    def _math(self, content: Tag) -> None:
        for span in content.select('[class*="mathtex"]'):
            raw = span.get_text().strip()
            if "\\[" in raw or "\\]" in raw:
                inner = re.sub(r"\\\[|\\\]", "", raw).strip()
                md = f"$${inner}$$"
            else:
                inner = re.sub(r"\\\(|\\\)", "", raw).strip()
                md = f"${inner}$"
            span.replace_with(NavigableString(self._token(md)))

    def _figures(self, content: Tag) -> None:
        for fig in content.select("figure"):
            link = fig.find("a", href=True)
            img = fig.find("img")
            src = (link["href"] if link else None) or (img.get("src") if img else None)
            if not src:
                continue
            md = self._img_md(src, img.get("alt", "") if img else "")
            cap = fig.find("figcaption") or fig.find(class_="capTi")
            if cap and cap.get_text(strip=True):
                md += f"\n*{cap.get_text(' ', strip=True)}*"
            self._block(fig, md)
        for img in content.select("img"):  # images hors figure
            src = img.get("src")
            if src:
                img.replace_with(NavigableString(self._token(self._img_md(src, img.get("alt", "")))))

    def _img_md(self, src: str, alt: str) -> str:
        url = urljoin(self.base, src)
        local = self.download(url)
        return f"![[{local}]]" if local else f"[{alt or 'figure'}]({url})"

    def _links(self, content: Tag) -> None:
        """Absolutise les liens relatifs (ressources/sous-pages Scenari).

        Sinon Obsidian, au clic, crée une note fantôme à la racine du vault.
        Absolus → ouverts dans le navigateur (où l'utilisateur est connecté).
        """
        for a in content.find_all("a", href=True):
            href = a["href"]
            if not re.match(r"^(https?:|mailto:|#)", href):
                a["href"] = urljoin(self.base, href)


def tidy(md: str) -> str:
    md = "\n".join(line.rstrip() for line in md.splitlines())
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# --------------------------------------------------------------------------- #
# Téléchargement d'images
# --------------------------------------------------------------------------- #
class ImageDownloader:
    def __init__(self, session, attach_dir: Path, dry_run: bool, log=print):
        self.session = session
        self.dir = attach_dir
        self.dry = dry_run
        self.log = log
        self.seen: dict[str, str] = {}   # url → nom local
        self.used: set[str] = set()      # noms déjà attribués

    def __call__(self, url: str) -> str | None:
        if url in self.seen:
            return self.seen[url]
        name = safe_name(os.path.basename(urlparse(url).path)) or "image"
        if name in self.used:                       # collision de basename
            stem, ext = os.path.splitext(name)
            i = 2
            while f"{stem}-{i}{ext}" in self.used:
                i += 1
            name = f"{stem}-{i}{ext}"
        try:
            if not self.dry:
                data = fetch(self.session, url, binary=True)
                self.dir.mkdir(parents=True, exist_ok=True)
                (self.dir / name).write_bytes(data)
        except Exception as e:                       # noqa: BLE001
            self.log(f"  ⚠ image non récupérée ({url}): {e}")
            return None
        self.seen[url] = name
        self.used.add(name)
        return name


# --------------------------------------------------------------------------- #
# Écriture vault
# --------------------------------------------------------------------------- #
def load_template(vault: Path) -> str:
    tpl = vault / "Templates" / "Bloc CESI.md"
    return tpl.read_text(encoding="utf-8") if tpl.exists() else BLOC_TEMPLATE


def write_bloc_note(bloc_dir, title, meta, index_url, menu, vault, today, dry, log=print):
    note = bloc_dir / f"{title}.md"
    if note.exists():
        log(f"  = note de synthèse déjà présente, conservée : {note.name}")
        return
    plan = "\n".join(f"- {label}" for href, label in menu if not href.endswith("index.html"))
    content = load_template(vault)
    content = re.sub(r"^year:.*$", f"year: {meta['year']}", content, count=1, flags=re.M)
    content = re.sub(r"^program:.*$", f"program: {meta['program']}", content, count=1, flags=re.M)
    content = re.sub(r"^source_url:.*$", f"source_url: {index_url}", content, count=1, flags=re.M)
    content = re.sub(r"^updated:.*$", f"updated: {today}", content, count=1, flags=re.M)
    if "{{date}}" in content:
        content = content.replace("{{date}}", today)
    if plan and PLAN_ANCHOR in content:
        content = content.replace(PLAN_ANCHOR, PLAN_ANCHOR[:-1] + plan, 1)
    if not dry:
        note.write_text(content, encoding="utf-8")
    log(f"  + note de synthèse : {note.name}")


def update_cesi_index(vault, year, title, dry, log=print):
    cesi = vault / "CESI" / "CESI.md"
    if not cesi.exists():
        log("  ⚠ CESI.md introuvable, wikilink non ajouté.")
        return
    lines = cesi.read_text(encoding="utf-8").splitlines()
    header = f"## {year.upper()}"
    link = f"- [[{title}]]"
    try:
        h = next(i for i, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        log(f"  ⚠ section {header} absente de CESI.md.")
        return
    end = next((i for i in range(h + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    block = lines[h + 1:end]
    if any(link == l.strip() for l in block):
        log("  = wikilink déjà présent dans CESI.md")
        return
    # Garde l'ordre existant (l'utilisateur gère l'ordre des blocs à la main) ;
    # ajoute simplement le nouveau bloc en fin de section.
    block = [l for l in block if l.strip() and "_(aucun bloc" not in l]
    new_block = block + [link]
    lines[h + 1:end] = [""] + new_block + [""]
    if not dry:
        cesi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"  + wikilink [[{title}]] sous {header} dans CESI.md")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def scrape(index_url: str, vault: Path, disttk: str, ua: str = DEFAULT_UA,
           dry: bool = False, log=print) -> Path:
    """Scrape un bloc. `log` reçoit chaque ligne de progression. Lève ScrapeError."""
    session = make_session(disttk, ua)
    base = index_url.rsplit("/", 1)[0] + "/"
    today = dt.date.today().isoformat()

    log(f"→ Index : {index_url}")
    index_soup = BeautifulSoup(fetch(session, index_url), "html.parser")
    bloc_title = safe_name(index_soup.title.get_text(strip=True)) if index_soup.title else "Bloc"
    meta = parse_slug(index_url)
    menu = parse_menu(index_soup, bloc_title)
    log(f"  bloc « {bloc_title} » — year={meta['year']} program={meta['program']}"
        + (f" filière={meta['filiere']}" if meta["filiere"] else ""))
    log(f"  {len(menu)} page(s) au menu")

    session_data = json.loads(fetch(session, urljoin(base, "session.txt")))

    bloc_dir = vault / "CESI" / meta["year"].upper() / bloc_title
    src_dir = bloc_dir / "_src"
    downloader = ImageDownloader(session, bloc_dir / "attachments", dry, log)
    if not dry:
        src_dir.mkdir(parents=True, exist_ok=True)

    for n, (href, label) in enumerate(menu):
        page = href.split("/")[-1]
        page_url = urljoin(base, href)
        page_soup = BeautifulSoup(fetch(session, page_url), "html.parser")
        main = page_soup.find("main") or page_soup
        content = main.find(id="content")
        if content is None:
            log(f"  ⚠ #content absent sur {page}, ignoré")
            continue
        fill(content, page, session_data)
        prune_empty(content)
        body = Converter(page_url, downloader).run(content)
        fname = "00-index.md" if href.endswith("index.html") else f"{n:02d}-{slugify(label)}.md"
        doc = f"# {label}\n\n*Source : {page_url}*\n\n{body}"
        if not dry:
            (src_dir / fname).write_text(doc, encoding="utf-8")
        log(f"  + _src/{fname}  ({len(body)} car.)")

    write_bloc_note(bloc_dir, bloc_title, meta, index_url, menu, vault, today, dry, log)
    update_cesi_index(vault, meta["year"], bloc_title, dry, log)
    log(f"✓ Terminé{' (DRY-RUN, rien écrit)' if dry else ''} — "
        f"{len(menu)} pages, {len(downloader.seen)} image(s) → {bloc_dir}")
    return bloc_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape un bloc CESI (Scenari) → Markdown dans le vault.")
    ap.add_argument("url", nargs="?", help="URL de l'index du bloc (sinon déduite de auth.curl).")
    ap.add_argument("--vault", default=os.environ.get("CESI_VAULT", DEFAULT_VAULT),
                    help=f"Racine du vault Obsidian (défaut : {DEFAULT_VAULT}).")
    ap.add_argument("--auth", default="auth.curl", help="Chemin du fichier auth.curl.")
    ap.add_argument("--dry-run", action="store_true", help="N'écrit rien, affiche seulement.")
    args = ap.parse_args()

    auth_path = Path(args.auth)
    disttk, ua, url_curl = load_auth(auth_path)
    url = args.url or url_curl
    if not url:
        sys.exit("✗ Aucune URL fournie et aucune trouvée dans auth.curl.")
    try:
        scrape(url, Path(args.vault), disttk, ua, args.dry_run)
    except ScrapeError as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
