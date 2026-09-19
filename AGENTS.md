# AGENTS.md — CESI-Scraper

> Cadrage et décisions du projet. Lu en premier par tout agent ouvrant ce dépôt.
>
> **`README.md` est une vitrine, en anglais** : présentation et usage, sans état d'avancement.
> Le technique va dans `docs/`, l'avancement dans la note Obsidian. Ne pas le repasser en
> français ni y remettre de checklist.

## But
Outil qui récupère un **bloc de cours CESI** (plateforme Scenari/Opale, `https://scenari.cesi.fr`) et produit du **Markdown propre**, déposé dans le vault Obsidian, comme matière première d'une **synthèse rédigée ensuite par l'IA**.

Vault cible : `/mnt/x/Obsidian/Obsidian Vault/` (= `X:\Obsidian\Obsidian Vault`). Sa structure et ses conventions font autorité dans **son propre `AGENTS.md`** — s'y référer pour le format de sortie, ne pas diverger.

## Contexte plateforme (constaté & vérifié)
- Généré par **SCENARI 6.3.16 / OpaleCesiExtProblem**, diffusé via un **lecteur LTI**.
- ⚠️ Le fichier `player.xhtml` (Ctrl+S sur le lecteur) est une **coquille LTI vide**. **L'ignorer.**
- Le vrai contenu est sous `https://scenari.cesi.fr/scenari/cas/{SLUG}/` :
  - `index.html` = accueil du bloc : `<title>` = **titre du bloc** ; `<nav id="outCat">` = **menu** (ordre + titres des pages, dont `~config/confPrj.xml` à filtrer).
  - 🔑 **Tout le contenu textuel du bloc tient dans un seul JSON `cas/{SLUG}/session.txt`**, indexé `page → section (classe CSS) → {text|url, date}`. Le HTML des pages n'est qu'un **squelette** (titres de sections, `.part_co` vides) ; le JS `lib-md/w_fragments/fragments.js` (`displayBlocks`) y réinjecte les `text`. Les pages « Assemblage_* » sont des conteneurs dont les sections `phase_*` **renvoient (`url`) vers des pages-feuilles** (`Mini_prosit_*`, `Corbeille_*`, `Prosit_*`…) qui portent le vrai texte. Le scraper **reproduit `displayBlocks` en Python** — pas de navigateur.
  - Le `date` de chaque section = date de visibilité (contenu futur masqué dans le lecteur) ; le scraper prend tout.
  - Markup utile : `.rBk` (paragraphes), `.txt_il/.txt_ili` (listes), `div.code` (CodeMirror, `data-lang` = langage), maths MathJax inline `\(…\)` dans `span.txt_mathtex_tl`, `<figure class="resInFlow">` (vignette `…_1.png` + lien zoom pleine résolution), tables, liens YouTube/PDF externes.
- **Slug** (variable selon promo/formation) : `[Etudiant_]PGE_{A3|A4|A5}_{FISE|FISA}[_{FILIÈRE}]_{Nom_Du_Bloc}_{2526|ETU}`. Parsé en `year` (a3…), `program` (`pge-a3-fise`/`pge-a3-fisa`), filière optionnelle (ex. `INFO`). Le **titre** vient du `<title>` (pas dé-sluggé).
- **Auth** : un **unique cookie `distTk`** (posé par le lancement LTI ; ~quelques semaines de validité). 403 `scAuthFailed` sans lui. Pas de redirection CAS sur ces URLs.

## Décisions arrêtées
1. **Source = crawl live avec le cookie de session** de l'utilisateur : partir d'une URL d'index de bloc, lire le menu `outCat`, télécharger chaque sous-page avec le cookie. (Pas de Ctrl+S manuel ; `player.xhtml` ignoré.)
2. **Sortie = Markdown propre**, un fichier par page, dans `CESI/{Année}/{Bloc}/_src/` du vault (ex. `00-index.md`, `01-theorie-des-jeux.md`…). Conversion HTML→MD en ne gardant que `#content`.
3. **Pas de distinction fait/à-faire** : on capture tout le contenu ; la synthèse (IA) ira dans `{Bloc}.md` (`type: bloc`).
4. Le scraper vit dans ce dépôt.

## Contrat de sortie (vault)
- Arborescence cible : `CESI/{A3|A4|A5}/{Bloc}/` avec `{Bloc}.md` (synthèse) + `_src/` (Markdown scrapé).
- Frontmatter de `{Bloc}.md` (`type: bloc`) : `year` (a3/a4/a5), `program` (ex. `pge-a3-fise`), `status`, `source_url` (URL Scenari de l'index), `updated`, `tags: [cesi, cours]`.
- Règles détaillées : **`AGENTS.md` du vault** (source de vérité).

## Implémentation (`scrape.py`)
- **Stack** : Python `requests` + `BeautifulSoup` + `markdownify` (cf. `requirements.txt`). Pas de navigateur (le `session.txt` rend Playwright inutile). Installation + usage : `README.md`.
- **Auth** : cookie `distTk` lu depuis `auth.curl` (gitignoré, format « Copier comme cURL ») ou `$SCENARI_DISTTK`. 403 → message « recolle un cURL ».
- **Images** : téléchargées en local dans `attachments/` à côté de la note (choix arrêté avec l'utilisateur), embed `![[fichier]]`.
- **Sortie** : `_src/NN-page.md` (un par entrée de menu, contenu assemblé + converti), `{Bloc}.md` depuis le template (frontmatter rempli, « Plan du bloc » pré-rempli) **sans écraser** une synthèse existante, et wikilink idempotent dans `CESI.md`.
- Validé de bout en bout sur 2 blocs (FISE sciences + FISA dev). Limites connues : tableaux à cellules fusionnées, liens vers ressources relatives (`res/*.pdf`), QCM → cf. `README.md`.

## Style de collaboration
L'utilisateur **cadre et valide le design avant d'implémenter** (questions d'architecture, arbitrages explicites). Proposer une reco + le raisonnement, poser les vraies questions, n'écrire le code qu'après feu vert. Il tient aussi à des artefacts propres.
