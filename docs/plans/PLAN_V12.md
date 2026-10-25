# v0.12 plan: coexist with other HUD mods by merging at runtime (2026-10-25)

**Planned, not implemented.**

Run 17 (PHASE3 §3ag): on the Steam Deck the minimap stayed idle because **Extended Item Cards ("Extended UI" 1.3.2)** also replaces the HUD movie, and whichever mod sets the `hud_instance` template last wins. The user asked whether this can be solved dynamically instead of with a separate build per HUD mod.

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

1. **Merge at runtime (mod):**
   - **Hook:** `Engine.WorldInfo:IsMenuLevel` POST, which runs after Extended UI's PRE patch. Also run the check on enable and when a foreign HUD appears (the current `stockhud` phase).
   - **Detect:** the template's `MovieInfo` is neither ours nor stock.
   - **Extract our block:** read the stock HUD bytes from `GfxHUD.FlashMovie.HUD` (always loaded from `WillowGame.u`, PROGRESS fact 1) and our movie's bytes from `GfxHUD_Minimap`, and take our movie minus stock. No game data ships in the `.sdkmod`.
   - **Check the foreign movie, refusing with a clear message on any failure:**
     - its prefix before the first `ShowFrame` has the same tag codes as stock's;
     - no character id clash;
     - no export or function name clash;
     - our gradient and 1003 accounting holds.
   - **Splice** (port the `swfbuild` splice and gradient shift into the mod, with tests).
   - **Install:** construct a new `GFxMovieInfo` (`KEEP_ALIVE`, fact 3) copying the foreign one's properties, especially its references to its textures, with the merged bytes. Point the template at it, and remember both so disable can restore the foreign `MovieInfo`, not stock's.
2. **Visible messages:** when merging, refusing, or finding an unknown HUD, log it and print a console line (the F7 path), so a player sees why the minimap is or isn't there. This also fixes run 17's invisible hint.
3. **Tests (red first):**
   - an offline fixture HUD with an extra character range and its own `p1`;
   - an id clash refused;
   - a prefix mismatch refused;
   - gradient ids shifted;
   - our block extracted exactly;
   - the template pointed at the merged object, and disable restoring the foreign one;
   - console lines.
   - The real-movie suites keep running against our own movie. A local check runs them against the merged Extended UI movie.
4. **In-game (Deck, with Extended UI enabled):** both the minimap and Extended UI's cards, armor bars and smooth compass work; then the same with Extended UI disabled.

## Unknowns

- **Runtime movie objects:** that GFx loads a movie from a `GFxMovieInfo` constructed at runtime from Python, and how long writing an 840 KB byte array through pyunrealsdk takes, once per session.
- **Other HUD mods:** they may not share the stock prefix; the checks refuse those rather than guessing.
- **Extended UI's later versions:** they could change its movie. The checks run on every merge, so a new version is either merged or refused with a message.
