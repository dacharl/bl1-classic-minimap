# v0.13 plan: players build the HUD movie from their own game files (2026-10-25)

**Planned; grilled in six rounds (decisions 1–23, 2026-10-25). Not implemented.**

The MVP must be installable by other players. Today a player needs `GfxHUD_Minimap.upk`, which we can't
redistribute: it contains game assets. The GitHub release ships only `classic_minimap.sdkmod`, and building the
package needs both editions installed plus this repository's Python tools. This plan makes the `.sdkmod` the only
download. The mod assembles the minimap movie on the player's machine from the player's own installed files, and
ships only our code, our own artwork and hashes.

## Confirmed decisions from grilling, round 1

The user accepted all four recommendations on 2026-10-25:

1. **Option C:** the mod builds the HUD movie in memory from the player's own installed files, caches it
   under `sdk_mods/settings/`, and installs it as a constructed `GFxMovieInfo`. The `.sdkmod` is the only
   download; no builder script, and nothing written into the game folder. See
   [ADR 0004](../adr/0004-build-the-hud-movie-from-the-players-files.md).
2. **Our own art when Enhanced isn't found.** Enhanced is optional: its six shapes are used when its
   `GfxHUD.upk` is found, and our own vector art of the same sizes otherwise.
3. **The build runs synchronously on enable** (normally at the main menu) when the cache is missing or
   stale, with a console line saying it is the first-run build. The cost is a pause of about 1–3 s, once.
4. **An unrecognised build hash warns and continues.** The structural checks still refuse inputs the
   builder can't handle; a hash that matches no known input set only adds an "unrecognised game files"
   status line and log entry.

## Confirmed decisions from grilling, round 2

The user answered on 2026-10-25 (decision 6, the cache key, is still open):

5. **Original art prefers glyphs from the game's own font, else simple shapes of our own.** The stock HUD
   draws its text in `WillowBody`, imported from the game's font library (`gfxfontlib.swf`); the movie
   holds only an empty font record (id 119, 0 glyphs; scratchpad `fontscan.py`). A text field in that
   font ships no font data and draws whatever glyph the player's font library has. So "N" and "!" are
   glyphs, and the turn-in mark is a glyph if Enhanced's is a character. The box, the window and the
   threat diamond are simple shapes of our own at Enhanced's sizes. Nothing is traced from Enhanced.
7. **`GfxHUD_Minimap.upk` is dropped.** There is no package at all, built or shipped. On enable, the mod
   builds the movie (or reads the movie cache) and points the HUD template at a constructed movie object;
   the next HUD the game spawns (loading a save, starting a game) is created from it. An old installed
   package is ignored, and the status line suggests deleting it. `tools/` still builds `HUD_minimap.gfx`
   offline for the real-movie suites, from the same builder code.
8. **Enhanced discovery and rebuilds:** automatic discovery next to classic, then in every library in
   Steam's `libraryfolders.vdf`; a hidden `Enhanced folder` setting in `classic_minimap.json` (the SDK has
   no text-entry option); a "Use Enhanced artwork" switch, on by default; a "Rebuild HUD movie" button that
   clears the movie cache; F7 reports what was found and which art is in use.

## Confirmed decisions from grilling, round 3

The user accepted these on 2026-10-25:

6. **The movie cache key is the SHA-256 of every input file, computed on every enable**, plus the art
   source and the mod version. Size and modification time are not enough: another mod can swap in a
   same-size file.
9. **Everything happens on enable:** find the inputs, read the movie cache or build (first run only), then
   construct the movie object and point the HUD template at it. Loading a save or starting a game only
   spawns the HUD from that object. A later foreign HUD movie is merged from the cached movie's block.
10. **No separate spike.** Constructed movie objects are proven (runs 18–20) and the builder reproduces the
    release movie exactly. v0.13 logs its build time and the input paths it found; the Deck run is the gate.
    This replaces plan step 0.
11. **Expected hashes start with the verified input sets only:** the PC's English files, built with
    Enhanced art and with original art. The Deck's first build confirms them or adds to the list, and other
    languages and versions are added from F7 reports (a mismatch only warns, decision 4).

## Confirmed decisions from grilling, round 4

The user accepted these on 2026-10-25. Glyphs are the fallback for players without Enhanced's assets:

12. **Open objectives keep classic's diamond** (status-menu sprite 1050, tinted by status) for everyone. It
    is the player's own art and sizes the edge handoff (`OBJECTIVE_HALF`); original art replaces only what
    came from Enhanced.
13. **The turn-in mark is a capital "X" in turn-in gold**, on the turn-in landmark frame. The new-mission
    mark is "!" and north is "N", all game font glyphs. The box, window and threat diamond are simple shapes
    of our own.
14. **Glyphs get a dark outline from four black copies offset by 1 px**, not AS2 filters, whose support in
    classic's GFx is unverified.
15. **Glyphs and our own shapes are original art only**: used when Enhanced's `GfxHUD.upk` isn't found or
    "Use Enhanced artwork" is off. Otherwise Enhanced's shapes are used, as today.

## Confirmed decisions from grilling, round 5

The user answered on 2026-10-25:

