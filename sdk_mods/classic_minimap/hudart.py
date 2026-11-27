"""The minimap movie's art: Enhanced's vector shapes copied under our ids, or original art (game font
glyphs, our own box, window and threat diamond, the save indicator's Vault logo) when the Enhanced HUD
movie is not installed (PLAN_V08, PLAN_V13, PLAN_V15).
"""
import math

try:        # inside the mod package: the in-game build (PLAN_V13)
    from .hudlayout import (BOX_FILL, BOX_LINE, BOX_LINE_WIDTH, BOX_MARGIN, ENEMY_ART, ENH_SHAPES, GLYPHS, GLYPH_BOX,
                            GLYPH_FONT, GLYPH_OUTLINE, GLYPH_SIZE, NEWMISSION_ART, NORTH_ART, SAVE_ARCH,
                            SAVE_ARC_STEPS, SAVE_ART, SAVE_FILLETS, SAVE_FILLET_STEPS, SAVE_LOGO, SAVE_REF_RADIUS,
                            SAVE_RING_RADII, SAVE_RING_STEPS, THREAT_ART_HALF, THREAT_LINE_WIDTH, TURNIN_ART,
                            WINDOW_ART, WINDOW_H, WINDOW_LEFT, WINDOW_TOP, WINDOW_W)
    from .swfdeps import SHAPES as SHAPE_CODES, shape_bitmaps
    from .swfrecords import (BitWriter, DEFINE_EDIT_TEXT, DEFINE_FONT3, DEFINE_SHAPE3, DEFINE_SPRITE, END_CODE,
                             FRAME_LABEL, REMOVE_OBJECT2, SHOW_FRAME, header, one_frame_sprite, place, read_tags,
                             rect_bytes, rgba, skip_rect, sprite, tag, translate_matrix, twips, u16, words)
except ImportError:     # a plain module: tools/ wrappers and the offline suites put this folder on sys.path
    from hudlayout import (BOX_FILL, BOX_LINE, BOX_LINE_WIDTH, BOX_MARGIN, ENEMY_ART, ENH_SHAPES, GLYPHS, GLYPH_BOX,
                           GLYPH_FONT, GLYPH_OUTLINE, GLYPH_SIZE, NEWMISSION_ART, NORTH_ART, SAVE_ARCH,
                           SAVE_ARC_STEPS, SAVE_ART, SAVE_FILLETS, SAVE_FILLET_STEPS, SAVE_LOGO, SAVE_REF_RADIUS,
                           SAVE_RING_RADII, SAVE_RING_STEPS, THREAT_ART_HALF, THREAT_LINE_WIDTH, TURNIN_ART,
                           WINDOW_ART, WINDOW_H, WINDOW_LEFT, WINDOW_TOP, WINDOW_W)
    from swfdeps import SHAPES as SHAPE_CODES, shape_bitmaps
    from swfrecords import (BitWriter, DEFINE_EDIT_TEXT, DEFINE_FONT3, DEFINE_SHAPE3, DEFINE_SPRITE, END_CODE,
                            FRAME_LABEL, REMOVE_OBJECT2, SHOW_FRAME, header, one_frame_sprite, place, read_tags,
                            rect_bytes, rgba, skip_rect, sprite, tag, translate_matrix, twips, u16, words)


def wrapper_sprite(sid, child):
    """One-frame sprite placing `child` at depth 1, identity matrix (like E_HUD 109, 111, 180)."""
    return one_frame_sprite(sid, place(1, child))


def enhanced_art(enhanced):
    """Copy the Enhanced turnin / newmission / north vector shapes under ENH_SHAPES ids, plus wrappers."""
    found = {}

    def scan(tags):
        for code, body in tags:
            if code in SHAPE_CODES and len(body) >= 2 and u16(body, 0) in ENH_SHAPES:
                found.setdefault(u16(body, 0), (code, body))
            if code == DEFINE_SPRITE:
                scan(read_tags(body, 4, len(body)))
    scan(read_tags(enhanced, skip_rect(enhanced, 8) + 4, len(enhanced)))
    missing = sorted(set(ENH_SHAPES) - set(found))
    if missing:
        raise SystemExit('Enhanced HUD movie lacks shapes %s' % missing)
    out = []
    for old, new in sorted(ENH_SHAPES.items()):
        code, body = found[old]
        if shape_bitmaps(code, body):
            raise SystemExit('Enhanced shape %d fills with bitmaps; refusing to copy' % old)
        out.append(tag(code, words(new) + body[2:]))
    return out + art_wrappers()


