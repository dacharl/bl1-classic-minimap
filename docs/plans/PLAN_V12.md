# v0.12 plan: coexist with other HUD mods by merging at runtime (2026-10-25)

**Planned and grilled (decisions 1–12, 2026-10-25); implemented offline in v0.12.0 (PHASE3 §3ai). Step 0 (spike) and step 4 (in-game) are still to do.** Deviation from decision 2: the manifest is a Metadata tag in our own movie, not a second movie in the package (`upkpatch` can't add exports).

Run 17 (PHASE3 §3ag): on the Steam Deck the minimap stayed idle because **Extended Item Cards ("Extended UI" 1.3.2)** also replaces the HUD movie, and whichever mod sets the `hud_instance` template last wins. The user asked whether this can be solved dynamically instead of with a separate build per HUD mod.

## Confirmed decisions from grilling, round 1

The user accepted all four recommendations on 2026-10-25:

1. **Any foreign HUD movie that passes the structural checks is merged**, not only Extended UI's.
   There is no known-hash allowlist, so a new Extended UI version is either merged or refused with a
   message, never left idle until we release again.
2. **The minimap block ships prebuilt.** `swfbuild` writes a second movie into `GfxHUD_Minimap.upk`
   holding only our block, plus a block manifest: stock's prefix tag codes, our gradient count and our
   character id range. The runtime no longer diffs our movie against stock, so it never reads the stock
   HUD's `RawData`. This replaces "Extract our block" in plan step 1.
3. **A refused foreign HUD keeps the template.** The minimap stays idle and says why. We never take the
   template back from another mod, and there is no "prefer the minimap" option for now. See
   [ADR 0003](../adr/0003-merge-into-foreign-huds-never-override.md).
4. **The merge check runs on enable, in an `Engine.WorldInfo:IsMenuLevel` POST hook, and when a foreign
   HUD appears.** The POST hook returns at once when the template is ours or already merged. A HUD that
   has already spawned keeps its movie, so the minimap appears from the next level load, and the message
   says so.

## Confirmed decisions from grilling, round 2

The user accepted all four recommendations on 2026-10-25:

5. **Status is shown in three places at once:** the SDK log, a console line (the F7 path), and a short
   status line in the mod's MODS menu description ("Merged into …'s HUD", "Refused: id clash at 812",
   "Waiting for the next level load"). The MODS menu doesn't depend on any HUD, which run 17's
   console-only hint did.
6. **No disk cache.** The merge runs once per session in memory and logs how long it took. A cache keyed
   on the foreign movie's hash becomes a follow-up only if in-game timing exceeds about 1 s.
7. **Disable restores exactly what we replaced**, the foreign movie object, and only while the template
   still points at our merged object; otherwise it leaves the template alone and logs that. Re-enabling
   in the same session reuses the merged object while the foreign movie object is unchanged.
8. **Tests use a synthetic fixture HUD** from `ci_fixture.py`: a stock-shaped prefix, an extra character
   range, its own `p1` and gradient records, with variants for an id clash, a prefix mismatch, a name
   clash and bad gradient accounting. A local-only check runs both real-movie suites against the movie
   merged with the real Extended UI HUD; the real-movie suites keep running against our own movie.

## Confirmed decisions from grilling, round 3

The user accepted all four recommendations on 2026-10-25:

9. **An in-game spike comes first** (plan step 0). If GFx won't load a constructed movie object, the
   fallback is writing the merged HUD movie into a small package in `CookedPC` and loading it with
   `load_package`, which means porting `upkpatch`'s repack into the mod.
10. **The splice lives in one module, `sdk_mods/classic_minimap/swfmerge.py`**, imported by both the mod
    and `swfbuild`: the tag walk, the prefix, id and name checks, the gradient shift and the splice. The
    offline suites exercise the code that runs in game, under the mod's coverage and mutation floors.
11. **The block manifest carries the mod version.** A mismatch with the `.sdkmod` is a merge refusal
    ("reinstall GfxHUD_Minimap.upk"), since the merge trusts the manifest's ids and gradient count.
12. **Rollout:** core v0.12.0 and profiler 0.1.3 (allowlist). With no foreign HUD movie, behaviour is
    unchanged. The in-game gate is plan step 4.

## Research (evidence)

### How Extended UI installs its HUD

Read from its public source (MOW531/MOW531-BL1-SDK-Mods, `Experimental mods/Extended Item Cards/Source`):
- **When:** `__init__.py` swaps movies in a `patch()` function that runs once, on the first `Engine.WorldInfo:IsMenuLevel` call (a PRE hook). That's after all mods load, so it always lands after our enable-time redirect.
- **What it sets:**
  - `GfxHUD.FlashInstances.hud_instance.MovieInfo` → `GfxHUD_MOD.FlashMovie.HUD`.
  - Likewise the status menu, bank, vending, mission and weapon-card movies.
  - It also sets `KEEP_ALIVE` on several objects.
  - It never restores anything.
- **What its code needs:** `hud.py` drives its HUD with `SingleArgInvokeS`/`SetVariableString` on paths only its movie has (`inventory.card1`, `p1.outerequip.equipcard`, `reloadspeed.text`, `funstatsmod.htmlText`, `p1.ring.health.bar.gotoAndStop`), and sets `TickRateSeconds` ("Smooth HUD"). Re-pointing the template back to our movie would break it.

### Why not extend the GFx script API

