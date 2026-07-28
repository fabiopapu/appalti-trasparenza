@echo off
chcp 65001 >nul
title Trasparenza Appalti - server locale

if not exist dati mkdir dati

if not exist dati\indicatori.json (
    echo.
    echo Non ho ancora i dati: li scarico e li elaboro adesso.
    echo Scarico gli anni 2024 e 2025, circa 85 MB totali, un paio di minuti...
    echo.
    python calcola_indicatori.py 2024,2025 dati\indicatori.json
    if errorlevel 1 (
        echo.
        echo Qualcosa e' andato storto durante il calcolo. Guarda il messaggio sopra.
        pause
        exit /b 1
    )
)

echo.
echo Dati pronti. Avvio il server locale e apro il browser...
echo Per chiudere tutto, torna su questa finestra e premi CTRL+C.
echo.

timeout /t 2 >nul
start http://localhost:8000/index.html
python -m http.server 8000
