# Ward code-health review

This is the current file-by-file maintenance record. Historical product changes
and fixed defects live in `CHANGELOG.md`; keeping that history out of this file
makes the active cleanup decisions easier to audit.

## Bug hunt — August 2026

The latest phased read covered all tracked Python source in priority order:
state/persistence boundaries first, encounter mutations second, external-data
and asynchronous flows third, then rendering and regression infrastructure.
It reproduced and fixed thirteen additional failures:

| Priority | Area | Reproduced defect and resolution |
| --- | --- | --- |
| P0 | Turn start | Sorting initiative left the current pointer on the old first row, so `n` skipped the highest initiative. New and reset encounters now have no active turn; the first `n` starts the highest living creature without advancing the round. |
| P0 | Backup restore | Three independent atomic writes could leave a mixed-generation restore. All files are staged together and already-replaced files roll back if a later replace fails. |
| P1 | Empty/solo turns | A blank encounter's first creature and a solo encounter could begin on round 2. The explicit not-started state keeps both on round 1. |
| P1 | Map resize | Shrinking the terminal could strand tokens outside the visible grid. Invalid or colliding positions now reflow to visible free cells. |
| P1 | Snapshots | Shallow validation accepted malformed nested fields that crashed restore. Every combatant field used by restore is type-checked before mutation, while unknown future fields remain forward-compatible. |
| P1 | Templates | Selecting a corrupt template created and activated a blank encounter before failing. Corrupt entries are filtered and the flow validates before changing session state. |
| P1 | Cancellation | Escaping the encounter-generation modal caused the worker to dismiss it a second time. Cancellation is recorded and mounted screens are dismissed only once. |
| P1 | Targeting | Duplicate creature names resolved attacks to the first match. Target choices now carry stable row indices. |
| P1 | Rendering | Names, notes, actions, imported content, and errors could inject invalid Rich markup. Dynamic display text is escaped at rendering boundaries. |
| P1 | D&D Beyond | A structured character name could survive parsing and crash string consumers. Names and class/spell labels now accept only usable strings or safe fallbacks. |
| P2 | Initiative input | The inline editor could not enter negative initiative. A leading minus is now accepted and validated. |
| P2 | Dice input | `/roll` accepted an unbounded dice count and could block the UI. Rolls are capped at 1,000 dice. |
| P2 | Cache writes | Concurrent SRD fetches shared a fixed `.tmp` path. Atomic writes use unique sibling files and duplicate in-app fetches are coalesced. |

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
suite now exercises 107 battle/core cases, and the music and Tabletop Audio
provider suites bring the combined `python tests.py` gate to 133.

### Tabletop Audio provider audit — August 2026

The public-catalog module (`tabletop_audio.py`) and its music-flow integration
were reviewed as a fresh external-data boundary. Reproduced defects and their
resolutions:

| Area | Reproduced defect and resolution |
| --- | --- |
| Availability | One failed fetch dropped suggestions for the whole session; a valid 24-hour cache serves `fresh-cache`, and a failing refresh falls back to `stale-cache` metadata instead of raising. |
| Cache integrity | A malformed, empty, or mistyped cache entry crashed or emptied suggestions; entries are validated (timestamp shape, track list, field types) and re-fetched, and playing URLs are always derived from the validated slug, ignoring any `url` text planted in the cache. |
| Playback address | Scraped card text could be combined into an unsafe playback path; URLs are built only from `[A-Za-z0-9_]+` download ids against the fixed sounds host, loop by default, and go to `mpv`/`ffplay` with the catalog as referrer. |
| Flavor text | Paid "alternate versions … for Patreon" notices (including the adventure-PDF suffix) leaked into suggestion rows; promotion suffixes are stripped on both network parse and cache read. |
| Privacy | Party names could reach the AI helper through saved roster copies; encounter context strips PC names from both the live table and the persisted roster. |
| Cancellation | Cancelling a background search could dismiss a second, still-current modal during worker cleanup; only the still-current music modal is dismissed, and cancelled searches return cleanly to the music controls. |
| Phase filter | Key-case mismatches or substring matches (`inn` inside `beginning`) could widen or drop scene results; phase lookup is case-insensitive and require/boost terms match whole words. |
| Ranking | Description-only phase hits could outrank the tracks a scene is named for; title matches are weighted far above body matches, and the journey set uses travel-specific terms instead of generic setting words. |
| Packaging | The provider module was missing from the install package and the test gate; it ships in `py-modules`/package-data and `python tests.py` now also runs the `tests_music_ui` and `tests_tabletop_audio` suites. |

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
| `tests.py` | Added behavioral coverage for failed atomic writes; the cleanup pass brought the suite to 80 unit cases, earlier bug hunts expanded it to 93, and the phased full-code audit brought it to 107. The music and Tabletop Audio provider suites bring the combined gate to 133. |
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
