"""
Pressearchiv — Known Source Catalogue.

Usage:
    from scripts.sources import SOURCES, get_source, CAT_TOP, CAT_FACHPRESSE

    # Look up by DB code
    src = SOURCES["HB"]
    print(src["name"])         # "Handelsblatt"
    print(src["browse_name"])  # "Handelsblatt"  (for get_issue_list / get_table_of_contents)
    print(src["categories"])   # ["top_quellen"]

    # Filter by category
    top = [code for code, s in SOURCES.items() if CAT_TOP in s["categories"]]

Schema per entry:
    name         Human-readable display name (cleaned slug)
    browse_name  Exact name used in /browse/…/{browse_name} URLs and get_issue_list().
                 None if not individually browsable (e.g. many regional newspapers).
    categories   List of category constants (see CAT_* below)

Notes:
- browse_name is required for get_issue_list() / get_current_issue_id() /
  get_table_of_contents(). If None, TOC access is not available directly.
- "presse_de" only lists the first 25 of 500+ German regional newspapers
  available in the archive. Use the browse page at
  /browse/Alle%20Quellen/Presse/Presse%20Deutschland to discover more.
- Last updated: 2026-03-13 (auto-discovered via browse API + manual mapping)
"""

# ─── Category constants ──────────────────────────────────────────────────────
CAT_TOP       = "top_quellen"    # Top-Quellen (major national press)
CAT_FACHPRESS = "fachpresse"     # Fachpresse (trade/specialised press)
CAT_PRESSE_DE = "presse_de"      # Presse Deutschland (regional newspapers)
CAT_PRESSE_ATCH = "presse_at_ch" # Presse Österreich & Schweiz
CAT_AGENTUREN = "agenturen"      # Nachrichtenagenturen


