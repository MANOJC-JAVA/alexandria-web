@echo off
REM Alexandria Web - instala o Flask (so na primeira vez) e inicia o servidor
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
echo.
echo Abra no navegador: http://127.0.0.1:5000
echo Para encerrar, pressione Ctrl+C
python app.py
pause
