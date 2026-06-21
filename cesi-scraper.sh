#!/usr/bin/env bash
# Lanceur de l'app CESI-Scraper (fenêtre Tkinter via WSLg).
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python gui.py "$@"
