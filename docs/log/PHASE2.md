# Phase 2: minimap HUD movie

Status, 2026-10-23: **built and verified offline.** Not yet run in game. The movie's minimap only appears when the Phase 3 SDK mod calls `MinimapCreate()`.

## 1. Build

```bash
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/GfxHUD.upk" FlashMovie.HUD dist/phase2/HUD_classic.gfx
python -I tools/upkpatch.py extract "<Borderlands>/WillowGame/CookedPC/Packages/Interface/menus_ingame_redux.upk" FlashMovies.status_menu dist/phase2/status_menu.gfx
python -I tools/swfbuild.py dist/phase2/HUD_classic.gfx dist/phase2/status_menu.gfx dist/phase2/HUD_minimap.gfx
python -I tools/test_minimap_as.py dist/phase2/HUD_minimap.gfx
python -I tools/upkpatch.py replace dist/phase1/GfxHUD.orig.upk FlashMovie.HUD dist/phase2/HUD_minimap.gfx dist/phase2/GfxHUD_minimap.upk
```

Both inputs come from the user's own install. Nothing from Gearbox is checked in.

**New tools:**

| Tool | Purpose |
|---|---|
| [tools/as2asm.py](../../tools/as2asm.py) | AS2 bytecode ⇄ IR (constant-pool references become literals; branch offsets are recomputed) and a small builder with an expression helper. Round-trips all 1,308 action blocks in the three movies. |
| [tools/swfbuild.py](../../tools/swfbuild.py) | Builds `HUD_minimap.gfx` (below). |
| [tools/test_minimap_as.py](../../tools/test_minimap_as.py) | Minimal AS2 interpreter. Runs the root functions **decoded from the built movie** against mock clips. |
| [tools/swfdeps.py](../../tools/swfdeps.py) | Character dependency closure (shapes, bitmaps, fonts, sprites). |

## 2. What the movie adds

On top of the stock classic HUD movie, with all 1,042 original root tags byte-identical and in order:

- **92 characters** from `status_menu.gfx`: the closure of `mask` (1040) + `maps` (1132), ids 1039–1132, about 156 KB. These are the vector zone art for every zone frame (`arid` … `trash`, plus the `dlcmap1` loader frame), the landmark icon clip (`objective`, `rstation`, `poi`, `transition`, `vss`, `bb`, `health`, `shop`, `newu`, `questionmark`) and the player icon clip (`player`, `buddy1..3`). No fonts, text fields or images.
- **Sprite 1200**, exported as **`bl1mm_map`**. It contains `mask` (depth 1, named), `mask` as a clip layer (depth 5 → clips to 18) and `maps` (depth 8), using the exact placement bytes from the status menu's `map` sprite (1154). It's **not on the timeline**, so the stock HUD looks unchanged until the mod attaches it.
- **Root functions** (frame-1 `DoAction`):

| Function | Origin | Called by | Behaviour |
|---|---|---|---|
| `AddLandmark(clip,x,y,r,frame)` | status menu + 1 addition | classic native | Duplicates the icon clip into `map.maps`. **Addition:** when `frame == "player"`, stores it in `_root.mmPlayer`. |
| `UpdateLandmark(clip,u,v,r)` | status menu | classic native | `_x = themap._x + u·themap._width` (and likewise for y); `_rotation = r`. `u,v` are `TransformedLocation`. |
| `SetMapScale(scale)` | status menu | native `ApplyScale` | Scales `themap` and centres it on the `maps` origin. |
| `InitDLC(frame,pkg)` | status menu | classic native | `LoadDLCPackage = pkg`, then `maps` goes to the `dlcmap1` frame, which loads the DLC map movie. |
| `SetMarkerColor(color,clip)` | status menu | — | Tints a clip. |
| `MinimapCreate(x,y,scale)` | new | SDK mod | `_root.attachMovie("bl1mm_map","map",9000)` once, then sets position and scale. |
| `MinimapDestroy()` | new | SDK mod | Removes `map` and clears the player and threat state. |
| `MinimapClear()` | new | SDK mod | Removes every dynamic child of `map.maps` (icons, dots), for a rebuild. |
| `MinimapRecenter(rotate,offset)` | new | SDK mod, each tick | Puts the player icon at the mask centre, overriding the native's edge clamp. When `rotate` is set, `maps._rotation = offset − player._rotation`. |
| `UpdateThreats("u,v\|…")` | new | SDK mod | A pool of red squares (`createEmptyMovieClip` + drawing API, ±5 px, depths 1000+) at `themap._x + u·themap._width`. Unused dots are hidden. |

## 3. Verification (offline)

| Check | Result |
|---|---|
| Original root tags unchanged and in order | 1,042 / 1,042 byte-identical |
| Header length field | matches the file (601,879 bytes) |
| Closure of sprite 1200 | 93 ids, none undefined |
| Id clashes with the stock HUD (1–764) | none |
| Root function behaviour (`test_minimap_as.py`) | all 10 functions pass: attach once and reuse, landmark placement from normalised coordinates, player capture, centring north-up and rotated (to 1e-6), threat pool grow/hide, clear removes dynamic clips only, `InitDLC`, destroy |
| Packaged `GfxHUD_minimap.upk` | movie extracts back byte-identical; +159,883 bytes; textures relocated (e.g. `HUD_G0` `0x6e374` → `0x953ff`); SHA-256 `ec972e36…7b18` |

**Limits:** the interpreter models AS2 semantics, not Scaleform. These still need an in-game check:
- `attachMovie` on `_root` with an exported symbol;
- `getInstanceAtDepth`;
- `createEmptyMovieClip` and the drawing API under GFx 3;
- how the clip layer behaves when `maps` rotates.

## 4. In-game checks

1. **Now, without the mod logic:** install `GfxHUD_minimap.upk` (same backup and restore as PHASE1 §3) and confirm the HUD looks **unchanged**. The minimap isn't on the timeline.
2. **With Phase 3:** the SDK mod calls `MinimapCreate`, drives `WillowGFxHelperMap` against the HUD (`Init` → `InitMapFrame` → poll `map.maps.themap._width` → `InitMapFrameVars`/`UpdateObjects(true)`/`ApplyScale`/`ApplyFlash`), then each `PlayerTick` at 20 Hz: `DesiredCenter` = player `TransformedLocation`, `UpdateObjects(false)`, `ApplyFlash`, `MinimapRecenter`, and `UpdateThreats` about 4×/s.
