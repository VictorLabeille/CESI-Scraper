# Architecture

Comment CESI-Scraper récupère un bloc de cours et produit du Markdown. Pour les
décisions de conception et le contrat de sortie, voir [`../AGENTS.md`](../AGENTS.md) ;
pour l'usage, [`../README.md`](../README.md).

## La plateforme Scenari/Opale

Les cours sont publiés par **SCENARI 6.3.16** et diffusés dans un **lecteur LTI**
(lancé depuis le LMS). Deux pièges :

1. Le fichier `player.xhtml` (ce qu'on obtient avec Ctrl+S sur le lecteur) est une
   **coquille LTI vide** : il ne contient aucun cours, juste de quoi charger le
   contenu dynamiquement. On l'ignore.
2. Les pages `cas/{SLUG}/*.html` ne sont que des **squelettes** : elles décrivent la
   structure (titres de sections `.part_ti`, conteneurs `.part_co` **vides**) mais
   pas le texte.

### Le fichier `session.txt` — la clé

Tout le contenu textuel d'un bloc tient dans **un seul JSON** :
`https://scenari.cesi.fr/scenari/cas/{SLUG}/session.txt`, indexé ainsi :

```jsonc
{
  "index.html": {
    "intro": { "text": "<article>…</article>", "date": "2025-09-19" }
  },
  "Assemblage_Theorie_des_jeux_V1.html": {
    "phase_1": { "url": "Mini_prosit_Theorie_des_jeux_V1.html", "date": "…" }
  },
  "Mini_prosit_Theorie_des_jeux_V1.html": {
    "obj":   { "text": "…", "date": "…" },
    "topic": { "text": "…", "date": "…" }
  }
}
```

- Chaque page → ses **sections** (clé = classe CSS : `intro`, `obj`, `topic`, `phase_1`…).
- Une section a soit un `text` (fragment HTML), soit une `url` (renvoi vers une
  **page-feuille** qui porte le vrai contenu — cas des pages « Assemblage_* »).
- `date` = date de visibilité (le lecteur masque le contenu futur ; le scraper prend tout).

Côté navigateur, `lib-md/w_fragments/fragments.js` (`displayBlocks`) lit ce JSON et
réinjecte chaque `text` dans le `.part_co` correspondant du squelette. **Le scraper
reproduit exactement cette logique en Python** (`fill()` dans `scrape.py`) — d'où
l'absence de navigateur headless.

## Authentification

Le contenu est derrière **un unique cookie de session `distTk`**, posé par le
lancement LTI (durée de vie : quelques semaines). Sans lui, tout renvoie
`403 scAuthFailed`. Il n'y a pas de redirection CAS sur ces URLs : minter un token
demanderait de rejouer tout le SSO CAS/LTI — trop fragile pour le gain, donc on
copie le token à la main (« Copier comme cURL » → `parse_curl_text()`).

## Pipeline (`scrape.py`)

```
URL d'index
   │  fetch index.html → <title> (titre du bloc) + <nav id=outCat> (menu ordonné)
   │  fetch session.txt → tout le contenu
   ▼
pour chaque page du menu :
   fetch le squelette → #content
   fill(#content, page, session)      # injecte les fragments, résout phase→url
   prune_empty()                      # retire les sections restées vides
   Converter.run(#content) → Markdown
   écrit _src/NN-page.md
   ▼
write_bloc_note()    # {Bloc}.md depuis le template (jamais écrasé)
update_cesi_index()  # ajoute [[wikilink]] en fin de section d'année dans CESI.md
```

### Conversion HTML → Markdown (`Converter`)

`markdownify` gère le gros (paragraphes `.rBk`, listes `.txt_il`, titres, tableaux,
liens). Quelques éléments sont traités à part, via des **placeholders** insérés avant
`markdownify` puis resubstitués après (robuste aux échappements) :

| Élément | Source | Sortie |
| --- | --- | --- |
| Code | `div.code` (CodeMirror, `data-lang`) | bloc clôturé ` ```lang ` (cf. `MIME2LANG`) |
| Maths | `\(…\)` dans `span.txt_mathtex_tl` | `$…$` (et `\[…\]` → `$$…$$`) |
| Figures/images | `<figure>` / `<img src="res/…">` | image téléchargée → `![[fichier]]` |
| Liens relatifs | `href="res/…"`, sous-pages | absolutisés en URL Scenari (sinon notes fantômes Obsidian) |

## Slug → métadonnées

Le SLUG encode les métadonnées, avec des variantes :

```
Etudiant_PGE_A3_FISE_Sciences_fondamentales_de_l_ingenieur_2526
        PGE_A3_FISA_INFO_Developpement_d_applications_distribuees_ETU
```

`parse_slug()` en tire `year` (`a3`), `program` (`pge-a3-fise` / `pge-a3-fisa`) et une
`filiere` optionnelle (`info`). Le **titre** vient du `<title>` de la page, jamais
dé-sluggé (sinon perte des accents/casse).

## Sortie dans le vault

```
CESI/{A3|A4|A5}/{Titre du bloc}/
├── {Titre du bloc}.md      # note de synthèse (type: bloc), frontmatter rempli
├── _src/                   # matière première (masquée du graphe Obsidian)
│   ├── 00-index.md
│   └── NN-page.md
└── attachments/            # images téléchargées
```

## Structure du code

| Fichier | Rôle |
| --- | --- |
| `scrape.py` | toute la logique (auth, crawl, assemblage, conversion, écriture) + CLI |
| `gui.py` | fenêtre Tkinter ; réutilise `scrape.py` (thread + journal en direct) |
| `cesi-scraper.sh` | lanceur de la fenêtre |
| `requirements.txt` | `requests`, `beautifulsoup4`, `markdownify` |

`scrape.py` est conçu pour être réutilisable : `parse_curl_text()`,
`scrape(..., log=callback)` et l'exception `ScrapeError` permettent à `gui.py` (ou
tout autre appelant) de piloter le scrape et de récupérer la progression.
