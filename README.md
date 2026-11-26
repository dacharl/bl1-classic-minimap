# Classic Minimap

A minimap for **Borderlands Game of the Year (classic)**, modelled on the one in Borderlands GOTY Enhanced. It sits in the top-right corner of your HUD, tilted like the rest of the HUD, and shows:

- the current zone's map art, scrolling and centered on you (optionally rotating with you);
- landmarks: New-U and fast-travel stations, vendors, Catch-A-Ride, bounty boards and area exits;
- your current objective: a diamond, or, like Enhanced, the turn-in mark when the mission is ready to hand in;
- **"!"** where a new mission can be picked up and a turn-in mark where a finished one can be handed in (one mark per spot);
- a north marker and edge arrows pointing to objectives that are off the map window;
- enemies as red dots, taken from the same radar the compass uses.

The ECHO panel (including the Angel videos), the mission title and the objective checklist move left to make room while the minimap is shown, as they do in Enhanced. The minimap hides itself during the travel tunnel, in menus, in cutscenes and when you're down.

> **Status:** v0.16.5 is a public test build: one-file install, with the HUD movie built from your own game files. It has been played on the PC (with and without Enhanced's art, and with Extended UI) and, up to v0.14.7, on the Steam Deck. The first stable release will be 1.0.0.

## Requirements

- Borderlands GOTY (classic) on Steam, the 32-bit `Borderlands.exe`.
- The **willow1 PythonSDK** for Borderlands installed and working (you should see a **MODS** entry in the main menu).
- Optional: **Borderlands GOTY Enhanced** installed. If it is, the minimap uses Enhanced's box, marks and enemy diamond; if not, it uses its own art (see [Art](#art)).
- About 1 MB of disk space, plus free space on the system drive for the game itself. The game can crash at startup if the disk is full.

## Install

1. Close Borderlands.
2. Copy `classic_minimap.sdkmod` into
   `…\steamapps\common\Borderlands\sdk_mods\`
3. Start the game, open **MODS** and make sure **Classic Minimap** is enabled. The first time, the mod builds its HUD movie from your game files, which takes a few seconds; later sessions reuse it.
4. Load a character. If you enabled the mod after a save was already loaded, change area or reload once for the minimap to appear.

That's the whole install. **Upgrading from v0.12 or earlier:** delete `GfxHUD_Minimap.upk` from `…\Borderlands\WillowGame\CookedPC\Packages\Interface\`. It is no longer used.

## What the mod reads from your game

To build its HUD movie, the mod reads:

- classic's `GfxHUD.upk` and `menus_ingame_redux.upk` (the HUD and the status-menu map);
- GOTY Enhanced's `GfxHUD.upk`, if Enhanced is installed (its minimap artwork).

It looks for Enhanced next to classic, then in every Steam library. It writes only its settings and the built movie (`classic_minimap_hud.gfx`, the movie cache) under `…\Borderlands\sdk_mods\settings\`. It never changes your game files, and the mod download contains no game files.

## Uninstall

Delete `classic_minimap.sdkmod`. Optionally delete `classic_minimap*` from `sdk_mods\settings\`. Nothing else needs restoring.

## Options

Open **MODS → Classic Minimap**:

**Map**

| Option | What it does |
|---|---|
| Docked size (%) | Size of the docked minimap. |
| Zoom | 100% uses Enhanced's objective-fit zoom; lower shows more of the map. Applies in either zoom mode. |
| Zoom mode | **Enhanced** (default): the zoom is fitted to you and your objectives once per level load, as in Enhanced; switching missions keeps it. **Objective**: also refits when your tracked mission or its status changes. **F8** refits in both modes. |
| Icon size (%) | Size of landmark, player and enemy icons; 100% matches Enhanced. |
| Rotate with player | Rotate the map so you always face up (north marker moves around the edge); icons stay upright, as in Enhanced. |

**Markers**

| Option | What it does |
|---|---|
| Show enemies | Red dots for enemies the radar tracks. |
| Enemy range (m) | Only show enemies this close; 0 = no limit (like Enhanced). |
| Show mission givers | "!" and turn-in marks at mission givers. |
| Tint objective diamonds | Off (default, like Enhanced): a mission ready to hand in shows the turn-in mark, and one not started shows "!", in place of the objective diamond. On: the diamond stays and turns gold (ready to hand in) or green (not started), as in earlier versions. |

**HUD**

| Option | What it does |
|---|---|
| Hide compass | Hide the classic compass strip at the bottom. |
| Angel position | **Centered** (default): Angel's ECHO video appears top center, clear of the minimap, like GOTY Enhanced. **Classic**: top right, partly behind the minimap. Takes effect from her next call. |

**Custom position** (sub-menu)

| Option | What it does |
|---|---|
| Position | **Docked** (default): where Enhanced puts it, tilted like the HUD, with ECHO and the mission text moved aside. **Custom**: uses the size and margin sliders below, with no tilt and no HUD changes. |
| Size (%), Right margin, Top margin | Placement when Position is Custom. |

**Advanced** (sub-menu)

| Option | What it does |
|---|---|
| Use Enhanced artwork | On (default): Enhanced's artwork when Enhanced is installed. Off: the mod's own art. Takes effect from the next level load. |
| Refresh map markers | Re-collect landmarks and objectives and refit the zoom (same as F8). |
| Rebuild HUD movie from game files | Build the minimap's HUD movie from your game files again, for example after installing Enhanced. Takes effect from the next level load. |

While the map is docked, the game's autosave icon is replaced by a matching one beside the map, so it doesn't cover the minimap.

**Keys:** **F8** refreshes the map markers. **F7** writes a diagnostic snapshot to the SDK log and confirms it in the in-game console; it includes which art is in use and which game files the movie was built from. Please include the snapshot with bug reports.

**Enhanced installed somewhere unusual?** Set `"Enhanced folder"` in `…\sdk_mods\settings\classic_minimap.json` to Enhanced's game folder, then press **Rebuild HUD movie from game files**.

## Art

With Enhanced installed, the minimap uses Enhanced's own box, window, turn-in and "!" marks, north "N" and enemy diamond. Without it, the mod draws its own:

- "N", a gold "!" and a green "?" (turn-in), the same colors as Enhanced's marks, drawn in the game's own HUD font with a dark outline;
- a dark frame around the map window, and a red enemy diamond.

The zone maps, landmark icons and objective diamond always come from classic itself.

## Troubleshooting

- **No minimap after enabling the mod:** load a save or change area. The minimap attaches to the HUD the game creates on the next level load.
- **"Can't build the minimap's HUD movie":** the mod couldn't read classic's `GfxHUD.upk` or `menus_ingame_redux.upk`. The message names the file. Check that the game is installed completely (Steam: **Verify integrity of game files**), and that no other mod replaced those files.
- **Markers look stale:** press **F8**. Markers also refresh on their own when your mission, objectives or area change.
- **Something looks wrong:** press **F7** where it happens, then send
  `…\Borderlands\Binaries\Plugins\unrealsdk.log` (and a screenshot).
- **Extended UI (Extended Item Cards) installed:** both mods replace the HUD movie, so the minimap merges itself into Extended UI's movie at startup, adding a pause of a few seconds once per session. The MODS description and the console say "Merged into …". The minimap appears from the next level load. If a HUD mod's movie can't be merged safely, it keeps the HUD, and the minimap stays idle and says why.
- **The game crashes at startup** with "memory could not be written": check free space on your system drive first. A full disk caused exactly this crash during testing.

## Known limitations

- Single player only so far: in co-op, other players aren't shown as markers, and split-screen layouts fall back to the Custom position.
- The classic game has no player-placed map waypoint, so Enhanced's waypoint marker has no equivalent.

## Optional performance profiler (for investigation only)

`classic_minimap_profiler.sdkmod` is a separate add-on for measuring how long the minimap's work takes. You don't need it to play, and the normal release doesn't include it; the minimap itself contains no timing code.

- Install it next to `classic_minimap.sdkmod`, enable both, then open **MODS → Classic Minimap Profiler**.
- **Capture length** (30/60/120/300 s), **Start performance capture**, **Dump performance report** (stop now and save; also writes the report to the SDK log), **Reset performance statistics** (discard without saving).
- A capture measures only while it runs and saves when it stops, to `…\Borderlands\sdk_mods\settings\classic_minimap_profiler\reports\` (the previous eight reports are kept under `archive\`).
- Its timings show which minimap operations take time; they don't measure frame rate. Use PresentMon (Windows) or MangoHud (Steam Deck) for frames.
- It supports only the Classic Minimap version it was built for, and refuses others.

## Building from source

The mod ships its builder (`sdk_mods/classic_minimap/swfbuild.py` and friends); `tools/` has wrappers for offline builds and the test suites. Offline builds use movies extracted from your own installs. Never commit or redistribute a built movie or package: they contain game assets.

- **Project progress, build commands, offline test suites and design notes:** [docs/PROGRESS.md](docs/PROGRESS.md).
- **Contributing as or with an agent:** read [AGENTS.md](AGENTS.md).

## Creating a GitHub release

The [Release SDK mod workflow](.github/workflows/release.yml) runs on demand. Once it is on the GitHub repository's default branch (`main`), open **Actions → Release SDK mod → Run workflow** on `main` and tick **prerelease** for a pre-release.

Before running CI it checks that `__version__` and `pyproject.toml` agree, that the tag `v<version>` doesn't exist yet, and that the release has notes: write them in `docs/release_notes/<version>.md` (commit it first), or paste them into the run's **notes** input if that file is missing. Without either, the run fails at once. After CI passes it builds and verifies `classic_minimap.sdkmod`, creates the tag `v<version>` at the tested commit and publishes the release with the notes, the install text, `classic_minimap.sdkmod` and `classic_minimap-changes.md` (the commits since the previous release, grouped by type). Bump both version fields before the next release: an existing tag causes the workflow to fail rather than replace a release. It uses the repository's built-in token; no personal access token is needed.

The release is the whole install: players build the HUD movie from their own game files. Run the game-dependent checks locally first: `tools/release.py` builds both art variants, runs both real-movie suites on each, and with `--game` checks the mod's in-game build against a game folder. The hosted workflow checks source syntax and archive integrity without game assets.

## License

[MIT](LICENSE). The mod contains no game files.

## Continuous integration

Pushes and merges to `main`, pull requests targeting `main`, and merge-queue events run the two blocking checks: lint (including workflow/repository checks) and source-only movie/mod/archive/profiler unit tests with per-file line and branch coverage floors. Mutation testing is on demand only (**Actions → Mutation testing → Run workflow**, or locally), because a full run takes over an hour. See [docs/CI.md](docs/CI.md) for thresholds, scope, reports and local commands. Real game-movie and in-game verification remain local release checks.
