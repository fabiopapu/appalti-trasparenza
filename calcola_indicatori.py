#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calcola indicatori statistici di trasparenza sugli appalti pubblici
italiani, aggregati per stazione appaltante e per regione. Non esprime
giudizi né accusa persone o aziende: produce solo numeri e percentuali a
partire da dati ufficiali pubblici (ANAC/OCDS, via Open Contracting
Partnership, licenza CC-BY 4.0).

Fonte: https://data.open-contracting.org/en/publication/117
Copre i contratti pubblici sopra 40.000€, aggiornati mensilmente.

Uso: python3 calcola_indicatori.py <anno> indicatori.json
Es.: python3 calcola_indicatori.py 2024 indicatori.json
"""

import csv
import io
import json
import re
import sys
import tarfile
from collections import defaultdict
from datetime import datetime

import requests

HEADERS = {"User-Agent": "TrasparenzaAppalti/1.0 (uso civico, CC-BY 4.0)"}
SOGLIA_VALORE_ALTO = 1_000_000  # oltre questa cifra, un contratto è "di rilievo"


def scarica_ed_estrai(anno):
    url = f"https://data.open-contracting.org/en/publication/117/download?name={anno}.csv.tar.gz"
    print(f"Scarico {url} ...")
    r = requests.get(url, headers=HEADERS, timeout=300, stream=True)
    r.raise_for_status()
    totale_atteso = int(r.headers.get("content-length", 0))
    buf = io.BytesIO()
    scaricati = 0
    for chunk in r.iter_content(chunk_size=1024 * 1024):
        buf.write(chunk)
        scaricati += len(chunk)
        if totale_atteso:
            print(f"\r  {scaricati / 1_000_000:.1f} / {totale_atteso / 1_000_000:.1f} MB...", end="", flush=True)
        else:
            print(f"\r  {scaricati / 1_000_000:.1f} MB scaricati...", end="", flush=True)
    buf.seek(0)
    print(f"\r  Completato: {buf.getbuffer().nbytes / 1_000_000:.1f} MB scaricati" + " " * 20)

    tar = tarfile.open(fileobj=buf, mode="r:gz")
    nomi = tar.getnames()
    candidati = [n for n in nomi if n.endswith("main.csv")]
    if not candidati:
        raise RuntimeError("main.csv non trovato nell'archivio")
    prefisso = candidati[0].rsplit("main.csv", 1)[0]
    return tar, prefisso


def scarica_tabella_comuni_regione():
    """Il dataset ANAC/OCDS non contiene la regione, solo il comune (address
    locality). Deriviamo la regione da un elenco ufficiale ISTAT dei comuni
    italiani (comuni-json, dati ISTAT CC BY 3.0 IT). Ritorna un dizionario
    NOME_COMUNE_MAIUSCOLO -> nome regione."""
    url = "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"
    print(f"\nScarico tabella comuni->regione da {url} ...")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    comuni = r.json()
    tabella = {}
    for c in comuni:
        nome = (c.get("nome") or "").strip().upper()
        regione = (c.get("regione") or {}).get("nome", "").strip()
        if nome and regione:
            tabella[nome] = regione
    print(f"Tabella comuni->regione: {len(tabella)} comuni caricati")
    return tabella


def leggi_csv_da_tar(tar, percorso):
    if percorso not in tar.getnames():
        return None
    f = tar.extractfile(tar.getmember(percorso))
    testo = io.TextIOWrapper(f, encoding="utf-8")
    return list(csv.DictReader(testo))


def parse_data(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").split(".")[0].split("T")[0])
    except ValueError:
        return None


_RE_DATA_RILASCIO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_data_rilascio(s):
    """Il campo 'date' di main.csv è la data reale di pubblicazione/
    registrazione dell'appalto (a differenza di tender_tenderPeriod_start/
    endDate, che nel dataset ANAC sono quasi sempre un placeholder di
    migrazione identico per tutti i record). Il formato è un po' anomalo
    (sembrano due timestamp incollati, es. '2024-10-21 20:13:40.840T12:00:00Z'),
    ma i primi 10 caratteri YYYY-MM-DD sono sempre affidabili."""
    if not s:
        return None
    m = _RE_DATA_RILASCIO.match(s)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def main():
    if len(sys.argv) != 3:
        print("Uso: calcola_indicatori.py <anno oppure anni separati da virgola> indicatori.json", file=sys.stderr)
        print("Es.: calcola_indicatori.py 2024,2025 indicatori.json", file=sys.stderr)
        sys.exit(1)
    anni_arg, percorso_out = sys.argv[1], sys.argv[2]
    anni = [a.strip() for a in anni_arg.split(",") if a.strip()]

    # Scarico ogni anno separatamente e unisco i risultati. Un contratto
    # pluriennale può comparire nel file di più anni (es. una proroga
    # aggiornata nel 2025 di un appalto iniziato nel 2024): deduplico per
    # ocid, tenendo la versione dell'anno più recente, per non contarlo due
    # volte nelle statistiche.
    righe_per_ocid = {}
    righe_parties_totali = []
    for anno in anni:
        print(f"\n=== Anno {anno} ===")
        try:
            tar, prefisso = scarica_ed_estrai(anno)
        except Exception as e:
            print(f"ATTENZIONE: anno {anno} non disponibile o non scaricabile ({e}), lo salto.")
            continue

        righe_main_anno = leggi_csv_da_tar(tar, prefisso + "main.csv")
        if not righe_main_anno:
            print(f"ATTENZIONE: main.csv vuoto per l'anno {anno}, lo salto.")
            continue
        print(f"{len(righe_main_anno)} appalti nel dataset {anno}")

        # [diagnostica] Elenco tutte le colonne di main.csv una sola volta
        # (sono uguali per ogni anno), per capire quale campo data è
        # davvero affidabile: tender_tenderPeriod_startDate si è rivelato
        # spesso un placeholder da migrazione, quindi cerchiamo alternative
        # (date di pubblicazione, di aggiudicazione, ecc.).
        if anno == anni[0]:
            colonne_main = list(righe_main_anno[0].keys())
            colonne_data = [c for c in colonne_main if "date" in c.lower() or "data" in c.lower()]
            print(f"\n[diagnostica] main.csv: {len(colonne_main)} colonne totali, quelle con 'date'/'data' nel nome:")
            for c in colonne_data:
                esempio = righe_main_anno[0].get(c, "")
                print(f"    - {c!r}  (esempio: {esempio[:50]!r})")
            print(f"[diagnostica] elenco completo colonne main.csv: {colonne_main}")

        for r in righe_main_anno:
            ocid = r.get("ocid") or r.get("id")
            if not ocid:
                continue
            r["_anno_origine"] = anno
            # Se già visto in un anno precedente, tengo la versione più
            # recente (probabilmente più aggiornata, es. dopo una proroga).
            esistente = righe_per_ocid.get(ocid)
            if esistente is None or anno >= esistente["_anno_origine"]:
                righe_per_ocid[ocid] = r

        righe_parties_anno = leggi_csv_da_tar(tar, prefisso + "parties.csv")
        if righe_parties_anno:
            righe_parties_totali.extend(righe_parties_anno)

    righe_main = list(righe_per_ocid.values())
    if not righe_main:
        raise RuntimeError("nessun appalto trovato per nessuno degli anni richiesti")
    print(f"\nTotale dopo deduplicazione su {len(anni)} anni: {len(righe_main)} appalti")

    # Mappa buyer_id -> comune, da parties.csv (funziona: quel campo esiste
    # davvero nel dataset). La regione NON è presente in parties.csv (il
    # dataset ANAC/OCDS non la include) — la deriviamo dal nome del comune
    # usando una tabella ufficiale ISTAT comune->regione.
    comune_di = {}
    if righe_parties_totali:
        colonne = list(righe_parties_totali[0].keys())
        print(f"\n[diagnostica] parties.csv (tutti gli anni): {len(righe_parties_totali)} righe, colonne trovate:")
        for c in colonne:
            esempio = righe_parties_totali[0].get(c, "")
            print(f"    - {c!r}  (esempio: {esempio[:50]!r})")

        pattern_comune = ["locality", "comune", "city", "town", "municipality"]
        col_comune = next((c for c in colonne if any(p in c.lower() for p in pattern_comune)), None)
        col_id = next((c for c in colonne if c.lower() == "id"), None)

        if col_id and col_comune:
            for r in righe_parties_totali:
                idr = r.get(col_id)
                if idr and r.get(col_comune):
                    comune_di[idr] = r[col_comune]
            print(f"[diagnostica] colonna comune: {col_comune!r} -> {len(comune_di)} enti")
        else:
            print(f"[diagnostica] NESSUNA colonna comune riconosciuta tra: {colonne}")
    else:
        print("\n[diagnostica] parties.csv NON TROVATO in nessun anno.")

    # Ora derivo la regione dal comune, usando la tabella ISTAT
    tabella_comuni = scarica_tabella_comuni_regione()
    regione_di = {}
    for idr, nome_comune in comune_di.items():
        regione = tabella_comuni.get(nome_comune.strip().upper())
        if regione:
            regione_di[idr] = regione

    buyer_ids_main = {r.get("buyer_id") for r in righe_main if r.get("buyer_id")}
    trovati_com = sum(1 for bid in buyer_ids_main if bid in comune_di)
    trovati_reg = sum(1 for bid in buyer_ids_main if bid in regione_di)
    print(f"\n[diagnostica] su {len(buyer_ids_main)} buyer_id unici in main.csv:")
    print(f"[diagnostica]   {trovati_com} hanno un comune noto ({100*trovati_com/max(1,len(buyer_ids_main)):.1f}%)")
    print(f"[diagnostica]   {trovati_reg} hanno una regione derivata dal comune ({100*trovati_reg/max(1,len(buyer_ids_main)):.1f}%)")
    if trovati_com > trovati_reg:
        comuni_non_matchati = {comune_di[bid] for bid in buyer_ids_main if bid in comune_di and bid not in regione_di}
        esempio_mancanti = list(comuni_non_matchati)[:10]
        print(f"[diagnostica]   esempi di comuni non trovati nella tabella ISTAT: {esempio_mancanti}")

    # Aggregazione per stazione appaltante (buyer_name). "per_anno" tiene le
    # stesse metriche ma spezzate per anno di origine (r["_anno_origine"],
    # l'anno del dataset scaricato a cui la riga deduplicata appartiene), così
    # il frontend può filtrare la tabella per anno invece di vedere solo il
    # totale aggregato su tutti gli anni richiesti.
    per_ente = defaultdict(lambda: {
        "regione": None, "comune": None, "n_gare": 0, "n_affidamenti_diretti": 0,
        "valore_totale": 0.0, "n_valore_alto": 0, "durate_gg": [], "gare_esempio": [],
        "per_anno": defaultdict(lambda: {
            "n_gare": 0, "n_affidamenti_diretti": 0, "valore_totale": 0.0, "durate_gg": [],
        }),
    })

    CATEGORIA_IT = {"works": "Lavori", "services": "Servizi", "goods": "Forniture"}
    MAX_ESEMPI_PER_ENTE = 30
    anni_disponibili = set()

    for r in righe_main:
        nome_ente = (r.get("buyer_name") or "").strip()
        if not nome_ente:
            continue
        e = per_ente[nome_ente]
        # Non mi fermo al primo tentativo: grandi enti (RFI, ANAS, ASL...)
        # hanno decine o centinaia di buyer_id diversi (uffici territoriali),
        # e se il primo incontrato non ha un comune riconosciuto non voglio
        # bloccare l'intero ente su "Non disponibile" ignorando gli altri.
        if e["regione"] is None:
            regione_trovata = regione_di.get(r.get("buyer_id"))
            if regione_trovata:
                e["regione"] = regione_trovata
        if e["comune"] is None:
            comune_trovato = comune_di.get(r.get("buyer_id"))
            if comune_trovato:
                e["comune"] = comune_trovato
        e["n_gare"] += 1

        inizio = parse_data(r.get("tender_tenderPeriod_startDate"))
        fine = parse_data(r.get("tender_tenderPeriod_endDate"))
        durata = (fine - inizio).days if (inizio and fine and fine > inizio) else None

        # Il filtro per anno: preferisco tender_tenderPeriod_startDate quando
        # sembra genuino (cioè diverso da endDate — il placeholder di
        # migrazione ANAC ha sempre start=end identici, senza vera durata).
        # Se sembra un placeholder, o manca del tutto, ripiego sulla data di
        # rilascio/registrazione (campo "date"). Le righe senza nessuna delle
        # due non entrano in nessun bucket per anno (ma contano comunque nel
        # totale complessivo dell'ente).
        inizio_genuino = inizio if (inizio and inizio != fine) else None
        rilascio = parse_data_rilascio(r.get("date"))
        anno_di_riferimento = inizio_genuino or rilascio
        anno_riga = str(anno_di_riferimento.year) if anno_di_riferimento else None
        if anno_riga is not None:
            anni_disponibili.add(anno_riga)
            pa = e["per_anno"][anno_riga]
            pa["n_gare"] += 1
        else:
            pa = None

        dettaglio = (r.get("tender_procurementMethodDetails") or "").upper()
        e_diretto = "AFFIDAMENTO DIRETTO" in dettaglio
        if e_diretto:
            e["n_affidamenti_diretti"] += 1
            if pa is not None:
                pa["n_affidamenti_diretti"] += 1

        try:
            valore = float(r.get("tender_value_amount") or 0)
        except ValueError:
            valore = 0.0
        e["valore_totale"] += valore
        if pa is not None:
            pa["valore_totale"] += valore
        if valore >= SOGLIA_VALORE_ALTO:
            e["n_valore_alto"] += 1

        if durata is not None:
            e["durate_gg"].append(durata)
            if pa is not None:
                pa["durate_gg"].append(durata)

        # Raccolgo un esempio dell'appalto vero (oggetto, categoria, valore),
        # utile per capire concretamente cosa compra questo ente. Tengo solo
        # i più significativi per non far esplodere la dimensione del file.
        descrizione = (r.get("tender_description") or "").strip()
        if descrizione and valore > 0:
            categoria_raw = (r.get("tender_mainProcurementCategory") or "").strip().lower()
            e["gare_esempio"].append({
                "oggetto": descrizione[:200],  # taglio descrizioni lunghissime
                "categoria": CATEGORIA_IT.get(categoria_raw, categoria_raw.capitalize() or "Non specificata"),
                "valore": round(valore, 2),
                "data": anno_di_riferimento.strftime("%Y-%m-%d") if anno_di_riferimento else None,
                "diretto": e_diretto,
                "durata_gg": durata,
            })

    # [diagnostica] Distribuzione per anno del file scaricato vs anno di
    # riferimento combinato (tenderPeriod genuino, altrimenti rilascio),
    # più un conteggio di quante righe usano l'uno o l'altro.
    conteggio_per_anno_rif = defaultdict(int)
    conteggio_per_file_origine = defaultdict(int)
    n_da_tenderperiod, n_da_rilascio, n_mancanti = 0, 0, 0
    for r in righe_main:
        conteggio_per_file_origine[r.get("_anno_origine")] += 1
        inizio_diag = parse_data(r.get("tender_tenderPeriod_startDate"))
        fine_diag = parse_data(r.get("tender_tenderPeriod_endDate"))
        inizio_genuino_diag = inizio_diag if (inizio_diag and inizio_diag != fine_diag) else None
        rilascio_diag = parse_data_rilascio(r.get("date"))
        rif_diag = inizio_genuino_diag or rilascio_diag
        if inizio_genuino_diag:
            n_da_tenderperiod += 1
        elif rilascio_diag:
            n_da_rilascio += 1
        else:
            n_mancanti += 1
        conteggio_per_anno_rif[str(rif_diag.year) if rif_diag else "(data mancante)"] += 1
    print("\n[diagnostica] righe per anno del FILE scaricato:")
    for k, v in sorted(conteggio_per_file_origine.items()):
        print(f"    {k}: {v} righe")
    print(f"[diagnostica] fonte della data usata per il filtro: {n_da_tenderperiod} da tenderPeriod genuino, "
          f"{n_da_rilascio} da rilascio (fallback), {n_mancanti} nessuna data disponibile")
    print("[diagnostica] righe per anno di RIFERIMENTO (quello usato dal filtro):")
    for k, v in sorted(conteggio_per_anno_rif.items()):
        print(f"    {k}: {v} righe")

    def calcola_metriche(n_gare, n_diretti, valore_totale, durate_gg):
        pct = round(100 * n_diretti / n_gare, 1) if n_gare else 0
        durata_media = round(sum(durate_gg) / len(durate_gg), 1) if durate_gg else None
        return pct, durata_media

    # Trasformo in output finale, con percentuali già calcolate
    enti_output = []
    per_regione = defaultdict(lambda: {
        "n_gare": 0, "n_affidamenti_diretti": 0, "valore_totale": 0.0,
        "per_anno": defaultdict(lambda: {"n_gare": 0, "n_affidamenti_diretti": 0, "valore_totale": 0.0}),
    })

    for nome_ente, e in per_ente.items():
        pct_diretti, durata_media = calcola_metriche(
            e["n_gare"], e["n_affidamenti_diretti"], e["valore_totale"], e["durate_gg"])

        per_anno_output = {}
        for anno_riga, pa in e["per_anno"].items():
            pct_pa, durata_pa = calcola_metriche(
                pa["n_gare"], pa["n_affidamenti_diretti"], pa["valore_totale"], pa["durate_gg"])
            per_anno_output[anno_riga] = {
                "n_gare": pa["n_gare"],
                "pct_affidamenti_diretti": pct_pa,
                "valore_totale": round(pa["valore_totale"], 2),
                "durata_media_gara_giorni": durata_pa,
            }

        # Tengo solo i N esempi di valore più alto: sono i più rilevanti da
        # mostrare e limitano la dimensione del file per enti molto attivi.
        esempi = sorted(e["gare_esempio"], key=lambda g: -g["valore"])[:MAX_ESEMPI_PER_ENTE]
        enti_output.append({
            "ente": nome_ente,
            "regione": e["regione"] or "Non disponibile",
            "comune": e["comune"],
            "n_gare": e["n_gare"],
            "pct_affidamenti_diretti": pct_diretti,
            "valore_totale": round(e["valore_totale"], 2),
            "n_contratti_di_rilievo": e["n_valore_alto"],
            "durata_media_gara_giorni": durata_media,
            "gare_esempio": esempi,
            "per_anno": per_anno_output,
        })
        if e["regione"]:
            pr = per_regione[e["regione"]]
            pr["n_gare"] += e["n_gare"]
            pr["n_affidamenti_diretti"] += e["n_affidamenti_diretti"]
            pr["valore_totale"] += e["valore_totale"]
            for anno_riga, pa in e["per_anno"].items():
                pr_pa = pr["per_anno"][anno_riga]
                pr_pa["n_gare"] += pa["n_gare"]
                pr_pa["n_affidamenti_diretti"] += pa["n_affidamenti_diretti"]
                pr_pa["valore_totale"] += pa["valore_totale"]

    regioni_output = []
    for regione, r in per_regione.items():
        pct = round(100 * r["n_affidamenti_diretti"] / r["n_gare"], 1) if r["n_gare"] else 0
        per_anno_regione = {}
        for anno_riga, pr_pa in r["per_anno"].items():
            pct_pa = round(100 * pr_pa["n_affidamenti_diretti"] / pr_pa["n_gare"], 1) if pr_pa["n_gare"] else 0
            per_anno_regione[anno_riga] = {
                "n_gare": pr_pa["n_gare"],
                "pct_affidamenti_diretti": pct_pa,
                "valore_totale": round(pr_pa["valore_totale"], 2),
            }
        regioni_output.append({
            "regione": regione,
            "n_gare": r["n_gare"],
            "pct_affidamenti_diretti": pct,
            "valore_totale": round(r["valore_totale"], 2),
            "per_anno": per_anno_regione,
        })

    risultato = {
        "anno": int(anno),
        "anni_disponibili": sorted(a for a in anni_disponibili if a),
        "generato_il": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "n_enti": len(enti_output),
        "regioni": sorted(regioni_output, key=lambda x: -x["n_gare"]),
        "enti": sorted(enti_output, key=lambda x: -x["n_gare"]),
    }

    with open(percorso_out, "w", encoding="utf-8") as f:
        json.dump(risultato, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nScritti indicatori per {len(enti_output)} enti in {percorso_out}")


if __name__ == "__main__":
    main()
