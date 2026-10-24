# Phase 1: GfxHUD.upk movie patcher

Status, 2026-10-23: **complete.** The tool works offline on both games' `GfxHUD.upk`. Classic loaded the resized package (all 71 later exports and 134 texture bulk offsets moved by +39) and the HUD rendered normally (section 3). The original is restored. Phase 2's design questions are closed (section 4).

## 1. The tool

[tools/upkpatch.py](../../tools/upkpatch.py):

```bash
python -I tools/upkpatch.py extract  <in.upk> FlashMovie.HUD <out.gfx>
python -I tools/upkpatch.py replace  <in.upk> FlashMovie.HUD <in.gfx> <out.upk>
python -I tools/upkpatch.py selftest <in.upk> [FlashMovie.HUD]
```

`replace` re-parses its own output before writing, and refuses to overwrite the input package.

**What it changes (Observed layout of classic `GfxHUD.upk`, v584, 73 exports):**
- **The movie itself.** `FlashMovie.HUD` (`GFxMovieInfo`) stores the GFx file in its `RawData` `ArrayProperty<byte>`: a tag with size = 4 + n, then an int32 count n, then the bytes. The tag size and count are rewritten; the other properties (`References`, `bUsesFontlib`, `SourceFile`, …) are copied unchanged.
- **The export table.** The header, name, import and export tables all sit before the first export's data (`headerSize = 0x2268` = the first export's offset). So nothing in the header moves. Only each later export's `SerialOffset` (entry +36) and the movie's `SerialSize` (entry +32) are rewritten.
- **Bulk-data offsets.** Every `Texture2D` holds cooked bulk-data records (flags, count, size on disk, **absolute offset in file**). Each texture has two (source art and mip 0). When an export moves, any int32 equal to `old_offset + pos + 4`, with a size field that fits, is rewritten to the new position. It found exactly 134 = 2 × 67 textures in classic and 234 = 2 × 117 in Enhanced, and none in any other export.
- **Nothing else references file positions.** There's no TOC or hash file under `WillowGame` and only one `GfxHUD.upk`. `CookedPC/Patch` holds only DLC definitions and `GuidCache_dlc*`. The package GUID in the header is unchanged.

## 2. Offline results

| Check | Classic | Enhanced |
|---|---|---|
| Round trip (same movie) | byte-identical, SHA-256 `5c515c3e…3ea88` = game file | byte-identical |
| Grow movie by 39 bytes (Metadata tag 77 added) | 71 exports moved by +39, all 134 bulk offsets consistent, other bytes unchanged | 121 moved, 234 consistent |
| Shrink movie by 16 bytes | 71 moved by −16, consistent | 121 moved, consistent |

Produced in `dist/phase1/`:
- `HUD_classic.gfx`: the classic HUD movie, extracted (441,996 bytes).
- `GfxHUD_roundtrip.upk`: identical to the game file.
- `HUD_classic_padded.gfx` / `GfxHUD_sizetest.upk`: the same movie with one harmless Metadata tag; the package is 39 bytes larger and every texture has moved.

## 3. In-game check: not a valid test

**Correction (PHASE3 §3d):** classic `WillowGame.u` carries its own cooked copy of `GfxHUD.FlashMovie.HUD` and loads it at startup, so the game **never reads `GfxHUD.upk`**. The "HUD rendered normally" result below therefore says nothing about relocation. The minimap now ships as a separate package, `GfxHUD_Minimap.upk`, loaded by the SDK mod, and the first real test of a resized package is the minimap itself.

**Original result (2026-10-23):** with `GfxHUD_sizetest.upk` installed, the HUD rendered normally in game. The original was then restored, and its SHA-256 `5c515c3e…3ea88` matches. The steps used:

This checks the one thing offline tests can't: that the game loads a package whose exports and texture bulk data have moved.

1. Back up `WillowGame\CookedPC\Packages\Interface\GfxHUD.upk`, for example by copying it to `dist\phase1\GfxHUD.orig.upk`.
2. Copy `dist\phase1\GfxHUD_sizetest.upk` over it, keeping the name `GfxHUD.upk`.
3. Launch and load a character. Check that:
   - the HUD draws (health, shield, ammo, XP bar, compass);
   - **button-prompt icons and weapon-slot textures** show (these are the moved `Texture2D`s: `xbox360_*`/`ps3_*`, `weaptex*`, `HUD_G*`/`HUD_I*`);
   - picking up an item shows its card.
4. Put the original back. Comparing SHA-256 `5c515c3e…3ea88` confirms the restore.

If textures come out black or garbled, the bulk-offset rewrite is wrong for this engine build. If the game crashes on loading the HUD, check `My Games\Borderlands\WillowGame\Logs\Launch.log`.