def art_wrappers():
    """The one-frame wrappers around the art ids, whichever art fills them."""
    out = [wrapper_sprite(TURNIN_ART, ENH_SHAPES[108]), wrapper_sprite(NEWMISSION_ART, ENH_SHAPES[110]),
           wrapper_sprite(NORTH_ART, ENH_SHAPES[179]), wrapper_sprite(ENEMY_ART, ENH_SHAPES[127])]
    # the window shape is centred; its wrapper shifts it so the sprite's origin is the window's top-left
    out.append(one_frame_sprite(WINDOW_ART, place(1, ENH_SHAPES[82], translate_matrix(-WINDOW_LEFT, -WINDOW_TOP))))
    return out


def polygon_shape(sid, points, fill, line=None):
    """DefineShape3: one closed polygon (clockwise on screen, so the fill is FillStyle1), optional outline.

    fill and line colours are RGBA bytes; line is (width in px, RGBA)."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad = line[0] / 2 if line else 0
    body = words(sid) + rect_bytes(min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)
    body += bytes([1, 0x00]) + fill
    body += bytes([1]) + words(twips(line[0])) + line[1] if line else bytes([0])
    w = BitWriter()
    w.u(1, 4)                                       # NumFillBits
    w.u(1 if line else 0, 4)                        # NumLineBits
    pts = [(twips(x), twips(y)) for x, y in points]
    w.style_change(pts[0], fill1=1, line=1 if line else None)
    w.closed_path(pts)
    w.end()
    return tag(DEFINE_SHAPE3, body + w.data())


def font_record(hud, name='WillowBody'):
    """The HUD's own DefineFont3 record for `name`: empty, so text in it draws the game font library's glyphs."""
    for code, body in read_tags(hud, skip_rect(hud, 8) + 4, len(hud)):
        if code == 75 and body[5:5 + body[4]].rstrip(b'\0') == name.encode():
            return body
    raise SystemExit('HUD movie has no %s font' % name)


def glyph_text(tid, glyph, colour):
    """DefineEditText: one centred, read-only glyph in GLYPH_FONT. The box centres the glyph's capital height."""
    half, top = GLYPH_BOX / 2, -0.45 * GLYPH_SIZE
    return tag(DEFINE_EDIT_TEXT, words(tid) + rect_bytes(-half, half, top, top + 1.25 * GLYPH_SIZE)
               + bytes([0x80 | 0x08 | 0x04 | 0x01, 0x20 | 0x10])    # HasText ReadOnly HasTextColor HasFont; HasLayout NoSelect
               + words(GLYPH_FONT, twips(GLYPH_SIZE)) + rgba(colour)
               + bytes([2]) + words(0, 0, 0, 0)                      # centred, no margins, indent or leading
               + b'\0' + glyph.encode('latin-1') + b'\0')


def glyph_sprite(sid, tid):
    """The glyph over four black copies offset by GLYPH_OUTLINE px: an outline without AS2 filters (decision 14)."""
    places = [place(depth, tid, translate_matrix(dx, dy))
              for depth, (dx, dy) in enumerate(((-GLYPH_OUTLINE, 0), (GLYPH_OUTLINE, 0), (0, -GLYPH_OUTLINE),
                                                (0, GLYPH_OUTLINE)), 1)]
    places.append(place(5, tid + 1))
    return one_frame_sprite(sid, *places)


