# Changelog

## [0.3.0] — 2026-10-25

### Added

- **`parse_query(text, court_map=None)`** — single-line query parser (new module
  `infosoud.query`, re-exported from `infosoud`). Accepts a značka with optional
  `sp. zn.` / `č. j.` prefix, číslo listu (`41 C 12/2024-58`), 2-digit years,
  and a court given as name (incl. locatives: `Krajský soud v Brně`), code or
  ISIR abbreviation (`KSBR`), before or after the značka. Also accepts
  InfoSoud (new and legacy), ISIR and pravnikovo.info URLs. Returns a frozen
  `ParsedQuery` (`spis_zn`, `court_code`, `cislo_listu`, `is_insolvency`,
  `source`, `court_hint`); raises `ValueError` with a Czech message when no
  značka is found.
- **`resolve_court(text, court_map)`** — resolve a court code, ISIR abbreviation
  or (locative) name to an InfoSoud court code.
- `parse_spis_zn` and `SpisZn` are now importable from the package root.
- pytest test suite (`tests/`), `dev` extra with pytest.

## [0.2.0] — 2026-04-10

### Fixed

- **Missing hearings when `/jednani/vyhledej` returns only cancelled entries**
  The hearings endpoint sometimes returns only cancelled/past hearings while
  future hearings are only in the case timeline (NAR_JED events). Previously
  the client returned immediately if the endpoint returned *any* data, even if
  all entries were cancelled. Now it falls through to the NAR_JED fallback
  when no active hearings are present.
  ([#1](https://github.com/pravnikovo/infosoud/issues/1))

- **Multi-day hearings not returned**
  NAR_JED events can contain a `jednani` sub-array with additional hearing
  days (e.g. a trial spanning 10.06 + 11.06). These sub-items were silently
  ignored. Now all hearing days are fetched and returned.
  ([#1](https://github.com/pravnikovo/infosoud/issues/1))

## [0.1.0] — 2026-04-02

### Added

- Initial release: CLI + Python client for InfoSoud API
- Tolerant sp. zn. parser (handles any whitespace/separator combo)
- Multi-word druh veci support (`3 P A NC 53/2026`)
- Auto-detection of Nejvyssi soud from druh veci
- Fuzzy court name resolution (`melnik` -> `OSSTCME`)
- Prague district auto-discovery (OSPHA -> OSPHA01-10)
- Case timeline, hearing details, case subject lookup
- JSON and CSV output
- Court code mapping with pobocky and extra courts
- Published on PyPI: `pip install infosoud`
