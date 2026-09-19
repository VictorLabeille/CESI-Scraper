# CESI-Scraper

**Pull a whole CESI course block into clean Markdown, without a browser.**

CESI publishes its courses through Scenari/Opale on `scenari.cesi.fr`. This tool reads one block
and writes it into an Obsidian vault, one Markdown file per page, images included — the raw
material for revision notes written afterwards.

> ⚠️ **Personal tool.** It fetches **my own courses**, through **my own CESI session**, to make my
> own revision notes. **No course content is redistributed here** — this repository holds code and
> nothing else; the session token and the notes stay local. If you reuse it, respect your
> platform's terms of service and the copyright of the material.

## The trick

The HTML pages of a block are empty shells. Every line of text lives in a **single JSON file**,
`session.txt`, at the root of the block, and JavaScript injects it into the page at load time.

So there is no need to drive a browser: the scraper reproduces that injection in Python. It reads
the block's index for the page order, downloads `session.txt` once, resolves the cross-references
between container pages and leaf pages, and converts what comes out — inline maths to `$…$`, code
blocks with their language, figures downloaded at full resolution.

The result lands in `CESI/{Year}/{Block}/_src/`, and a synthesis note is created from the vault's
template. **An existing synthesis is never overwritten**; only the source material is refreshed.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo apt install python3-tk        # for the window app
```

## Use it

A small desktop window — paste the cURL, the vault path is remembered, click **Scraper**:

```bash
./cesi-scraper.sh          # or: .venv/bin/python gui.py
```

Under WSLg it also installs as a **CESI-Scraper** entry in the Windows start menu.

Or from the command line, with the URL of a block index:

```bash
.venv/bin/python scrape.py "https://scenari.cesi.fr/scenari/cas/<SLUG>/index.html"
.venv/bin/python scrape.py "<url>" --dry-run          # show the plan, write nothing
.venv/bin/python scrape.py "<url>" --vault /tmp/test  # a throwaway vault
.venv/bin/python scrape.py                            # URL taken from auth.curl
```

## Authentication

Everything sits behind one session cookie, `distTk`. To hand it over:

1. Open a course page in your browser, logged in.
2. DevTools → **Network** → reload → right-click the `index.html` request → **Copy as cURL (bash)**.
3. Paste it into `auth.curl` at the repository root (git-ignored). The token and the user agent are
   read from there.

Shorter alternative: `export SCENARI_DISTTK=<token>`.

The token lasts a few weeks. On a `403`, paste a fresh cURL. Minting one automatically would mean
replaying the whole CAS/LTI single sign-on and storing a password — too fragile a machine for a
gesture this rare.

## Known limits

Tables with merged cells are converted best-effort, and so are quizzes. Links to course resources
are rewritten as absolute Scenari URLs: clickable in the browser where you are logged in, and no
longer turning into phantom notes in Obsidian.

## Repository map

| Path | What is there |
| --- | --- |
| `scrape.py` | The scraper: fetch, reassemble, convert, write |
| `gui.py`, `cesi-scraper.sh` | The window app and its launcher |
| `docs/ARCHITECTURE.md` | How the platform works, what is in `session.txt`, the pipeline step by step |
| `AGENTS.md` | Conventions, scope and the output contract towards the vault |

Documentation is in French; this page is not.

## Licence

[MIT](LICENSE).
