"""Character ids, depths, export names and the window rectangle the minimap movie is laid out with.

Shared by the art (hudart), the root functions (hudscript) and the assembly (swfbuild), so none of them
imports another. The values are measurements from Enhanced's HUD and the in-game runs (PHASE3).
"""
SOURCE_ROOTS = (1132,)            # maps (zone art, landmark/player icon clips, dlcmap frame) in status_menu.gfx
MAPS_SPRITE = 1132
COPIED_FUNCTIONS = ('AddLandmark', 'UpdateLandmark', 'SetMapScale', 'InitDLC', 'SetMarkerColor')
MAP_ID = 1200
EXPORT_NAME = 'bl1mm_map'
ATTACH_DEPTH = 9000
FALLBACK_NAME = 'mmfallback'      # hidden timeline instance, used if attachMovie fails
FALLBACK_DEPTH = 600              # unused by the stock root timeline (1, 635..1295) and never removed
FALLBACK_OFFSCREEN = -20000
LANDMARK_SPRITE = 1066            # status menu landmark icons (frames objective .. questionmark)
# Vector art copied from the Enhanced HUD movie (E_HUD; PLAN_V08.md): shape id there -> id here. No bitmaps.
ENH_SHAPES = {108: 1301, 110: 1303, 179: 1305,     # turnin, newmission ("!"), north "N"
              81: 1307, 82: 1308,                   # minimap box (background + border), window (mask) (PLAN_V09)
              127: 1310}                            # threat marker: red diamond, black outline (E sprite 128)
TURNIN_ART, NEWMISSION_ART, NORTH_ART = 1302, 1304, 1306   # one-frame wrapper sprites (as E 109, 111, 180)
WINDOW_ART = 1309                 # wrapper placing the window shape top-left anchored (see map_sprite)
ENEMY_ART = 1311                  # one-frame wrapper for the threat marker (as E sprite 128), exported bl1mm_enemy
# Original art (PLAN_V13 decisions 5, 12-15), used when the Enhanced HUD movie isn't available. The glyph sprites
# take the ids of Enhanced's turnin / newmission / north shapes: art id -> (glyph, colour, outline text id); the
# coloured text is the next id. GLYPH_FONT copies the HUD's empty WillowBody record (the game's font library).
GLYPHS = {1301: ('?', 0x66FF00, 1312), 1303: ('!', 0xFFCC00, 1314), 1305: ('N', 0xFFFFFF, 1316)}  # E 108/110 colours
GLYPH_FONT = 1318
ORIGINAL_IDS = {1312, 1313, 1314, 1315, 1316, 1317, GLYPH_FONT}
GLYPH_SIZE = 28.0                 # font height (px): capitals about 20 px, like Enhanced's 19-21 px marks
GLYPH_BOX = 32.0
GLYPH_OUTLINE = 1.0
BOX_MARGIN = 5.0                  # a tight frame around the window (E shape 81's bounds include a clear margin, run 21)
BOX_FILL, BOX_LINE, BOX_LINE_WIDTH = (0x0B1624, 0xE6), (0x6A9AC8, 0xF0), 2.0
THREAT_ART_HALF, THREAT_LINE_WIDTH = 7.2, 1.5   # E shape 127 is 14.45 px across
# Enhanced's window (E shape 82, centred) and where its sprite 187 places things
WINDOW_LEFT, WINDOW_TOP, WINDOW_W, WINDOW_H = -103.95, -86.8, 207.95, 173.65
BOX_DEPTH, MASK_DEPTH, MAPS_DEPTH = 3, 4, 6
OBJECTIVE_ART = 1050              # classic objective diamond sprite (placed at 0.55 in the landmark frames)
EDGE_DEPTH = 100                  # north indicator; objective edge icons at EDGE_DEPTH + 1 + i
# Enhanced's edge-indicator path is the rectangle +-110 x +-92 around the window centre: on the box border,
# just outside the 207.95 x 173.65 window (E sprites 182/186 frame positions + their (0, -55) placement)
EDGE_OUT_X, EDGE_OUT_Y = 110.0 - WINDOW_W / 2, 92.0 - WINDOW_H / 2
OBJECTIVE_SCALE = 0.55
# Static half-size of an objective icon at _xscale 100: the diamond's base shape (1047, 45.1 units) at the
# landmark frame's 0.55. The art also has a pulsing ring (shape 1049 scaled 1.0 -> 2.2 over 12 frames), so the
# icon's live _width swings with the animation; the edge handoff must not use it (run 14 "wobble").
OBJECTIVE_HALF = 45.1 * OBJECTIVE_SCALE / 2
SOURCE_CLIPS = ('landmarks', 'players', 'enemy')   # maps' icon templates that AddLandmark duplicates
HUD_CLIPS = ('echo', 'quest', 'check1', 'check2', 'check3', 'check4', 'check5')   # p1 column we shift
HUD_ARGS = ('ex', 'ey', 'qx', 'qy', 'cx', 'cy', 'cdy', 'csx', 'csy')                # MinimapHudShift's placements
# PLAN_V15: our save indicator, a vector Vault logo like the game's HUD.Textures.saving_indicator (a ring and a
# Λ mark). The game texture itself drew opaque in GFx, which has no blend modes (run 35), so the art is our own.
SAVE_LOGO, SAVE_ART = 1330, 1334
SAVE_IDS = {SAVE_LOGO, SAVE_ART}
SAVE_EXPORT = 'bl1mm_save'
SAVE_ART_SIZE = 128                    # art box (px), like the 128 px texture; the mod scales the sprite to its size
SAVE_DEPTH = 9002                      # above the map (ATTACH_DEPTH)
SAVE_RING_RADII = (60.0, 52.0)         # outer / inner (px in the 128 box): the native's ring is thinner than the
                                       # reference logo's 270 / 225 (run 40: inner edge at ~0.87 of the radius)
SAVE_RING_STEPS = 64                   # polygon sides per circle
SAVE_ARC_STEPS = 12                    # segments per arch arc
# The Λ arch, measured from the native icon (run 37, the tunnel screenshot zoomed; ring radius 270 in these units,
# like the reference logo of run 36, whose arch was taller and rounder): each edge runs from a foot on the ring's
# inner edge, through `foot`, up to a tangent of its top circle (centre, radius). The outer top is 153 above the
# centre, the opening's narrowly rounded apex 108. Run 39 (both icons side by side) widened the outer edge slightly:
# top radius 36 (was 30), foot -153 (was -150).
SAVE_REF_RADIUS = 270.0
SAVE_FILLETS = {'outer': 16.0, 'inner': 18.0}   # run 40: the legs meet the ring in rounded fillets (radius, units above)
SAVE_FILLET_STEPS = 8
SAVE_ARCH = {'outer': ((-153.0, 181.0), (0.0, -117.0), 36.0),
             'inner': ((-92.0, 218.0), (0.0, -102.0), 8.0)}
THREAT_DEPTH = 1000