**Status:** the original is back in place. The backup stays at `dist\phase1\GfxHUD.orig.upk` (SHA-256 `5c515c3e…3ea88`). To restore it after any later test:
```bash
cp dist/phase1/GfxHUD.orig.upk "/c/Program Files (x86)/Steam/steamapps/common/Borderlands/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk"
```

## 4. Phase 2 decisions (closed 2026-10-23)

| Question | Decision | Evidence |
|---|---|---|
| Where the zone art comes from | **Copy the `map` tree (sprite 1154) from `status_menu.gfx` into the HUD movie. No new package exports are needed.** Classic zone maps are *vector* `DefineShape4` art (e.g. Fyrestone's `themap` is a 13,983-byte shape), not textures. The tree contains no external images. The textures in `menus_ingame_redux.upk` (72 exports, 324 KB) are button and UI images. Enhanced, by contrast, switched its map art to texture-backed images, which is why its `GfxHUD.upk` is bigger. | [tools/swfdeps.py](../../tools/swfdeps.py): closure of sprite 1154 is 118 characters, 167 KB (48 shapes, 52 sprites, 16 text fields, font 85). No `DefineExternalImage` or bitmaps. |
| Character id clashes | Only **font 85** needs a new id. The classic HUD defines ids 1–764, and the map tree uses 1039–1154. | `swfdeps.py`, `Movie.defs` |
| Fonts | Font 85 is `WillowHead` with **0 glyphs**, a placeholder resolved from the shared font library by name. The classic HUD has `bUsesFontlib = 1`, so copying it as-is works. | `DefineFont3` records, `GFxMovieInfo.bUsesFontlib` |
| Legend text fields | **Leave them out.** The 13 legend labels (`Leg_Waypoint`, `Leg_Player`, …) use font id 58, which isn't defined anywhere in `status_menu`. The minimap doesn't show a legend. The native's writes to `map.Leg_*` / `map.buddy%d._visible` then hit missing paths, which are harmless (Phase 0 showed missing GFx paths read back as `Infinity` without errors). | EditText records 1136–1152 |
| How to edit the Flash | **Scripted rewriter** (`tools/swfbuild.py`, to write). It copies the closure into `HUD_classic.gfx`, remaps ids, places the root `map` clip and appends root ActionScript. The result is reproducible, and the mod ships as a patcher run against the user's own files instead of redistributing Gearbox art. | — |
| DLC zone maps | The native calls root **`InitDLC(frame, dlcPackage)`** (classic version: `LoadDLCPackage = dlcPackage; map.maps.gotoAndStop(frame)`). Frame `dlcmap1` of `maps` then runs `loadMovie(_root.LoadDLCPackage, "themap")`. **Add the same root `InitDLC` to the HUD.** The frame logic comes along with the copied `maps` sprite. | `status_menu.gfx` `InitDLC`, sprite 1132 frame 30; `dlc1_maps.upk` has 6 `dlcmap_*` movies |
| When the map frame is ready | Classic `WillowHUDGFxMovie` has **no `extInitComplete`** (its `ext*` functions are only `extResAnimFinished`, `extBearingStripDirty`, …), so the DLC movies' `ExternalInterface.call("extInitComplete")` has nowhere to go. **The SDK mod polls instead:** after `InitMapFrame`, it waits until `map.maps.themap._width` is finite and > 0, then runs the `extInitComplete` sequence (`InitMapFrameVars`, `UpdateObjects(true)`, `ApplyScale`, `ApplyFlash`). | classic `WillowHUDGFxMovie` exports |
| Name clashes at the HUD root | None. The classic HUD has no root `map` clip and no `AddLandmark`, `UpdateLandmark`, `SetMapScale`, `InitDLC`, `ClearLandmarks`, `RemoveLandmark` or `UpdateThreats`. | `C_HUD.gfx` listing |
| Edge clamp | Each tick, the SDK mod calls a new root AS **`MinimapRecenter()`** after `UpdateObjects`/`ApplyFlash`. It sets `map.maps._x/_y` so the player icon sits at the mask centre: `mask.c − player._x · scale`. Inside the art this matches the native's own result (`DesiredCenter` = player); near the edges it undoes the native clamp. Rotation mode then rotates around the same centre. Watch for jitter against the native's easing in the first Phase 3 build. | PHASE0 §2d centring formula |
| Tick source | **`WillowPlayerController.PlayerTick`** (flags `event`, with a script body, so it goes through `ProcessEvent`), throttled to 20 Hz. `GameViewportClient.Tick` (`event`) is the fallback. | function flags |
| Split-screen | **v1 supports player 1 only.** The classic native only knows one root `map`. | REPORT §3, Phase 4 |

**Still open:** nothing for Phase 1. Next is Phase 2: write `tools/swfbuild.py` and build the minimap HUD movie.
