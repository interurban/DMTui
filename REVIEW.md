# Ward code-health review

This is the current file-by-file maintenance record. Historical product changes
and fixed defects live in `CHANGELOG.md`; keeping that history out of this file
makes the active cleanup decisions easier to audit.

## Bug hunt — August 2026

The post-cleanup hunt reproduced four boundary failures and added regression
coverage for each: negative dice modifiers crossing zero, healing-target
eligibility, encounter pointers whose saved scope disagreed with record
ownership, and malformed rows from D&D Beyond's unsupported external schema.
The fixes are deliberately at the shared logic/persistence boundaries so the
UI, recovery path, and future callers receive the same behavior.

## Cleanup pass — August 2026

The pass looked for unused imports and definitions, duplicated persistence and
UI plumbing, stale compatibility paths, broad exception handling, oversized
functions, unsafe subprocess use, and documentation that no longer described
the shipped product.

### Changed

| File | Cleanup |
| --- | --- |
| `app.py` | Removed unused Textual imports, formatted the modal imports, and moved folio-label presentation into `modals.py`, where menu rendering belongs. |
| `campaigns.py` | Replaced a private atomic-write copy with the shared persistence primitive and expanded a dense conditional return. |
| `ddb.py` | Combined the duplicated equipped-inventory walks for armor and shields into one pass. |
| `dmtui/cli.py` | Marked the legacy `main` re-export explicitly; this compatibility package is intentional, not abandoned code. |
| `encounter_store.py` | Replaced its private atomic-write copy with the shared persistence primitive. |
| `modals.py` | Consolidated repeated monster/spell search, selection, fetch, and list-rebuild behavior in `_SearchLibrary`; failed fetches now remain visible instead of being silently swallowed. Folio choice formatting moved here from `app.py`. |
| `persistence.py` | Added one tested atomic JSON writer that preserves the previous file and removes its temporary file when serialization fails. |
| `srd.py` | Made cache writes use the same atomic persistence path as user-owned data. |
| `tests.py` | Added behavioral coverage for failed atomic writes; the suite now exercises 80 unit cases. |
| `ward_backup.py` | Removed two more copies of atomic JSON-write and cleanup code. |
| `pyproject.toml` | Ships the new persistence module. |

### Inspected; deliberately unchanged

| File | Result |
| --- | --- |
| `battle.py` | Pure combat and dice logic remains cohesive and heavily exercised. No dead public definitions or imports were found. |
| `dm_screen.py` | Static read-only reference data is already isolated from encounter mutation. |
| `music.py` | Source configuration, backend selection, and subprocess ownership are separated cleanly; commands use argument lists rather than a shell. |
| `openai_client.py` | Shared request/config helpers already remove the earlier duplication. The optional integration remains isolated from core encounter use. |
| `widgets.py` | Small rendering-only module; no abandoned widget classes were found. |
| `ward/` | Canonical installed entry point and packaged music catalog are both active. |
| `dmtui/` | Retained only as the documented command/module compatibility alias. |
| `smoke.py` | Its long linear scenario is intentional: it records one end-to-end table session and catches navigation regressions. Splitting it would obscure sequence and shared state. |
| `requirements.txt` | Still matches the sole runtime dependency in `pyproject.toml` and remains the documented legacy install path. |
| JSON configuration/examples | Current schemas and product terminology match the runtime normalizers. |

### Remaining structural limits

- `app.py` is still the largest module because it owns Textual orchestration.
  A future split should follow stable product boundaries—campaign navigation,
  encounter actions, and reference integrations—not arbitrary line counts.
- `ddb.extract_combatant` is long, but its calculations share normalized
  character context. It was kept together after removing the duplicated
  inventory pass rather than fragmented into tightly coupled helpers.
- Compatibility reads for legacy `encounter.json`, `character_ids`,
  `VTT_OFFLINE`, and the `dmtui` launcher remain documented migration paths.
  Removing them would strand existing user data or scripts for little gain.

## Validation contract

Before cleanup is published, Ward must pass Python compilation, all unit tests,
the complete headless Textual smoke scenario, editable-package construction,
and whitespace validation. No live campaign data or real music stream is used
by those checks.
