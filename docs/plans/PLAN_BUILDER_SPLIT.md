# PLAN_BUILDER_SPLIT: split the movie builder by responsibility, before 1.0.0

Status: accepted (2026-11-26), not started. Follows [PLAN_MUTATION_NEXT](PLAN_MUTATION_NEXT.md) section C.

## Decisions (the user, 2026-11-26)

1. **Floors:** each file's coverage and mutation floors are set at its measured value minus 3 points (rounded down),
   from a measurement taken after the split and after the tests of PLAN_MUTATION_NEXT section A. Mutation floors
   never go below 70. This also applies to the files that are not split (PLAN_MUTATION_NEXT section D).
2. **Scope:** split options a and b: the SWF record code into its own file, then the art and the AS2 code into
   theirs. The mod's own `__init__.py` is not split.
3. **Timing:** before 1.0.0.
4. **Out of scope:** moving the mod's pure geometry (`anchor_transform`, `coord_scale`, `fit_zoom`, `to_map`,
   `threat_points`) into a `geometry.py` (option c). It would change code that runs every frame in game and would
   need an in-game run; it can be planned after 1.0.0.

## Evidence (PHASE3 §3cg, timed full run)

- `swfbuild.py`: 1,118 lines, 4,066 of 13,062 mutants, 40% of the run's worker time. Its survivors (898) run its
  whole six-entry suite list at 8.8 s each, a quarter of the run, because one file holds four responsibilities and
  its list must cover all of them, including two `test_ci` cases that build whole movies.
- Survivors by responsibility: art 410 of 2,033, assembly 156 of 438, AS2 code 143 of 625 (`new_functions`, 524
  lines in one function), constants 98 of 315, records 99 of 655.
- `swfmerge.py` and `swfdeps.py` read the same tag headers and fields as `swfbuild` writes (shared since §3cg
  through `swfmerge.u16`, `header`, `words`).

## Target layout (all in `sdk_mods/classic_minimap/`)

| File | Holds | From |
|---|---|---|
| `swfrecords.py` | Tag codes and flag bits, `u16`/`u32`/`words`/`header`, `tag`, `read_tags`, `skip_rect`, `top_level`, `raw_id`, `twips`, `place`, `sprite`, `one_frame_sprite`, `translate_matrix`, `sb`, `BitWriter`, `signed_bits`, `rect_bytes`, `rgba` | `swfbuild`, `swfmerge` |
| `hudart.py` | `enhanced_art`, `art_wrappers`, `wrapper_sprite`, `original_art`, `font_record`, `glyph_text`, `glyph_sprite`, `polygon_shape`, `paths_shape`, `logo_paths`, `save_art`, `landmark_frames` and their constants | `swfbuild` |
| `hudscript.py` | `root_actions`, `copied_functions`, `add_player_capture`, and `new_functions` broken into one builder per root function (`MinimapCreate`, `MinimapCmd`, ...) | `swfbuild` |
| `hudlayout.py` (if needed) | Character ids, depths, export names, the window rectangle: the constants that art, script and assembly share, so the three never import each other | `swfbuild` |
| `swfbuild.py` | `build`, `map_sprite`, `place_fallback`, `shift_gradient_images`, `core_version`, `main` | stays |

- **Imports:** every new file uses the relative import with the plain-module fallback the builder files already use
  (in-game package; `tools/` wrappers and the offline suites put the folder on `sys.path`). No import cycles:
  records ← art, script ← assembly; `swfmerge` and `swfdeps` import from `swfrecords`.
- **Names kept:** `swfbuild` keeps the names other code imports (`build`, `tag`, `top_level`, `EXPORT_NAME`,
  `core_version`, `WINDOW_*`: `hudmovie`, `ci_fixture`, `release.py`, `test_ci`, `test_minimap_as`,
  `test_minimap_mod`, `test_swfmerge`, `test_workflow`), and `swfmerge` keeps `tag`, `read_tags`, `Bits` and
  `MergeRefused` for the mod and the suites. Moved names are re-exported, not duplicated.
- **Packaging:** `tools/build_sdkmod.py` packages the whole mod folder, so new files ship without a change (no file
  list exists to update); `quality_checks.py` requires coverage and mutation floors for every shipped `.py` file,
  which step 4 provides. Check the built `.sdkmod` lists the new files.
- **Not touched:** the movie paths the native helper writes to and the root functions it calls (AGENTS), the mod's
  `__init__.py` (its `BOX_MARGIN` copy of `swfbuild.BOX_MARGIN` stays as it is).

## Steps (one commit each, Conventional Commits, test first where behaviour is pinned)

1. **`swfrecords.py`:** move the record code; `swfmerge`, `swfdeps` and `swfbuild` import it. Move
   `SwfRecordChecks` to target it, and add the missing byte tests (PLAN_MUTATION_NEXT A1: `translate_matrix`, `sb`,
   `signed_bits`, `rect_bytes`, `top_level`), red first against a deliberately wrong expectation where a value is
   new.
2. **`hudart.py`** (and `hudlayout.py` if the constants need a home): move the art; table-driven tests for the
   glyph text record and the polygon and paths shapes against hand-worked bytes, and properties of `logo_paths`
   (closed paths, mirror symmetry, every point inside the ring radius).
3. **`hudscript.py`:** move the AS2 code, then break `new_functions` into one builder per root function, each
   returning the same IR as today (compared function by function against the pre-split IR in a test).
4. **Configuration:** add the new files to `cosmic-ray.toml` and to `pyproject.toml` with provisional floors equal
   to `swfbuild`'s today (coverage 97 line / 78 branch, mutation 70), so `quality_checks.py` passes until step 6.
   Add each file to `SUITES_BY_FILE` with all suites (the safe default) until step 5 measures it.
5. **Measure the lists:** probe the new files (`MINIMAP_SUITE_PROBE`), set their lists, and run each file once with
   its list against every suite to confirm no kill is lost (as §3cg did for `swfmerge`).
6. **Full run and floors:** after PLAN_MUTATION_NEXT sections A and B, one full run; set every file's floors to
   measured minus 3 (decision 1) in one commit, with the table in PHASE3.

## Validation (each step)

- The built movie byte-identical to the pre-split build, both art variants, from `dist/phase2` inputs.
- Both real-movie suites on both variants; the unit run with every coverage floor; Ruff; `quality_checks.py
  repository`.
- Before landing: `python -I tools/release.py --game <Borderlands> --enhanced <Enhanced>`, whose in-game-build
  byte check proves the mod builds the same movie from the installed packages through the split code.
- The PHASE3 entry records mutant counts per file before and after, the probe lists and the full-run scores.
- No in-game run is planned: the in-game build's output is proven byte-identical. If any step changes bytes, stop:
  that is a behaviour change outside this plan.

## Expected effect

- Art and records mutants (about 2,700) need their unit suites and at most one movie case, not six suites, so their
  survivors cost about 2 to 3 s instead of 8.8 s; with sections A and B, a full run should drop well under an hour
  (an estimate; step 6 measures it).
- Smaller files with one job each, and `new_functions` in reviewable pieces.
