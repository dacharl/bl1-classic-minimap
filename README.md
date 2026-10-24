# Classic Minimap

A minimap for **Borderlands Game of the Year (classic)**, modelled on the one in Borderlands GOTY Enhanced. It sits in the top-right corner of your HUD, tilted like the rest of the HUD, and shows:

- the current zone's map art, scrolling and centred on you (optionally rotating with you);
- landmarks: New-U and fast-travel stations, vendors, Catch-A-Ride, bounty boards and area exits;
- your current objective, tinted **gold** when the mission is ready to hand in;
- **"!"** where a new mission can be picked up and a turn-in icon where a finished one can be handed in;
- a north marker and edge arrows pointing to objectives that are off the map window;
- enemies as red dots, taken from the same radar the compass uses.

The ECHO panel (including the Angel videos), the mission title and the objective checklist move left to make room while the minimap is shown, as they do in Enhanced. The minimap hides itself during the travel tunnel, in menus, in cutscenes and when you're down.

> **Status:** v0.8.0, early. Earlier versions were tested in game (Arid Badlands, Skag Gully, T-Bone Junction); the v0.8 features (zoom, edge arrows, mission givers) haven't been played yet.

## Requirements

- Borderlands GOTY (classic) on Steam, the 32-bit `Borderlands.exe`, not GOTY Enhanced.
- The **willow1 PythonSDK** for Borderlands installed and working (you should see a **MODS** entry in the main menu).
- About 1 MB of disk space, plus free space on the system drive for the game itself. The game can crash at startup if the disk is full.

## Install

You need two files: `GfxHUD_Minimap.upk` (the minimap's HUD artwork and code) and `classic_minimap.sdkmod` (the mod).

1. Close Borderlands.
2. Copy `GfxHUD_Minimap.upk` into
   `…\steamapps\common\Borderlands\WillowGame\CookedPC\Packages\Interface\`
3. Copy `classic_minimap.sdkmod` into
   `…\steamapps\common\Borderlands\sdk_mods\`
4. Start the game, open **MODS** and make sure **Classic Minimap** is enabled.
5. Load a character. If you enabled the mod after a save was already loaded, change area or reload once for the minimap to appear.

Your original game files are not modified; the mod loads its own package next to them.

## Uninstall

Delete the two files you copied. Nothing else needs restoring.

## Options

Open **MODS → Classic Minimap**:

| Option | What it does |
|---|---|
| Position | **Docked** (default): where Enhanced puts it, tilted like the HUD, with ECHO and the mission text moved aside. **Custom**: uses the size and margin sliders below, with no tilt and no HUD changes. |
| Docked size (%) | Size of the docked minimap. |
| Size (%), Right margin, Top margin | Placement when Position is Custom. |
| Zoom (vs Enhanced) | 100% matches Enhanced's minimap; lower shows more of the map. |
| Icon size (%) | Size of landmark, player and enemy icons; 100% matches Enhanced. |
| Rotate with player | Rotate the map so you always face up (north marker moves around the edge). |
| Show enemies | Red dots for enemies the radar tracks. |
| Enemy range (m) | Only show enemies this close; 0 = no limit (like Enhanced). |
| Show mission givers | "!" and turn-in icons at mission givers. |
| Hide compass | Hide the classic compass strip at the bottom. |
| Rebuild now | Re-collect landmarks and objectives (same as F8). |

**Keys:** **F8** rebuilds the minimap's markers. **F7** writes a diagnostic snapshot to the SDK log; please include it with bug reports.

## Troubleshooting

- **No minimap after enabling the mod:** load a save or change area. The minimap attaches to the HUD the game creates on the next level load.
- **Markers look stale:** press **F8**. Markers also refresh on their own when your mission, objectives or area change.
- **Something looks wrong:** press **F7** where it happens, then send
  `…\Borderlands\Binaries\Plugins\unrealsdk.log` (and a screenshot).
- **The game crashes at startup** with "memory could not be written": check free space on your system drive first. A full disk caused exactly this crash during testing.

## Known limitations

- Single player only so far: in co-op, other players aren't shown as markers, and split-screen layouts fall back to the Custom position.
- The classic game has no player-placed map waypoint, so Enhanced's waypoint marker has no equivalent.
- The turn-in and "!" icons and the north marker reuse artwork from the Enhanced edition. Building the package therefore needs both editions installed. Playing needs only classic plus the built files.

## Building from source

The package and mod are built from your own game files: the classic HUD and status-menu movies, plus three small vector icons from the Enhanced HUD.

- **Do not redistribute** the built `GfxHUD_Minimap.upk`: it contains game assets.
- **Project progress, build commands, offline test suites and design notes:** [docs/PROGRESS.md](docs/PROGRESS.md).
- **Contributing as or with an agent:** read [AGENTS.md](AGENTS.md).
