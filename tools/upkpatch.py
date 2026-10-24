"""Replace the Scaleform movie inside an uncompressed BL1 (UE3 v584/v594) package such as GfxHUD.upk.

  extract  <in.upk> <movie export path> <out.gfx>
  replace  <in.upk> <movie export path> <in.gfx> <out.upk> [--new-guid]
  selftest <in.upk> [movie export path]      round-trip + size-change checks, writes nothing

The movie export path is the full object path, e.g. "FlashMovie.HUD" (GFxMovieInfo). Its RawData
ArrayProperty<byte> holds the GFx file. Replacing it changes the export's size, so every later export
moves: the export table's SerialOffset values are rewritten, and so are the absolute file offsets that
cooked bulk data (Texture2D mips, source art) stores for itself.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upk import Pkg  # noqa: E402

TAG = 0x9E2A83C1


def find_export(pk, path):
    for i, e in enumerate(pk.exports, 1):
        if pk.path(i) == path:
            return i, e
    raise SystemExit('export %r not found' % path)


def walk_tags(pk, b, p):
    """Yield (name, type, tag_pos, data_pos, size) for a serialized property list until None."""
    while True:
        name = pk.fname(*struct.unpack_from('<ii', b, p))
        if name == 'None':
            return
        typ = pk.fname(*struct.unpack_from('<ii', b, p + 8))
        size = struct.unpack_from('<i', b, p + 16)[0]
        q = p + 24
        if typ == 'StructProperty':
            q += 8
        elif typ == 'BoolProperty':
            q += 4  # v584/v594 store the bool value as an int32 after a size-0 tag
        yield name, typ, p, q, size
        p = q + size


def raw_data_span(pk, export):
    """(tag_pos, data_pos, size) of the RawData ArrayProperty, relative to the export start."""
    b = pk.d[export['off']:export['off'] + export['size']]
    for name, typ, tp, dp, size in walk_tags(pk, b, 4):  # skip NetIndex
        if name == 'RawData' and typ == 'ArrayProperty':
            return tp, dp, size
    raise SystemExit('RawData not found in export')


def extract(pk, path):
    _, e = find_export(pk, path)
    tp, dp, size = raw_data_span(pk, e)
    base = e['off'] + dp
    count = struct.unpack_from('<i', pk.d, base)[0]
    assert count == size - 4, (count, size)
    return pk.d[base + 4:base + 4 + count]


def bulk_offset_fields(data, old_off):
    """Positions in an export's data holding an absolute offset that points just past itself.

    Cooked FUntypedBulkData is (flags, element count, size on disk, offset in file) followed by the
    payload, and offset-in-file is the absolute position of that payload: old_off + pos + 4.
    """
    out = []
    for p in range(12, len(data) - 3):
        if struct.unpack_from('<i', data, p)[0] == old_off + p + 4:
            disk = struct.unpack_from('<i', data, p - 4)[0]
            if 0 <= disk <= len(data) - (p + 4):
                out.append(p)
    return out


def replace(pk, path, gfx):
    idx, target = find_export(pk, path)
    tp, dp, size = raw_data_span(pk, target)
    old = pk.d[target['off']:target['off'] + target['size']]
    new_target = bytearray(old[:dp])
    struct.pack_into('<i', new_target, tp + 16, 4 + len(gfx))  # tag size = count + bytes
    new_target += struct.pack('<i', len(gfx)) + gfx + old[dp + size:]

    # Rebuild the data area in file order. Header, name/import/export tables all precede the first
    # export's data, so only the export table entries and the moved exports need fixing.
    order = sorted(range(len(pk.exports)), key=lambda i: pk.exports[i]['off'])
    out = bytearray(pk.d[:pk.exports[order[0]]['off']])
    new_pos = {}
    prev_end = len(out)
    for i in order:
        e = pk.exports[i]
        out += pk.d[prev_end:e['off']]  # any gap between exports (normally none)
        data = bytearray(new_target if i == idx - 1 else pk.d[e['off']:e['off'] + e['size']])
        new_off = len(out)
        if i != idx - 1 and new_off != e['off']:
            for p in bulk_offset_fields(data, e['off']):
                struct.pack_into('<i', data, p, new_off + p + 4)
        new_pos[i] = (new_off, len(data))
        out += data
        prev_end = e['off'] + e['size']
    out += pk.d[prev_end:]  # trailing bytes, if any

    for i, (off, size) in new_pos.items():
        struct.pack_into('<ii', out, pk.exports[i]['pos'] + 32, size, off)
    return bytes(out)


def check_package(data, movie_path, expect_gfx=None):
    """Re-parse package bytes and check export bounds, bulk offsets and the movie. Returns the Pkg."""
    pk = _pkg_from_bytes(data)
    order = sorted(pk.exports, key=lambda e: e['off'])
    for a, b in zip(order, order[1:]):
        assert a['off'] + a['size'] <= b['off'], 'exports overlap'
    assert order[-1]['off'] + order[-1]['size'] <= len(pk.d), 'export past end of file'
    for e in pk.exports:
        data = pk.d[e['off']:e['off'] + e['size']]
        for p in bulk_offset_fields(data, e['off']):
            assert struct.unpack_from('<i', data, p)[0] == e['off'] + p + 4
    if expect_gfx is not None:
        assert extract(pk, movie_path) == expect_gfx, 'movie bytes differ'
    return pk


def _pkg_from_bytes(b):
    import tempfile
    fd, name = tempfile.mkstemp(suffix='.upk')
    try:
        os.write(fd, b)
        os.close(fd)
        return Pkg(name)
    finally:
        os.unlink(name)


def bulk_fields_by_export(pk):
    return [len(bulk_offset_fields(pk.d[e['off']:e['off'] + e['size']], e['off'])) for e in pk.exports]


def padded_gfx(gfx, text=b'bl1-classic-minimap size-change test'):
    """Insert a Metadata tag (code 77) as the first tag; players skip it. Changes the movie size."""
    nbits = gfx[8] >> 3
    first_tag = 8 + (5 + 4 * nbits + 7) // 8 + 4
    body = text + b'\0'
    assert len(body) < 0x3F
    tag = struct.pack('<H', (77 << 6) | len(body)) + body
    out = bytearray(gfx[:first_tag] + tag + gfx[first_tag:])
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out)


def selftest(upk, movie_path):
    pk = Pkg(upk)
    gfx = extract(pk, movie_path)
    print('movie %s: %d bytes, signature %r, header length %d' % (movie_path, len(gfx), gfx[:3],
                                                                 struct.unpack_from('<I', gfx, 4)[0]))
    fields = bulk_fields_by_export(pk)
    print('exports %d, self-referencing bulk offsets found %d in %d exports'
          % (len(pk.exports), sum(fields), sum(1 for f in fields if f)))
    check_package(pk.d, movie_path, gfx)

    same = replace(pk, movie_path, gfx)
    assert same == pk.d, 'round trip changed bytes'
    print('round trip: byte-identical (%d bytes)' % len(same))

    for label, new_gfx in (('grow', padded_gfx(gfx)), ('shrink', gfx[:-16])):
        out = replace(pk, movie_path, new_gfx)
        pk2 = check_package(out, movie_path, new_gfx)
        idx, _ = find_export(pk, movie_path)
        delta = len(out) - len(pk.d)
        for i, (a, b) in enumerate(zip(pk.exports, pk2.exports)):
            assert a['name'] == b['name'] and a['cls'] == b['cls']
            if i == idx - 1:
                continue
            da = pk.d[a['off']:a['off'] + a['size']]
            db = pk2.d[b['off']:b['off'] + b['size']]
            moved = b['off'] - a['off']
            assert moved in (0, delta), (i, moved, delta)
            # identical apart from the rewritten bulk offsets
            fa = set(bulk_offset_fields(da, a['off']))
            assert fa == set(bulk_offset_fields(db, b['off']))
            diff = [p for p in range(len(da)) if da[p] != db[p]]
            assert all(any(f <= p < f + 4 for f in fa) for p in diff), (i, diff[:8])
        assert bulk_fields_by_export(pk2) == fields
        print('%s: movie %+d bytes, file %+d bytes, %d exports moved, all bulk offsets consistent'
              % (label, len(new_gfx) - len(gfx), delta,
                 sum(1 for a, b in zip(pk.exports, pk2.exports) if a['off'] != b['off'])))
    print('selftest OK')


def guid_offset(data):
    """File offset of the package GUID (v584 header: folder name, flags, 7 table ints, 1 int, GUID)."""
    n = struct.unpack_from('<i', data, 12)[0]
    return 12 + 4 + n + 4 + 7 * 4 + 4


def with_new_guid(data):
    """A package saved under a new file name gets its own GUID, so it can't be taken for the original."""
    out = bytearray(data)
    off = guid_offset(out)
    out[off:off + 16] = os.urandom(16)
    return bytes(out)


def main(argv):
    new_guid = '--new-guid' in argv
    argv = [a for a in argv if a != '--new-guid']
    cmd = argv[1]
    if cmd == 'extract':
        data = extract(Pkg(argv[2]), argv[3])
        open(argv[4], 'wb').write(data)
        print('wrote %s (%d bytes)' % (argv[4], len(data)))
    elif cmd == 'replace':
        pk = Pkg(argv[2])
        gfx = open(argv[4], 'rb').read()
        if gfx[:3] not in (b'GFX', b'FWS'):
            raise SystemExit('%s is not an uncompressed GFx/SWF file' % argv[4])
        out = replace(pk, argv[3], gfx)
        if new_guid:
            out = with_new_guid(out)
        check_package(out, argv[3], gfx)
        if os.path.abspath(argv[5]) == os.path.abspath(argv[2]):
            raise SystemExit('refusing to overwrite the input package')
        open(argv[5], 'wb').write(out)
        print('wrote %s (%d bytes, %+d)' % (argv[5], len(out), len(out) - len(pk.d)))
    elif cmd == 'selftest':
        selftest(argv[2], argv[3] if len(argv) > 3 else 'FlashMovie.HUD')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