def original_art(hud):
    """Original art (PLAN_V13 decisions 5, 12-15) under the ids enhanced_art uses, when the Enhanced HUD movie
    isn't available: game font glyphs for the turn-in, new-mission and north marks; our own box, window and
    threat diamond, at the sizes of Enhanced's shapes so every layout constant holds."""
    font = font_record(hud)
    out = [tag(DEFINE_FONT3, words(GLYPH_FONT) + font[2:])]
    for sid, (glyph, colour, tid) in sorted(GLYPHS.items()):
        out += [glyph_text(tid, glyph, 0x000000), glyph_text(tid + 1, glyph, colour), glyph_sprite(sid, tid)]
    x0, x1, y0, y1 = WINDOW_LEFT, WINDOW_LEFT + WINDOW_W, WINDOW_TOP, WINDOW_TOP + WINDOW_H
    m = BOX_MARGIN
    out.append(polygon_shape(ENH_SHAPES[81], [(x0 - m, y0 - m), (x1 + m, y0 - m), (x1 + m, y1 + m), (x0 - m, y1 + m)],
                             rgba(*BOX_FILL), (BOX_LINE_WIDTH, rgba(*BOX_LINE))))
    out.append(polygon_shape(ENH_SHAPES[82], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], rgba(0x223853)))
    h = THREAT_ART_HALF
    out.append(polygon_shape(ENH_SHAPES[127], [(0, -h), (h, 0), (0, h), (-h, 0)], rgba(0xFF0000),
                             (THREAT_LINE_WIDTH, rgba(0x000000))))
    return out + art_wrappers()


def paths_shape(sid, paths, fill, r):
    """DefineShape3 of closed straight-edged paths (px points) in one solid fill, bounded by radius r. Each path is
    (points, fill0, fill1): the side its edges fill, so one shape can have holes and nothing is drawn twice."""
    body = words(sid) + rect_bytes(-r, r, -r, r) + bytes([1, 0x00]) + fill + bytes([0])
    w = BitWriter()
    w.u(1, 4); w.u(0, 4)                                            # NumFillBits, NumLineBits
    for points, fill0, fill1 in paths:
        pts = [(twips(x), twips(y)) for x, y in points]
        w.style_change(pts[0], fill0=fill0, fill1=fill1)
        w.closed_path(pts)
    w.end()
    return tag(DEFINE_SHAPE3, body + w.data())


