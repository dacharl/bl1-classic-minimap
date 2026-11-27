# PLAN_MUTATION_NEXT: what the timed full mutation run says to do next

Status: proposed (2026-11-26). Nothing here is implemented. Evidence: two full runs after PHASE3 §3cg on Windows,
Python 3.13, 8 workers, 13,062 mutants, 65 min each, identical outcomes; the second logged every mutant's duration
(`dist/ci/mutation-times.jsonl`, `tools/mutation_times.py`). Every file passes its floor.

## 1. Evidence

### Where the time goes (worker seconds; 30,903 s in all = 64.4 min on 8 workers)

| File | Share | Killed (mean s) | Survived (mean s) | Timeouts (s) |
|---|---:|---:|---:|---:|
| `swfbuild.py` | 40.1% | 3,160 (1.4) | 898 (**8.8**) | 8 (163) |
| mod `__init__.py` | 30.7% | 2,802 (1.6) | 888 (5.5) | 0 |
| profiler `profiler.py` | 9.9% | 762 (2.5) | 138 (3.4) | **34 (685)** |
| `swfmerge.py` | 5.8% | 1,484 (0.8) | 276 (1.8) | 2 (40) |
| `as2asm.py` | 4.1% | 831 (1.1) | 75 (3.9) | 4 (81) |
| `swfdeps.py` | 3.7% | 502 (0.8) | 116 (5.4) | 5 (100) |
| `hudmovie.py`, `upk.py`, packager, profiler `__init__` | 5.7% | | | 11 (221) in `upk` |

- **`swfbuild` survivors alone are 7,928 s, a quarter of the run.** A survivor runs its whole six-entry list, two
  of which (`test_ci` cases) build complete movies.
- **Timeouts cost 1,290 s** (each waits out the 20 s limit). 10 of the 34 in the profiler are one condition,
  `if self.state != "collecting":` mutated, which makes a test wait forever instead of failing.
- A process costs about 0.7 s; a kill in an in-process suite (`swfmerge`, `upk`, `swfdeps`) averages 0.8 s, a kill
  that needs the stubbed mod (`test_ci` mod case, `test_profiler`) 1.6 to 3.3 s.

### Where the survivors are (not killed, by top-level function)

- **`swfbuild.py` (906), by responsibility:** art 410 of 2,033 (20%: `glyph_text`, `original_art`, `logo_paths`,
  `polygon_shape`), assembly 156 of 438 (36%: `build`, `main`), AS2 code 143 of 625 (`new_functions`), constants
  98 of 315 (31%), records 99 of 655 (15%). The records survivors are a real gap: `translate_matrix`, `sb`,
  `signed_bits` and `rect_bytes` have no byte-level test (for example `to_bytes(len(bits) * 8, …)` survives).
- **Mod (888):** module constants 90 (40% of theirs survive), `tick` 70, `anchor_transform` 57, `capture` 39,
  `threat_points` 38, `coord_scale` 33 (38%), `merge_into` 28 (39%); 33 `ExceptionReplacer` survivors in
  `except Exception:` recovery paths.
- **`swfmerge` (278):** `function_names` 44 (35%), module constants 43, `walk_shape` 35, `split` 24.
- **profiler (172):** `Profiler._publish` 29, `start` 13, `utc_now` 13 (37%).
- **`swfdeps` (121):** `Movie.refs` 49 (also the PlaceObject3 class-name offset noted in §3cf), the CLI's printout.
- **`hudmovie` (57):** `provide` 27, `default_vdfs` 13, `find_enhanced` 11 (Steam library discovery).

### Structure

- `swfbuild.py` (1,118 lines) holds four responsibilities: SWF record writing, AS2 code generation
  (`new_functions`, 524 lines in one function), art (Enhanced copy, original glyphs and box, the save logo) and
  movie assembly. Its suite list must cover all four, so every mutant pays for the movie-building cases.
- The mod's `__init__.py` (1,720 lines, 96 top-level definitions) mixes SDK hooks and lifecycle, pure geometry
  (`anchor_transform`, `coord_scale`, `fit_zoom`, `to_map`, `threat_points`, `save_spot`: about 1,100 mutants),
  marker collection, movie commands, visibility gating and `State`. The pure parts are tested only through the
  stubbed mod, at 1.6 s a kill.

