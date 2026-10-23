#!/usr/bin/env python3
"""CESI-Scraper — fenêtre desktop (Tkinter).

Colle un « Copier comme cURL », confirme le vault, clique Scraper. Le reste est
géré par scrape.py. Le cURL est persisté dans auth.curl (gitignoré), le chemin du
vault et le dossier documents de chaque bloc dans gui_config.json.

Lancement : .venv/bin/python gui.py     (nécessite python3-tk : sudo apt install python3-tk)
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import scrape

HERE = Path(__file__).resolve().parent
AUTH_FILE = HERE / "auth.curl"
CONFIG_FILE = HERE / "gui_config.json"
MONO = "TkFixedFont"  # police à chasse fixe intégrée à Tk (présente partout)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.running = False
        root.title("CESI-Scraper")
        root.geometry("760x620")
        root.minsize(620, 520)

        cfg = self._load_config()
        pad = dict(padx=12, pady=(0, 8))

        # — Cookie / cURL —
        ttk.Label(root, text="Cookie — colle ton « Copier comme cURL » :").pack(
            anchor="w", padx=12, pady=(12, 2))
        self.curl = ScrolledText(root, height=6, wrap="word", font=MONO, undo=True)
        self.curl.pack(fill="x", **pad)
        self.curl.bind("<KeyRelease>", lambda _e: self._refresh_detected())
        if AUTH_FILE.exists():
            self.curl.insert("1.0", AUTH_FILE.read_text(encoding="utf-8", errors="replace"))

        # — Vault —
        row = ttk.Frame(root); row.pack(fill="x", **pad)
        ttk.Label(row, text="Vault :").pack(side="left")
        self.vault = tk.StringVar(value=cfg.get("vault", scrape.DEFAULT_VAULT))
        ttk.Entry(row, textvariable=self.vault).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="📁 Parcourir", command=self._browse).pack(side="left")

        # — Dossier documents (mémorisé par bloc ; vide = liens Scenari) —
        self.docs_dirs: dict = cfg.get("docs_dirs", {})
        self.slug = ""
        rowd = ttk.Frame(root); rowd.pack(fill="x", **pad)
        ttk.Label(rowd, text="Documents :").pack(side="left")
        self.docs = tk.StringVar()
        ttk.Entry(rowd, textvariable=self.docs).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(rowd, text="📁 Parcourir", command=self._browse_docs).pack(side="left")

        # — Bloc détecté + options —
        row2 = ttk.Frame(root); row2.pack(fill="x", **pad)
        self.detected = tk.StringVar(value="Bloc : —")
        ttk.Label(row2, textvariable=self.detected, foreground="#555").pack(side="left")
        self.dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Aperçu (n'écrit rien)", variable=self.dry).pack(side="right")

        # — Bouton —
        self.btn = ttk.Button(root, text="▶  Scraper", command=self._start)
        self.btn.pack(fill="x", padx=12, pady=(0, 8))

        # — Journal —
        ttk.Label(root, text="Journal :").pack(anchor="w", padx=12)
        self.log = ScrolledText(root, height=14, wrap="word", font=MONO, state="disabled",
                                background="#1e1e1e", foreground="#d4d4d4")
        self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        self._refresh_detected()
        self.root.after(100, self._pump)

    # ----- helpers -----
    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_config(self):
        if self.slug:
            docs = self.docs.get().strip()
            if docs:
                self.docs_dirs[self.slug] = docs
            else:
                self.docs_dirs.pop(self.slug, None)
        CONFIG_FILE.write_text(json.dumps({"vault": self.vault.get(), "docs_dirs": self.docs_dirs},
                                          indent=2, ensure_ascii=False), encoding="utf-8")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.vault.get() or "/mnt", title="Choisir le vault Obsidian")
        if d:
            self.vault.set(d)

    def _browse_docs(self):
        d = filedialog.askdirectory(initialdir=self.docs.get() or "/mnt/x",
                                    title="Dossier des documents de ce bloc")
        if d:
            self.docs.set(d)

    def _refresh_detected(self):
        disttk, _ua, url = scrape.parse_curl_text(self.curl.get("1.0", "end"))
        if url:
            m = scrape.parse_slug(url)
            if m["slug"] != self.slug:  # nouveau bloc → son dossier documents mémorisé
                self.slug = m["slug"]
                self.docs.set(self.docs_dirs.get(self.slug, ""))
            tok = "🔑" if disttk else "⚠ pas de token"
            self.detected.set(f"Bloc : {m['slug']}  ·  {m['year']} / {m['program']}  ·  {tok}")
        else:
            self.detected.set("Bloc : —  (colle un cURL d'une page de cours)")

    def _append(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_running(self, on: bool):
        self.running = on
        self.btn.configure(state="disabled" if on else "normal",
                           text="⏳  Scraping…" if on else "▶  Scraper")

    # ----- run -----
    def _start(self):
        if self.running:
            return
        curl_text = self.curl.get("1.0", "end").strip()
        disttk, ua, url = scrape.parse_curl_text(curl_text)
        if not disttk:
            messagebox.showerror("Cookie manquant", "Aucun token `distTk` dans le cURL collé.")
            return
        if not url:
            messagebox.showerror("URL manquante", "Aucune URL de bloc trouvée dans le cURL collé.")
            return
        vault = self.vault.get().strip()
        if not Path(vault).is_dir():
            messagebox.showerror("Vault introuvable", f"Le dossier n'existe pas :\n{vault}")
            return
        docs = self.docs.get().strip()
        if docs and not Path(docs).is_dir():
            messagebox.showerror("Dossier documents introuvable", f"Le dossier n'existe pas :\n{docs}")
            return
        AUTH_FILE.write_text(curl_text + "\n", encoding="utf-8")  # persiste le token (gitignoré)
        self._save_config()

        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        self._set_running(True)
        args = (url, Path(vault), disttk, ua, self.dry.get(), Path(docs) if docs else None)
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _worker(self, url, vault, disttk, ua, dry, docs_dir):
        try:
            scrape.scrape(url, vault, disttk, ua, dry, log=lambda m: self.q.put(("log", m)),
                          docs_dir=docs_dir)
            self.q.put(("done", ""))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def _pump(self):
        try:
            while True:
                kind, msg = self.q.get_nowait()
                if kind == "log":
                    self._append(msg)
                elif kind == "done":
                    self._set_running(False)
                elif kind == "error":
                    self._append(f"✗ {msg}")
                    self._set_running(False)
                    messagebox.showerror("Erreur", msg)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)


def main():
    root = tk.Tk()
    try:  # thème un peu plus propre si dispo
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