- **No newer clip APIs:** classic's `GFxMovie` has `Invoke`, which crashes on its unfilled return (PROGRESS fact 2), and `SetVariable*`, but none of the later `GFxObject` clip APIs (`AttachMovie`, `CreateEmptyMovieClip`).
- **Single-argument invokes only:** `WillowGFxMovie` has just `SingleArgInvokeS`/`F`/`B`/`SF`, and every AS2 clip-creating method needs two or more arguments.
- **No reusable helper:** the stock HUD's 37 root functions never attach or load a clip.
- **The `loadMovie` bootstrap** (loading a separate minimap movie into an existing clip) would need a clip that's safe to destroy in every HUD. It is not pursued.

### Their movie against ours

Their package was downloaded from the repository for offline analysis (`GfxHUD_MOD.upk`, 20,197,427 bytes, SHA-256 `6a6e29d1…e489`; kept in the session scratchpad, never committed). Its HUD movie was extracted with `tools/upkpatch.py` (666,106 bytes) and compared with the stock classic HUD and our movie (scratchpad `mergecheck.py`, `p1check.py`):

| Check | Result |
|---|---|
| Characters | Stock has 763 (max id 764). Theirs adds 66 (765–830), ours adds 102 (1043–1311). **No clash.** |
| Insertion point | First `ShowFrame` at top-level tag 158 in both stock and theirs. |
| Gradients (PHASE3 §3ab) | Theirs is identical to stock: 4 fills before the insertion point, 14 in total, 14 tag-1003 records with ids 0–13. |
| External images (1001/1009) | Theirs has the same 54 as stock; our block adds none. |
| Exports, root functions | No clash with `bl1mm_*` or any of our 17 root function names. |
| `p1` (dock, HUD shift) | Same sprite 761, same placement, the same 18 named children (`echo` included). |

### The merge, done offline

Scratchpad `mergemovie.py`:
1. Take our block: the 105 top-level tags (174,283 bytes) our build inserts before stock's first `ShowFrame`, found as "our movie minus stock".
2. Splice it into their movie at the same point.
3. Shift their 1003 ids with `swfbuild.shift_gradient_images`.

Result (840,389 bytes):
- **Their textures kept:** every original shape keeps its external gradient image.
- **Our suites pass:** `tools/test_minimap_as.py` and `tools/test_minimap_mod.py` both pass against it (13 root functions, attach and fallback paths, dock, zoom, edges, threats).
- **Their code untouched:** their own AS is unchanged, since nothing after the insertion point moves except the 1003 ids. Our suites can't exercise their features.

## Plan

0. **Spike (PC, decision 9):** a throwaway console command constructs a `GFxMovieInfo` (`KEEP_ALIVE`)
   holding a copy of our own movie's bytes and texture references, points the template at it, and
   times the write. Change area: if the minimap appears, constructed movie objects work. If not, switch
   step 1's install to the package fallback before building anything else. Not committed.
1. **Merge at runtime (mod):**
   - **Hook:** `Engine.WorldInfo:IsMenuLevel` POST, which runs after Extended UI's PRE patch. Also run the check on enable and when a foreign HUD appears (the current `stockhud` phase).
   - **Detect:** the template's `MovieInfo` is neither ours nor stock.
   - **Load our block:** read the prebuilt minimap block movie and its block manifest from `GfxHUD_Minimap` (decision 2). No game data ships in the `.sdkmod`.
   - **Check the foreign movie, refusing with a clear message on any failure:**
     - its prefix before the first `ShowFrame` has the same tag codes as stock's;
     - no character id clash;
     - no export or function name clash;
     - our gradient and 1003 accounting holds;
     - the block manifest's version matches the mod's (decision 11).
   - **Splice** with `swfmerge.py`, shared with `swfbuild` (decision 10).
   - **Install:** construct a new `GFxMovieInfo` (`KEEP_ALIVE`, fact 3) copying the foreign one's properties, especially its references to its textures, with the merged bytes. Point the template at it, and remember both so disable can restore the foreign `MovieInfo`, not stock's.
2. **Visible messages (decision 5):** when merging, refusing, or waiting for the next level load, log it, print a console line (the F7 path) and set the MODS menu status line, so a player sees why the minimap is or isn't there. Log the merge time (decision 6). This also fixes run 17's invisible hint.
3. **Tests (red first):**
   - the synthetic fixture HUD from `ci_fixture.py` (decision 8) merged: extra character range, its own `p1`, gradient ids shifted;
   - refusals: an id clash, a prefix mismatch, a name clash, bad gradient accounting, a manifest version mismatch;
   - `swfbuild`'s block movie and manifest match "our movie minus stock" exactly;
   - the template pointed at the merged object; disable restoring the foreign one only while the template is still ours; re-enable reusing the merged object (decision 7);
   - log, console and MODS menu status lines.
   - The real-movie suites keep running against our own movie. A local-only check runs them against the movie merged with the real Extended UI HUD.
4. **In-game (decision 12):** on the Deck with Extended UI enabled, both the minimap and Extended UI's cards, armor bars and smooth compass work; then on the Deck with Extended UI disabled; then a quick regression run on the PC.

## Unknowns

- **Runtime movie objects:** that GFx loads a movie from a `GFxMovieInfo` constructed at runtime from Python, and how long writing an 840 KB byte array through pyunrealsdk takes, once per session. Step 0 answers both.
- **Other HUD mods:** they may not share the stock prefix; the checks refuse those rather than guessing.
- **Extended UI's later versions:** they could change its movie. The checks run on every merge, so a new version is either merged or refused with a message.