## 2. Plan (in order; each is one branch and one PHASE3 entry)

### A. Cheap test gaps (no structural change)

1. **SWF record bytes** in `test_builder_formats.SwfRecordChecks`: `translate_matrix` (zero, positive, negative,
   mixed widths), `sb`, `signed_bits` and `rect_bytes`, `top_level`, worked by hand from the MATRIX and RECT
   formats. Expected: most of the 99 records survivors.
2. **Profiler hangs become failures:** the tests that wait for the profiler to finish get an iteration or clock
   bound that fails the test (for example a fake clock that raises after N reads). Expected: about 30 of 34
   timeouts become kills, about 600 s of worker time saved.
3. **Mod geometry with worked values** from recorded anchors (PHASE3 runs), for `anchor_transform`,
   `coord_scale`, `fit_zoom`, `to_map`; each `except Exception:` branch of `tick` driven once.
4. **`swfmerge.function_names` and `split`** with authored DoAction bytes and truncated movies; **`swfdeps.refs`**
   PlaceObject3 with a class name (fixes the §3cf offset observation, test first).
5. **`hudmovie` Steam discovery:** table tests of `libraryfolders.vdf` text and the Enhanced lookup.

### B. Speed (keeps scope, denominators and floors)

6. **Fewer processes per survivor:** `test_builder_formats`, `test_swfmerge` and `test_hudmovie` import no SDK
   stubs and could share one process inside `test_mutants.py` (one `unittest` run over the three modules). A
   `swfbuild` survivor would run 4 processes instead of 6: about 1,250 s of worker time (2.6 min wall). Keep the
   hang layers: the shared process is still one watched child. Check first that the three suites are independent
   in one process (they are in the default unit run's per-suite processes, not proven together).
7. **Re-probe the lists after A** (new tests change who kills first) with `MINIMAP_SUITE_PROBE`, and once per file
   run its full list against everything to confirm no kill is lost.

### C. Structure (a separate decision: per-file denominators change)

**Decided 2026-11-26:** item 8 (the builder split) is accepted for before 1.0.0, planned in
[PLAN_BUILDER_SPLIT](PLAN_BUILDER_SPLIT.md); item 9 (the mod's geometry) is out of scope. Floors for every file are
set at measured minus 3 (section D).

8. **Split `swfbuild.py`** into `swfrecords.py` (tag, place, sprite, BitWriter, rect, matrix; `swfmerge` and
   `swfdeps` would share its readers), `hudart.py` (Enhanced copy, original art, save logo), `hudscript.py`
   (`new_functions` broken into one builder per root function) and `swfbuild.py` (assembly). Art and records
   mutants then need only their unit tests and one movie case, not six suites.
9. **Split the mod's pure parts** into `geometry.py` (transforms, zoom, threat placement) and perhaps
   `visibility.py` (`hidden_reason`), tested in-process without SDK stubs; `__init__.py` keeps hooks, lifecycle and
   `State`.

Constraints for C (check each before starting):
- Each new file needs coverage and mutation floors in `pyproject.toml` and a `cosmic-ray.toml` entry
  (`quality_checks.py` requires both). Total scope is the same code, but per-file denominators change: that needs
  the user's agreement, and floors for the new files set from a measurement, not guessed.
- `build_sdkmod.py` must package the new files; the in-game build imports them as a package (relative imports with
  the plain-module fallback the builder files already use); the release byte check must still match.
- The profiler patches core names (`tick`, `current_hud_movie`); those must stay on the mod module.
- Behaviour unchanged: the built movie byte-identical (both art variants) and both real-movie suites green.

### D. Floors (after A, from a fresh full run)

10. Raise each floor to its measured score minus about 3 points (today that would be: mod 73, `swfbuild` 74,
    `swfmerge` 81, `hudmovie` 84, `as2asm` 88, `swfdeps` 77, `upk` 87, packager stays 80 at 84.6, profiler 88 and
    78), never lower one.

## 3. Expected effect

A and B together: roughly 55 to 60 min for a full run (timeouts and survivor processes), with higher scores. C is
the larger lever for `swfbuild` and the mod (their survivors and kills are 70% of the time) but is a design change.
