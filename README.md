# CESI-Scraper

Récupère un **bloc de cours CESI** (plateforme Scenari/Opale, `scenari.cesi.fr`) et le dépose en **Markdown propre** dans le vault Obsidian — matière première d'une synthèse rédigée ensuite.

## Documentation
- [`README.md`](README.md) — installation et usage (ce fichier).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — comment ça marche (plateforme Scenari, `session.txt`, pipeline).
- [`AGENTS.md`](AGENTS.md) — cadrage, décisions et contrat de sortie vers le vault.

## Comment ça marche

Tout le contenu d'un bloc tient dans un seul fichier `session.txt` (JSON) à la racine du bloc ; le HTML des pages n'est qu'un squelette rempli par JavaScript. Le scraper reproduit ce remplissage côté Python — **pas de navigateur headless**. Il :

1. lit `index.html` (titre + menu `outCat` = pages du bloc, dans l'ordre) ;
2. télécharge `session.txt` et réassemble chaque page (en résolvant les renvois `phase → url`) ;
3. convertit le HTML en Markdown (maths `\(…\)` → `$…$`, code `data-lang` → bloc clôturé, images téléchargées en local, …) ;
4. écrit `CESI/{Année}/{Bloc}/_src/NN-page.md`, crée `{Bloc}.md` depuis `Templates/Bloc CESI.md`, et ajoute le `[[wikilink]]` dans `CESI.md`.

## Installation

```bash
# venv (si besoin : sudo apt install python3-venv)
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# pour l'app fenêtre (Tkinter) :
sudo apt install python3-tk
```

## App (fenêtre) — recommandé

Une petite fenêtre desktop : tu colles le cURL, le vault est pré-rempli, tu cliques **Scraper**.

```bash
./cesi-scraper.sh          # ou : .venv/bin/python gui.py
```

Une entrée **CESI-Scraper** est aussi installée dans le **menu Démarrer de Windows** (via WSLg, fichier `~/.local/share/applications/cesi-scraper.desktop`) — tu peux la lancer d'un clic.

L'app mémorise le cURL (dans `auth.curl`, gitignoré) et le chemin du vault (`gui_config.json`) ; au prochain lancement tout est pré-rempli, tu n'as qu'à recoller un cURL frais quand le token a expiré.

## Authentification

Le contenu est derrière un unique cookie de session **`distTk`**. Pour le fournir :

1. Ouvre une page de cours Scenari dans ton navigateur (connecté).
2. DevTools (F12) → **Réseau** → recharge → clic droit sur la requête `index.html` → **Copier → Copier comme cURL (bash)**.
3. Colle-le dans un fichier **`auth.curl`** à la racine (gitignoré). Le scraper en extrait `distTk` + le `User-Agent`.

Alternative plus courte : `export SCENARI_DISTTK=<token>`.

> Le token expire au bout de quelques semaines. Si une requête revient en `403`, recolle un cURL frais. Pas d'automatisation complète : minter un token demanderait de rejouer tout le SSO CAS/LTI (fragile, mot de passe stocké) — pour un geste aussi rare, le copier-coller suffit.

## Usage

```bash
# URL de l'index d'un bloc
.venv/bin/python scrape.py "https://scenari.cesi.fr/scenari/cas/<SLUG>/index.html"

.venv/bin/python scrape.py "<url>" --dry-run         # n'écrit rien, montre le plan
.venv/bin/python scrape.py "<url>" --vault /tmp/test  # vault de test
.venv/bin/python scrape.py                            # URL déduite de auth.curl
```

Options : `--vault` (défaut `/mnt/x/Obsidian/Obsidian Vault`, ou `$CESI_VAULT`), `--auth`, `--dry-run`.

Le scraper **n'écrase jamais** une note de synthèse `{Bloc}.md` déjà rédigée ; il rafraîchit `_src/` et les images.

## Limites connues

- Les **tableaux complexes** (cellules fusionnées) sont rendus au mieux par `markdownify`.
- Les liens vers des ressources du cours (`res/*.pdf`, sous-pages) sont **absolutisés** en URL Scenari : cliquables dans le navigateur (où l'on est connecté), et surtout ils n'amènent plus Obsidian à créer des notes fantômes.
- Les **QCM** sont rendus en best-effort.
