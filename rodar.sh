#!/usr/bin/env sh
# Alexandria Web - instala o Flask (so na primeira vez) e inicia o servidor
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt --quiet
echo "Abra no navegador: http://127.0.0.1:5000  (Ctrl+C para encerrar)"
python3 app.py