16. **The builder moves into the mod package** (`swfbuild`, `as2asm`, `swfdeps`, the `upk` reader and
    `upkpatch`'s extract); `tools/` keeps thin wrappers, so offline builds, the real-movie suites and the
    in-game build run one copy of the code. The moved files come under the mod's coverage floors.
17. **Build failures:** a missing, unreadable or refused classic input leaves the minimap idle with a status
    line and no partial movie; an unreadable Enhanced package, or one lacking its shapes, falls back to
    original art with a status line; a cache that can't be written leaves the movie in memory for the
    session, logged.
18. **v0.13.0 is not the public release.** The tuning pass comes next, and the first public release is
    **1.0.0** (user's choice, replacing the recommendation to publish v0.13.0).
19. **README:** one-file install with a first-run build of a few seconds; a "What the mod reads from your
    game" section (classic's HUD and status-menu packages, Enhanced's HUD package if installed; it writes
    only its settings and the movie cache, and ships no game files); an upgrade note to delete an old
    `GfxHUD_Minimap.upk`; troubleshooting for "Rebuild HUD movie" and the Extended UI merge. The release
    workflow's notes drop "a locally built GfxHUD_Minimap.upk".

## Confirmed decisions from grilling, round 6: the path to 1.0.0

The user accepted these on 2026-10-25:

20. **Tuning gets its own plan, PLAN_V14**, grilled after v0.13 has been played. PLAN_V13 stays the
    distribution change and ships as v0.13.0 for the user's own PC and Deck runs.
21. **The 1.0.0 gate has three parts:**
    - v0.13 passes on the PC and the Deck, the original-art build included;
    - PLAN_V14's tuning: the level-change-to-minimap delay (about 10 s), the zoom with no nearby
      objective against Enhanced's `QuickAccessInit`, the threat marker's size, and the merge cost
      re-measured with the movie cache;
    - each never-confirmed check passes or becomes a documented known limitation: the new-mission and
      turn-in marks at givers, the single edge diamond, "Rotate with player", the edge clamp near art
      borders. Co-op stays a known limitation.
22. **Versions:** v0.13.0, then v0.14.x for tuning, all private builds; 1.0.0 is bumped on the release
    commit. The profiler stays 0.1.x and its allowlist gains each core version, 1.0.0 included.
23. **The release workflow gains a `prerelease` input** (`gh release create --prerelease`), and one v0.14.x
    pre-release proves the workflow end to end before 1.0.0, the first full release.

## Research (evidence)

### What the built movie contains, by origin

From `tools/swfbuild.py` `build()`:

| Content | Origin | On a classic-only machine |
|---|---|---|
| The whole stock HUD movie (base: every character, gradient, image reference and root script) | Classic `GfxHUD.FlashMovie.HUD` | Yes, on disk and in memory |
| Zone vector art, landmark/player/enemy icon clips, the DLC map frame (sprite 1132 closure) | Classic status-menu movie (`menus_ingame_redux.upk`, `FlashMovies.status_menu`) | Yes, on disk |
| Five root functions: `AddLandmark`, `UpdateLandmark`, `SetMapScale`, `InitDLC`, `SetMarkerColor` (game AS code) | Classic status-menu movie | Yes |
| Turn-in, "!" and north "N" shapes; box and window shapes; threat diamond (E shapes 108, 110, 179, 81, 82, 127; vector only, no bitmaps) | Enhanced HUD movie | **Only if Enhanced is installed** |
| `bl1mm_map` layout, wrappers, exports, the fallback instance, 12 new root functions, the block manifest | Ours (generated by `swfbuild`) | Ships with the mod |

The block adds no external images (PLAN_V12 research), so the movie's texture references are the stock HUD's.

### The builder can run on the player's machine

Scratchpad `buildprobe.py`, run against the main checkout's extracted inputs on 2026-10-25:
- **Fast:** `swfbuild.build(HUD_classic, status_menu, HUD_enhanced)` takes 1.15–1.18 s in CPython on the desktop.
- **Deterministic:** its output (618,106 bytes, SHA-256 `8b435820…`) matches the v0.12.0 release's `HUD_minimap.gfx` (`8b435820…38be`, PHASE3 §3ai). Identical game files give identical bytes, so we can publish the **expected hash** of a correct build (a hash, not game data) and check a player's build against it.
- **Same stock HUD:** the stock HUD movie extracted from `GfxHUD.upk` on disk is byte-identical to the cooked copy inside `WillowGame.u` (found at offset 7,940,059 in the decompressed `C_WillowGame.u`). Reading the disk file is equivalent to what the game loads (PROGRESS fact 1).
- **Pure Python:** `swfbuild`, `as2asm`, `swfdeps`, `swfmerge`, `upk` and `upkpatch`'s extract use only the standard library (`struct`, `sys`, `os`, `re`), about 83 KB of source in total.
- **Uncompressed inputs:** the build commands extract all three movies with `upkpatch extract` directly, so the inputs need no LZO step:
  - classic `GfxHUD.upk` (591,860 bytes) and `menus_ingame_redux.upk` (1,054,497 bytes);
  - Enhanced's `WillowGame/CookedPC/Packages/Interface/GfxHUD.upk` (1,532,694 bytes).

### Installing a movie without a package file

PLAN_V12's runtime merge already installs a movie with no package file:
- it constructs a `GFxMovieInfo` with `template_obj=` the current movie and `KEEP_ALIVE`;
- it sets its `RawData`;
- it points `hud_instance.MovieInfo` at it.

The PC spike and runs 19–20 confirmed GFx loads such an object on the PC and the Deck. `template_obj` copies the data properties, including texture references. Writing 616–840 KB of `RawData` took about 0.2 s.

### Enhanced availability (from memory, not verified this session)

Steam gave Borderlands GOTY Enhanced free to owners of the original GOTY in 2019, so many classic players own it, but it is a separate ~13 GB install. On the Deck, the two games may sit in different Steam libraries (internal storage and SD card). Steam's `libraryfolders.vdf` lists every library (`C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf` on this PC).

## Options

| | Option | Player experience | Cost and risk |
|---|---|---|---|
| A | Offline builder script players run (Python + this repository) | Poor: needs Python, a command line and both installs; awkward on the Deck | Little new code |
| B | The mod builds a `.upk` into `CookedPC` once, then `load_package` | One file to install; first run builds | Port `upkpatch`'s repack into the mod; writes into the game folder |
| **C** | **The mod builds the movie in memory from the player's files, caches it under `sdk_mods/settings/`, installs it as a constructed `GFxMovieInfo`** | **One file to install; first run builds (about 1–3 s), later sessions read the cache** | **Reuses v0.12's install path; no game-folder writes; a cache to invalidate** |
| D | Ship only our own artwork and code, no copied art at all | One file | Zone maps and icons must come from the status menu anyway, so this collapses into C |

## Recommendation: option C

- **Inputs:**
  - classic `GfxHUD.upk` and `menus_ingame_redux.upk`, read from the game folder;
  - Enhanced's `GfxHUD.upk` if it can be found: next to classic, or through `libraryfolders.vdf`, or a path option.
- **Build:** run the shipped builder (`swfbuild` and friends, moved into `sdk_mods/classic_minimap/`).
- **Without Enhanced:** substitute **our own vector art** for its six shapes (box, window, turn-in, "!", "N", threat diamond), drawn to the same sizes so all layout constants hold.
- **Cache and verify:** write the built movie to `sdk_mods/settings/classic_minimap_hud.gfx`, with a key made from the input hashes, the art source and the mod version. Compare the build with the published expected hash for each known input set, and log a mismatch as "unrecognised game files" rather than refusing.
- **Install:**
  - Stock template: construct the `GFxMovieInfo` from the cached bytes with `template_obj=` the stock movie.
  - Foreign HUD (PLAN_V12): merge the block sliced from the cached movie. Its reads now come from the cache instead of `RawData`, which also removes a 0.7 s read from the merge, a PLAN_V12 tuning item.
- **Release:** the `.sdkmod` from GitHub is the only download. `GfxHUD_Minimap.upk` is no longer installed, and an old one is ignored, with a note to delete it.

## Plan

0. ~~Spike~~ dropped (decision 10): the first v0.13 run logs the in-game build time and the input paths.
1. **Move the builder into the mod package** (`swfbuild`, `as2asm`, `swfdeps`, the `upk` reader and `upkpatch`'s extract), keeping `tools/` entry points as thin wrappers so offline builds and both real-movie suites run the same code.
2. **Original art (decisions 5, 12–15):** game font glyphs in `WillowBody` ("N", "!", gold "X") with four offset black copies as an outline, and simple shapes of our own for the box, window and threat diamond, behind the same character ids and sizes; `swfbuild` selects Enhanced or original art.
3. **Mod:** input discovery, build on enable when the cache is missing or stale, the cache, expected-hash check, install via constructed object, status lines (PLAN_V12 decision 5's three channels).
4. **Release and docs (decisions 11, 19, 23):** the README changes of decision 19; the release workflow's notes without the package, plus its `prerelease` input; expected hashes in the source. No public release from v0.13 (decision 18).
5. **Tests (red first):** builder parity on the CI fixture; the original-art build passes `test_minimap_as.py`; discovery (sibling, `libraryfolders.vdf`, option, none); cache hit, miss and invalidation; expected-hash match and mismatch messages; install via constructed object; a foreign HUD merges from the cache. Local-only: the in-mod build equals `8b435820…` from the real files.
6. **In game:** PC and Deck, each with and without Enhanced installed (or with discovery forced off), plus Extended UI on the Deck.

## Unknowns

- How long the build takes inside the game's Python, especially on the Deck (desktop CPython: 1.2 s).
- How classic's Python sees paths under Proton: the game folder and `libraryfolders.vdf` through Wine's `Z:` drive.
- Whether a player's game files ever differ from ours (other languages or regions, patches, or other mods replacing `menus_ingame_redux.upk` or `GfxHUD.upk` on disk). The expected-hash check makes this visible; the structural checks already refuse what the builder can't handle.
- Distribution terms: this is the usual patcher approach (ship code, assemble from the player's own files). It is not legal advice.
