# PLAN_V15: the autosave indicator beside the map

The classic autosave icon covers the docked minimap (PHASE3 §3an finding 2). This plan replaces it, while the minimap
is docked, with our own copy of the game's indicator, moved left the way the ECHO panel is.

## Research

**The native icon (§3ax, §3ay):**
- `WillowHUD` draws `SavingMat = HUD.Materials.SavingIndicator_INST` natively on the canvas, above all GFx. Its
  position is fixed in native code: neither edition has a position property.
- **Fields:** `SavingMaterialScale` 0.5, `SaveStartTime` and `SaveDuration`.
- **A save (run 33)** sets `SaveDuration` 3.0, and the game resets it to 0 about 3 s later. `SaveStartTime` uses
  another clock than `WorldInfo.TimeSeconds`. The icon shows while `SaveDuration > 0`.
- `NotifySavingStarted`/`Complete` are native-to-native, so hooks on them never fire. The mod polls `SaveDuration`.

**The art** (`WillowGame\CookedPC\Test\Interface\HUD.upk`, read with `upkprops.py`):
- `Texture2D'HUD.Textures.saving_indicator'`: 128 × 128, `PF_G8` (grayscale), `TC_Grayscale`, UI group.
- `Material'HUD.Materials.SavingIndicator'`: `BLEND_Additive`, unlit. The emissive and opacity come from the
  texture sample times a pulse built from `Time` (ignores pause) → `Sine` (default period) → `Clamp` / `OneMinus` /
  `Multiply`, and the scalar parameter `MatAlpha` (1.0).
- So the icon is the grayscale texture, added to the scene and pulsing in brightness about once a second.

**Showing a game texture in GFx:**
- GFx's `DefineExternalImage` (tag 1001) is a placeholder that script binds with `GFxMovie.SetExternalTexture(name,
  texture)`. The ECHO video uses it (`SetExternalTexture("texture1", …)`).
- Classic's HUD holds 8 such tags (controller buttons), laid out as: `UI16 id, UI16 format (13), UI16 width,
  UI16 height, UI8 len + export name, UI8 len + file name`.
- The texture is read from the player's own game at runtime, so nothing is redistributed (ADR 0004).

**Position:** in classic the save icon already overlaid an active ECHO call, so overlap with the ECHO panel is
acceptable (user). Our docked layout moves the ECHO panel left of the map (classic (791.45, 37.1) → Enhanced
(610, 13.1) in p1 space, run 25). The icon should move with it by the same offset, so the two keep classic's
relationship. The native icon's exact spot is not yet measured.

## Decisions (user, 2026-10-27)

1. **Reuse the game's graphic and its pulse**, rendered by us in the HUD movie.
2. **Placement:** classic's spot moved by the ECHO panel's shift (left of the map, like the comms). Overlap with an
   active ECHO call is fine, as in classic.
3. **Fallback**, if the texture can't be shown: a "Saving..." text in the game's font.
4. **No option.** Ours replaces the native icon whenever the minimap is docked. Otherwise the native icon stays as is.
5. **Diagnose before fixing:** v0.14.8 logged the timing (done, run 33).

## Plan

**Step 1, spike (one build; both icons visible, so one screenshot measures the native spot):**
- **Movie:**
  - Add a `DefineExternalImage` (`mmSaveTex`, 128 × 128), a shape filled with it, a sprite `mmsave` holding the
    shape, and a "Saving..." text in the copied WillowBody font (hidden).
  - Root `MinimapSave(mode, x, y, scale)`: 0 hides it, 1 shows the image, 2 shows the text. While shown, an
    `onEnterFrame` pulses `_alpha` with a 1 s sine and sets the blend mode to add.
- **Mod:**
  - Find the texture with `find_object("Texture2D", "HUD.Textures.saving_indicator")` and bind it once per HUD
    with `movie.SetExternalTexture("mmSaveTex", tex)`. Log the result and any exception.
  - Each tick: show while `hud.SaveDuration > 0`, at a provisional spot (the ECHO panel's shifted place). Use mode 2
    if binding failed.
- **The native icon is left as is** for this build. F7 reports the binding, the mode and the spot.

**Step 2:**
- From the spike's screenshot, set our spot to the native spot plus the ECHO shift. Choose image or text by
  what rendered.
- Hide the native icon while docked: `hud.SavingMaterialScale = 0`, restored when undocked or when the mod is
  disabled.

## Step 1 results (runs 34–35, PHASE3 §3ba, §3bb)

- **Timing:** ours shows and hides with every save.
- **Binding:** `SetExternalTexture` from Python is safe. It needs the placeholder **exported** under its name (v0.15.1).
- **Transparency:** the texture then draws, but **opaque**. GFx ignores `blendMode`, and none of the game's movies
  uses a blend mode, so the black around the logo can't be made transparent.
- **The native spot:** centred on the docked minimap at stage ≈ (1120, 102), about 64 stage px across.
- **The pulse:** brightness = clamp(1 − sin(2πt), 0, 1) on the engine's real-time clock (Time ignores pause, Sine
  period 1 s), from the material's wiring.

## Step 2 (decided 2026-10-28: vector redraw)

1. **Art:** our own vector Vault logo, a ring plus the Λ mark, white, drawn in the movie. It is transparent and sharp
   at any size. It replaces the external image and `SetExternalTexture`. The "Saving..." text fallback (decision
   3) is dropped: it covered a texture that can't be shown, and vector art has no such failure path.
2. **Size and spot:**
   - 64 stage px, like the native icon.
   - Position: the native spot moved by the ECHO panel's shift, in p1 space: the Enhanced echo position +
     (native − classic echo).
   - For 16:9 that is (610, 13.1) + (903.95 − 791.45, 71.55 − 37.1) = p1 (722.5, 47.55), stage ≈ (938.6, 78.0).
3. **Pulse in sync:** each tick while shown, the mod sets our alpha to 100 × clamp(1 − sin(2π · t), 0, 1), where t
   is `WorldInfo.RealTimeSeconds`. The first run logs the clock against `SaveStartTime` to confirm the match. The
   frame-counted AS pulse is removed.
4. **Hide the native icon:** while ours is in use (map docked and shown), set `pc.myHUD.SavingMaterialScale = 0`.
   Restore the original (0.5) when undocked, hidden, on a new HUD, and on disable.

## Risks

- GFx may draw a `G8` texture without the additive blend (a grey or black square). The `add` blend mode should
  cover it; otherwise the text fallback applies.
- `SetExternalTexture` hasn't been called from Python before. It returns a bool, unlike `Invoke`, whose return
  value crashed the game (hard-won fact 1). Calling it can't be tested offline, so log around it.
- The texture may not be loaded until the first save. If `find_object` misses, retry at the first save; text
  until then.

## Tests

- **AS:** `MinimapSave` modes, placement, pulse and blend, hiding.
- **Mod:** binding (success, missing texture, exception → text), show/hide following `SaveDuration`, and in step 2
  the native scale set to 0 and restored.
- **Builder:** the external image tag's bytes match the classic layout.
