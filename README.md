# Trasparenza Appalti

## Uso in locale (per vedere subito il sito, senza GitHub)

1. Scompatta questa cartella dove vuoi (es. Desktop)
2. Apri la cartella, fai **doppio click su `avvia_locale.bat`**
3. Si apre una finestra nera (il terminale): la prima volta scarica e
   calcola i dati (76 MB, un paio di minuti), le volte successive è
   istantaneo perché i dati restano salvati
4. Il browser si apre da solo su `http://localhost:8000/index.html`
   con il sito già popolato
5. Per chiudere: torna sulla finestra nera e premi **CTRL+C**, poi chiudi

Se vuoi ricalcolare i dati da capo (es. per un anno diverso), cancella il
file `dati\indicatori.json` e rilancia `avvia_locale.bat`.

## Quando sei pronto per pubblicarlo online (GitHub Pages)

Quando vuoi che il sito sia visibile a chiunque con un link, invece che
solo sul tuo PC, carica questa stessa cartella su GitHub (stessa
procedura già fatta per il sito carburanti) e attiva GitHub Pages nelle
impostazioni della repo. Il workflow dentro `.github/workflows/` fa sì
che i dati si aggiornino da soli ogni mese, senza bisogno del tuo PC acceso.

## File in questa cartella

- `index.html` — il sito vero e proprio
- `calcola_indicatori.py` — scarica i dati ANAC e calcola gli indicatori
- `dati/indicatori.json` — i dati calcolati (creato al primo avvio)
- `avvia_locale.bat` — avvia tutto in automatico su Windows
- `.github/workflows/aggiorna-appalti.yml` — per l'aggiornamento automatico mensile una volta online

## Fonte dei dati

ANAC (Autorità Nazionale Anticorruzione), contratti pubblici sopra
40.000€, formato OCDS via Open Contracting Partnership, licenza CC-BY 4.0:
https://data.open-contracting.org/en/publication/117