# ─── Source catalogue ────────────────────────────────────────────────────────
# Key = DB code (used in SearchResult.database, in field queries like FIRMA-AKTUELL,
#       and as prefix in issue IDs like "HB__:2026:51")
SOURCES: dict[str, dict] = {

    # ── Top-Quellen ──────────────────────────────────────────────────────────
    "HB": {
        "name": "Handelsblatt",
        "browse_name": "Handelsblatt",
        "categories": [CAT_TOP],
    },
    "HBON": {
        "name": "Handelsblatt online",
        "browse_name": "Handelsblatt online",
        "categories": [CAT_TOP],
    },
    "HBTO": {
        "name": "Handelsblatt Today",
        "browse_name": "Handelsblatt Today",
        "categories": [CAT_TOP],
    },
    "FAZ": {
        "name": "F.A.Z. Frankfurter Allgemeine Zeitung",
        "browse_name": "F.A.Z. Frankfurter Allgemeine Zeitung (FAZ)",
        "categories": [CAT_TOP],
    },
    "FAZN": {
        "name": "FAZ.NET",
        "browse_name": "FAZ.NET",
        "categories": [CAT_TOP],
    },
    "FAS": {
        "name": "Frankfurter Allgemeine Sonntagszeitung",
        "browse_name": "Frankfurter Allgemeine Sonntagszeitung (FAS)",
        "categories": [CAT_TOP],
    },
    "SZ": {
        "name": "Süddeutsche Zeitung",
        "browse_name": "Süddeutsche Zeitung (SZ)",
        "categories": [CAT_TOP],
    },
    "SZDE": {
        "name": "sueddeutsche.de",
        "browse_name": "sueddeutsche.de",
        "categories": [CAT_TOP],
    },
    "WELT": {
        "name": "DIE WELT",
        "browse_name": "DIE WELT",
        "categories": [CAT_TOP],
    },
    "SPIE": {
        "name": "DER SPIEGEL",
        "browse_name": "DER SPIEGEL",
        "categories": [CAT_TOP],
    },
    "SPON": {
        "name": "DER SPIEGEL online",
        "browse_name": "DER SPIEGEL online",
        "categories": [CAT_TOP],
    },
    "NZZ": {
        "name": "Neue Zürcher Zeitung",
        "browse_name": "Neue Zürcher Zeitung (NZZ)",
        "categories": [CAT_TOP],
    },
    "NZZS": {
        "name": "NZZ am Sonntag",
        "browse_name": "NZZ am Sonntag",
        "categories": [CAT_TOP],
    },
    "FR": {
        "name": "Frankfurter Rundschau",
        "browse_name": "Frankfurter Rundschau",
        "categories": [CAT_TOP],
    },
    "TSP": {
        "name": "Der Tagesspiegel",
        "browse_name": "Der Tagesspiegel",
        "categories": [CAT_TOP],
    },
    "TSPO": {
        "name": "tagesspiegel.de",
        "browse_name": "tagesspiegel.de",
        "categories": [CAT_TOP],
    },
    "TAZ": {
        "name": "taz. die tageszeitung",
        "browse_name": "taz. die tageszeitung",
        "categories": [CAT_TOP],
    },
    "MM": {
        "name": "manager magazin",
        "browse_name": "manager magazin",
        "categories": [CAT_TOP],
    },
    "MCBO": {
        "name": "Börsen-Zeitung",
        "browse_name": "Börsen-Zeitung (aktuell)",
        "categories": [CAT_TOP],
    },
    "CAPI": {
        "name": "Capital",
        "browse_name": "Capital",
        "categories": [CAT_TOP],
    },
    "FOCU": {
        "name": "FOCUS",
        "browse_name": "FOCUS",
        "categories": [CAT_TOP],
    },
    "FOCM": {
        "name": "FOCUS-MONEY",
        "browse_name": "FOCUS-MONEY",
        "categories": [CAT_TOP],
    },
    "EUFI": {
        "name": "Euro",
        "browse_name": "Euro",
        "categories": [CAT_TOP],
    },
    "STER": {
        "name": "Stern",
        "browse_name": "Stern",
        "categories": [CAT_TOP],
    },
    "IMP": {
        "name": "Impulse – Das Unternehmer-Magazin",
        "browse_name": "Impulse - Das Unternehmer-Magazin",
        "categories": [CAT_TOP],
    },
    # WirtschaftsWoche — TOC confirmed working (49 articles, 2026-03-13)
    "WW": {
        "name": "WirtschaftsWoche",
        "browse_name": "WirtschaftsWoche",
        "categories": [CAT_TOP],
    },

    # ── Fachpresse ───────────────────────────────────────────────────────────
    "HBIG": {
        "name": "Handelsblatt Geldanlage",
        "browse_name": "Handelsblatt Geldanlage",
        "categories": [CAT_FACHPRESS],
    },
    "DIGH": {
        "name": "Handelsblatt Inside Digital Health",
        "browse_name": "Handelsblatt Inside Digital Health",
        "categories": [CAT_FACHPRESS],
    },
    "HBRE": {
        "name": "Handelsblatt Inside Energie und Immobilien",
        "browse_name": "Handelsblatt Inside Energie und Immobilien",
        "categories": [CAT_FACHPRESS],
    },
    "HZ": {
        "name": "Handelszeitung",
        "browse_name": None,
        "categories": [CAT_FACHPRESS, CAT_PRESSE_ATCH],
    },
    "FUW": {
        "name": "Finanz und Wirtschaft",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "LMZ": {
        "name": "Lebensmittel Zeitung",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "LMZN": {
        "name": "lebensmittelzeitung.net",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "LMZS": {
        "name": "Lebensmittel Zeitung Spezial",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "CW": {
        "name": "COMPUTERWOCHE",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "HOR": {
        "name": "HORIZONT",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "HORN": {
        "name": "HORIZONT Online",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "ASW": {
        "name": "absatzwirtschaft",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "DBDB": {
        "name": "DER BETRIEB",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "DAR": {
        "name": "Der Aufsichtsrat",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "KONZ": {
        "name": "DER KONZERN",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "CF": {
        "name": "Corporate Finance",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "FB": {
        "name": "CORPORATE FINANCE biz",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "VCNE": {
        "name": "Creditreform – Das Unternehmermagazin",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "KURS": {
        "name": "KURS – Monatszeitschrift für Finanzdienstleister",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "LP": {
        "name": "Lebensmittel Praxis",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "KONT": {
        "name": "Der Kontakter",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "KONO": {
        "name": "Kontakter online",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "CS": {
        "name": "Convenience Shop",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "CHGM": {
        "name": "changement!",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },
    "ADA": {
        "name": "ada",
        "browse_name": None,
        "categories": [CAT_FACHPRESS],
    },

    # ── Presse Österreich & Schweiz (Auswahl) ────────────────────────────────
    "AGZ": {
        "name": "Aargauer Zeitung",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "BAZ": {
        "name": "Basler Zeitung",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "BERN": {
        "name": "Berner Zeitung",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "BLI": {
        "name": "Blick",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "BLIO": {
        "name": "Blick online",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "BUND": {
        "name": "Der Bund",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "DOL": {
        "name": "Dolomiten",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "FALT": {
        "name": "Falter",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "FORM": {
        "name": "FORMAT",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "FURC": {
        "name": "Die Furche",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "HZO": {
        "name": "Handelszeitung Online",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "KLEI": {
        "name": "Kleine Zeitung",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "KRON": {
        "name": "Kronen Zeitung",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "KUR": {
        "name": "Kurier",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "DIS": {
        "name": "APA Diplomatic Bulletin Austria",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "AJOU": {
        "name": "APA Journal",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },
    "AGEF": {
        "name": "L'Agefi",
        "browse_name": None,
        "categories": [CAT_PRESSE_ATCH],
    },

    # ── Presse Deutschland (erste 25 von 500+) ───────────────────────────────
    # Weitere unter: /browse/Alle%20Quellen/Presse/Presse%20Deutschland
    "AAN": {"name": "Aachener Nachrichten",               "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "AAZ": {"name": "Aachener Zeitung",                   "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "MUAZ": {"name": "Abendzeitung München (AZ)",         "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "AAUG": {"name": "Augsburger Allgemeine",              "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BZ": {"name": "B.Z. Berlin",                         "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BNNA": {"name": "Badische Neueste Nachrichten",       "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BADZ": {"name": "Badische Zeitung",                   "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BR": {"name": "Bayerische Rundschau",                 "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BSTZ": {"name": "Bayerische Staatszeitung",           "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "MAZ": {"name": "Allgemeine Zeitung Mainz/Rheinhessen","browse_name": None, "categories": [CAT_PRESSE_DE]},
    "ALMA": {"name": "Altmark-Zeitung",                    "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "ABB": {"name": "Acher- und Bühler Bote",              "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "BAYG": {"name": "Bayerische GemeindeZeitung",         "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "ALLZ": {"name": "Aller-Zeitung",                      "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "AGLZ": {"name": "Allgemeine Laber-Zeitung",           "browse_name": None, "categories": [CAT_PRESSE_DE]},
    "ALZE": {"name": "Allgemeine Zeitung Lüneburger Heide","browse_name": None, "categories": [CAT_PRESSE_DE]},

    # ── Nachrichtenagenturen ─────────────────────────────────────────────────
    "AWP": {
        "name": "AWP Finanznachrichten",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "AWPO": {
        "name": "AWP Originaltext-Service",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "DTS": {
        "name": "dts Deutsche Textservice Nachrichtenagentur",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "DAPD": {
        "name": "dapd nachrichtenagentur",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "NEWA": {
        "name": "news aktuell (Originaltextservice)",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "NECH": {
        "name": "news aktuell schweiz",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "HUGI": {
        "name": "GlobeNewswire",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "BUIN": {
        "name": "Business Insider Deutschland",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "BUIP": {
        "name": "Business Insider",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "DW": {
        "name": "Deutsche Welle (dw.com)",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "OTS": {
        "name": "APA Original Textservice",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
    "AENS": {
        "name": "APA EconomicNewsService",
        "browse_name": None,
        "categories": [CAT_AGENTUREN],
    },
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_source(db_code: str) -> dict | None:
    """Return source metadata dict for a given DB code, or None if unknown."""
    return SOURCES.get(db_code.upper())


def sources_by_category(category: str) -> dict[str, dict]:
    """Return all sources belonging to a given category constant."""
    return {
        code: src for code, src in SOURCES.items()
        if category in src.get("categories", [])
    }


def browsable_sources() -> dict[str, dict]:
    """Return only sources with a known browse_name (usable with TOC API)."""
    return {
        code: src for code, src in SOURCES.items()
        if src.get("browse_name") is not None
    }