def logo_paths():
    """The Vault logo as one shape (run 37: the ring and a separate arch overlapped, and the alpha doubled there):
    the outer circle, filled inside, and two holes cut from it, both clockwise on screen like the circle: the hole
    around the arch (along the ring's inner edge over the top, back over the arch) and the arch's opening (up the
    left leg, over the apex, down the right leg, back along the ring's inner edge at the bottom). Each leg meets the
    ring in a fillet (SAVE_FILLETS, run 40), so both outlines are smooth."""
    r_out, r_in = SAVE_RING_RADII
    scale = r_out / SAVE_REF_RADIUS
    inner = r_in / scale                                     # the ring's inner edge, in SAVE_ARCH units

    def arc(centre, r, a0, a1, steps=None):                 # from a0 to a1, both ends included
        steps = steps or max(2, round(abs(a1 - a0) / (2 * math.pi) * SAVE_RING_STEPS))
        return [(centre[0] + r * math.cos(a0 + (a1 - a0) * k / steps),
                 centre[1] + r * math.sin(a0 + (a1 - a0) * k / steps)) for k in range(steps + 1)]

    def angle(p, centre=(0.0, 0.0)):
        return math.atan2(p[1] - centre[1], p[0] - centre[0])

    def mirror(points):
        return [(-x, y) for x, y in points]

    def join(*parts):                                       # concatenated, without the shared end points
        out = []
        for part in parts:
            out += [p for p in part if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6]
        return out

    def edge(name, side):
        """The left leg: its top (tangent to the top circle, at angle a) and the fillet from the leg into the ring's
        inner edge, on the hole's side (-1: left of the leg, +1: right), as points from the leg to the ring."""
        foot, c, r = SAVE_ARCH[name]
        a = angle(foot, c) + math.acos(r / math.hypot(foot[0] - c[0], foot[1] - c[1]))
        top = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
        length = math.hypot(foot[0] - top[0], foot[1] - top[1])
        d = ((foot[0] - top[0]) / length, (foot[1] - top[1]) / length)
        n = (-d[1], d[0]) if -d[1] * side > 0 else (d[1], -d[0])
        rf = SAVE_FILLETS[name]
        p0 = (top[0] + n[0] * rf, top[1] + n[1] * rf)       # the fillet's centre runs along the leg, rf off it,
        b = p0[0] * d[0] + p0[1] * d[1]                     # and lies rf inside the ring's inner edge
        t = -b + math.sqrt(b * b - (p0[0] ** 2 + p0[1] ** 2 - (inner - rf) ** 2))
        fc = (p0[0] + t * d[0], p0[1] + t * d[1])
        on_leg, on_ring = (top[0] + t * d[0], top[1] + t * d[1]), angle(fc)
        f0, f1 = angle(on_leg, fc), on_ring
        f1 = f0 + (f1 - f0 + math.pi) % (2 * math.pi) - math.pi                      # the short way round
        return a, c, r, arc(fc, rf, f0, f1, SAVE_FILLET_STEPS)

    a_l, oc, o_r, fillet = edge('outer', -1)                 # the hole around the arch is left of the left leg
    q = angle(fillet[-1])
    around = join(arc((0.0, 0.0), inner, q, math.pi - q + 2 * math.pi),                # over the top, to the right
                  mirror(fillet)[::-1],                                                # into the right leg
                  arc(oc, o_r, math.pi - a_l, a_l - 2 * math.pi, SAVE_ARC_STEPS),      # back over the arch's top
                  fillet[:-1])                                                         # down the left leg
    b_l, ic, i_r, fillet = edge('inner', 1)                  # the opening is right of the left leg
    q = angle(fillet[-1])
    opening = join(arc(ic, i_r, b_l, math.pi - b_l + 2 * math.pi, SAVE_ARC_STEPS),     # over the apex
                   mirror(fillet),                                                     # down the right leg
                   arc((0.0, 0.0), inner, math.pi - q, q),                             # along the bottom
                   fillet[::-1])                                                       # up the left leg
    ring = arc((0.0, 0.0), SAVE_REF_RADIUS, 0.0, 2 * math.pi, SAVE_RING_STEPS)[:-1]

    def px(points):
        return [(x * scale, y * scale) for x, y in points]
    return [(px(ring), 0, 1), (px(around), 1, 0), (px(opening), 1, 0)]


def save_art():
    """PLAN_V15: the save indicator, exported as SAVE_EXPORT: the game's Vault logo (a ring and the Λ arch) redrawn
    white in a SAVE_ART_SIZE box, measured from the native icon (run 37). The mod sets its alpha (the pulse)."""
    return [paths_shape(SAVE_LOGO, logo_paths(), rgba(0xFFFFFF), SAVE_RING_RADII[0]),
            one_frame_sprite(SAVE_ART, place(1, SAVE_LOGO))]


def landmark_frames(raw):
    """The landmark sprite plus Enhanced's frames 12/13 (turnin, newmission) as frames 11/12. Frame 10
    (questionmark) placed at depth 2 and removed depth 1, so 11 removes 2 and 12 removes 1."""
    _, ln, p = header(raw, 0)
    body = raw[p:p + ln]
    sid, frames = u16(body, 0), u16(body, 2)
    tags = [tag(c, b) for c, b in read_tags(body, 4, len(body)) if c != END_CODE]
    extra = [tag(FRAME_LABEL, b'turnin\0'), tag(REMOVE_OBJECT2, words(2)), place(1, TURNIN_ART), SHOW_FRAME,
             tag(FRAME_LABEL, b'newmission\0'), tag(REMOVE_OBJECT2, words(1)), place(1, NEWMISSION_ART), SHOW_FRAME]
    return sprite(sid, frames + 2, *tags, *extra)
