# Ward code-health review

This is the current file-by-file maintenance record. Historical product changes
and fixed defects live in `CHANGELOG.md`; keeping that history out of this file
makes the active cleanup decisions easier to audit.

## Bug hunt — August 2026

The post-cleanup hunts read every tracked source module and reproduced eleven
boundary or state-transition failures. The first pass covered negative dice
results, healing-target eligibility, mismatched encounter scope pointers, and
malformed D&D Beyond collection rows.

The full-code pass added coverage for seven more cases:

| Area | Reproduced defect and resolution |
| --- | --- |
| Turn order | Removing the active creature could skip its immediate successor, and removing a creature before initiative could start combat. Removal now advances from the deleted slot only when a turn was active and increments the round only on a real wrap. |
| D&D Beyond | A mixed-format ability-score list could raise `AttributeError`; stat rows are now normalized independently, and malformed response bodies/import parsing fail with a user-facing error. |
| Open5e | Statblock actions with a negative damage modifier were discarded; the SRD parser now retains signed modifiers such as `1d4-1`. |
| Music | A failed pause/resume signal escaped as `OSError` after changing the displayed pause state; process errors are normalized and state changes only after a successful signal. |
| Campaign roster | JSON booleans were accepted as D&D Beyond character ID `1`, while zero/negative IDs were retained; only positive, non-boolean IDs now survive normalization. |
| Encounter ownership | Empty or whitespace-padded campaign names could split the campaign-free index from its records; ownership is now canonicalized at reads, creates, and moves. |
| Conditions | An unknown condition from newer or hand-edited state crashed both detail and initiative rendering; unknown string conditions now remain visible with a neutral fallback chip. |

These fixes remain at shared logic, persistence, and external-service
boundaries so UI flows and future callers receive the same behavior. The unit
suite now exercises 93 cases.

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
| `tests.py` | Added behavioral coverage for failed atomic writes; the cleanup pass brought the suite to 80 unit cases, and the subsequent bug hunts expanded it to 93. |
| `ward_backup.py` | Removed two more copies of atomic JSON-write and cleanup code. |
| `pyproject.toml` | Ships the new persistence module. |

### Inspected; deliberately unchanged

| File | Result |
| --- | --- |
| `battle.py` | Pure combat and dice logic remains cohesive and heavily exercised. No dead public definitions or imports were found. |
| `dm_screen.py` | Static read-only reference data is already isolated from encounter mutation. |
| `openai_client.py` | Shared request/config helpers already remove the earlier duplication. The optional integration remains isolated from core encounter use. |
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
