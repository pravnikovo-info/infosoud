# InfoSoud

Neoficiální klient pro [InfoSoud](https://infosoud.gov.cz) — vyhledávání v soudních řízeních České republiky.

Umožňuje vyhledat průběh soudního řízení, nařízená jednání a události podle spisové značky. Data pocházejí z veřejného API Ministerstva spravedlnosti ČR.

**[infosoud.pravnikovo.info](https://infosoud.pravnikovo.info)** — webové rozhraní

## Instalace

```bash
pip install git+https://github.com/pravnikovo-info/infosoud.git
```

Až bude balíček na PyPI:
```bash
pip install infosoud
```

## Použití

### Příkazový řádek

```bash
# Vyhledat řízení
infosoud "1 T 64/2024" OSSCEDC
infosoud "1T64_2024 OSSCEDC"          # kompaktní formát
infosoud "4 T 21/2025 melnik"         # název soudu místo kódu

# Zobrazit jednání
infosoud --hearings "1 T 64/2024" OSSCEDC

# JSON výstup
infosoud --json "1 T 64/2024" OSSCEDC

# CSV výstup (události)
infosoud --csv "1 T 64/2024" OSSCEDC

# Vypsat soudy
infosoud --courts
infosoud --courts --csv
```

### Python

```python
from infosoud import InfoSoudClient, parse_spis_zn

client = InfoSoudClient()

# Vyhledat řízení
case = client.search_case("1 T 64/2024", "OSSCEDC")
print(case["stav"])          # "nevyřízená věc"
print(case["organizace"])    # "Okresní soud Děčín"

for event in case["udalosti"]:
    print(f"{event['datum']}  {event['udalost']}")

# Vyhledat jednání
hearings = client.search_hearings("1 T 64/2024", "OSSCEDC")
for h in hearings["udalosti"]:
    print(f"{h['datum']} {h['cas']}  {h['druhJednani']}  {h['resitel']}")

# Detail události (čas, jednací síň)
detail = client.get_event_detail("1 T 64/2024", "OSSCEDC", "NAR_JED", 48)
for attr in detail["atributy"]:
    print(f"{attr['typ']}: {attr['hodnota']}")

# Spisová značka — tolerantní parser
spis = parse_spis_zn("1T64_2024")
print(spis.canonical())  # "1 T 64/2024"
print(spis.compact())    # "1T64_2024"

# Fuzzy vyhledání soudu
code = client.resolve_court_name("melnik")  # → "OSSTCME"
code = client.resolve_court_name("praha 9") # → "OSPHA09"

# Seznam soudů
courts = client.build_court_map()  # {kód: název} pro všech 104 soudů
```

### Formáty spisové značky

Parser je maximálně tolerantní — všechny tyto formáty jsou ekvivalentní:

```
1 T 64/2024       1T64/2024       1T 64/2024
1 T64/2024        1T64_2024       1 T 64 / 2024
```

Kód soudu lze přidat za sp. zn.: `1T64_2024 OSSCEDC`

Místo kódu soudu lze zadat název: `4 T 21/2025 melnik` (bez diakritiky)

## API endpointy

| Endpoint | Metoda | Popis |
|----------|--------|-------|
| `/api/v1/rizeni/vyhledej` | POST | Vyhledání řízení |
| `/api/v1/jednani/vyhledej` | POST | Vyhledání jednání |
| `/api/v1/udalost/vyhledej` | POST | Detail události |
| `/api/v1/organizace/lov` | GET | Seznam krajských/vrchních soudů |
| `/api/v1/organizace/podrizene/lov` | GET | Seznam okresních soudů |

Base URL: `https://infosoud.gov.cz/api/v1`

## Kódy soudů

Kompletní seznam 104 soudů (96 z API + 8 poboček):

```bash
infosoud --courts
```

Příklady: `OSSCEDC` (OS Děčín), `OSPHA09` (OS Praha 9), `KSJIMBM` (KS Brno), `MSPHAAB` (MS Praha)

## Webové rozhraní

```bash
pip install infosoud[web]
python -m infosoud.web
```

Otevře webserver na `http://localhost:8060` s vyhledávacím formulářem, timeline událostí, ICS exportem jednání a CSV exportem.

## Licence

MIT — viz [LICENSE](LICENSE)

---

*Neoficiální nástroj. Data pocházejí z [infosoud.gov.cz](https://infosoud.gov.cz). Projekt [pravnikovo.info](https://pravnikovo.info) — open source nástroje pro právníky.*
