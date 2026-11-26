"""Unit tests for the binary readers and writers under the movie builder: as2asm (AS2 bytecode), upk (UE3
packages) and swfdeps (character dependencies). Each fixture is authored here from the file formats, not
produced by the code under test. They exist because the 2026-11-26 mutation run left most mutants of these
three files alive (PHASE3 3cf): opcode values, push encodings, string forms, outer chains and the per-tag
reference scan were not pinned.
"""
import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'sdk_mods', 'classic_minimap'))
import as2asm  # noqa: E402
import swfdeps  # noqa: E402
import upk  # noqa: E402
from as2asm import Reg  # noqa: E402
from ci_fixture import movie  # noqa: E402
from swfmerge import tag  # noqa: E402
from test_swfmerge import BitWriter, rich_shape  # noqa: E402


def H(v):
    return struct.pack('<H', v)


# Action codes from the SWF file format specification (version 10), spelled out independently of OPS.
SPEC_OPS = {
    'NextFrame': 0x04, 'PrevFrame': 0x05, 'Play': 0x06, 'Stop': 0x07, 'Add': 0x0A, 'Subtract': 0x0B,
    'Multiply': 0x0C, 'Divide': 0x0D, 'Equals': 0x0E, 'Less': 0x0F, 'And': 0x10, 'Or': 0x11, 'Not': 0x12,
    'Pop': 0x17, 'ToInteger': 0x18, 'GetVariable': 0x1C, 'SetVariable': 0x1D, 'StringAdd': 0x21,
    'GetProperty': 0x22, 'SetProperty': 0x23, 'Trace': 0x26, 'Delete': 0x3A, 'Delete2': 0x3B,
    'DefineLocal': 0x3C, 'CallFunction': 0x3D, 'Return': 0x3E, 'Modulo': 0x3F, 'NewObject': 0x40,
    'DefineLocal2': 0x41, 'InitArray': 0x42, 'InitObject': 0x43, 'TypeOf': 0x44, 'TargetPath': 0x45,
    'Add2': 0x47, 'Less2': 0x48, 'Equals2': 0x49, 'ToNumber': 0x4A, 'ToString': 0x4B, 'PushDuplicate': 0x4C,
    'StackSwap': 0x4D, 'GetMember': 0x4E, 'SetMember': 0x4F, 'Increment': 0x50, 'Decrement': 0x51,
    'CallMethod': 0x52, 'NewMethod': 0x53, 'StrictEquals': 0x66, 'Greater': 0x67,
    'StoreRegister': 0x87, 'ConstantPool': 0x88, 'GoToLabel': 0x8C, 'DefineFunction2': 0x8E, 'Push': 0x96,
    'Jump': 0x99, 'GetURL2': 0x9A, 'DefineFunction': 0x9B, 'If': 0x9D, 'GotoFrame2': 0x9F,
}


class As2asmChecks(unittest.TestCase):
    def test_opcode_table_matches_the_specification(self):
        self.assertEqual(as2asm.OPS, SPEC_OPS)
        self.assertEqual(as2asm.NAMES, {v: k for k, v in SPEC_OPS.items()})
        self.assertEqual(as2asm.BRANCHES, (0x99, 0x9D))

    def test_every_bodyless_opcode_is_one_byte_and_round_trips(self):
        for name, op in SPEC_OPS.items():
            if op < 0x80:
                self.assertEqual(as2asm.encode([{'op': op}]), bytes([op]), name)
                self.assertEqual(as2asm.decode(bytes([op])), [{'op': op}], name)

    def test_end_marker(self):
        self.assertEqual(as2asm.encode([{'op': 0x17}], end=True), b'\x17\x00')
        self.assertEqual(as2asm.decode(b'\x17\x00\x17'), [{'op': 0x17}], 'decoding stops at End')

    def test_register_repr(self):
        self.assertEqual(repr(Reg(7)), 'r7')

    def test_push_encodes_every_value_kind(self):
        golden = [
            (['ab'], b'\x00ab\x00'),
            ([Reg(3)], b'\x04\x03'),
            ([None], b'\x02'),
            ([Ellipsis], b'\x03'),
            ([True, False], b'\x05\x01\x05\x00'),
            ([5], b'\x07\x05\x00\x00\x00'),
            ([-1], b'\x07\xff\xff\xff\xff'),
            ([2**31 - 1], b'\x07\xff\xff\xff\x7f'),
            ([-2**31], b'\x07\x00\x00\x00\x80'),
            ([1.5], b'\x06\x00\x00\xf8\x3f\x00\x00\x00\x00'),             # a double: high word first
            ([2**31], b'\x06\x00\x00\xe0\x41\x00\x00\x00\x00'),           # too big for an int32: a double
            ([-2**31 - 1], b'\x06\x00\x00\xe0\xc1\x00\x00\x20\x00'),
            (['é'], b'\x00\xe9\x00'),
        ]
        for values, body in golden:
            record = bytes([0x96]) + H(len(body)) + body
            self.assertEqual(as2asm.encode([{'op': 0x96, 'args': values}]), record, values)

    def test_push_decodes_every_value_kind(self):
        def decode(body, pool=()):
            return as2asm.decode(bytes([0x96]) + H(len(body)) + body, pool)[0]['args']
        self.assertEqual(decode(b'\x00ab\x00\x00\x00'), ['ab', ''])
        self.assertEqual(decode(b'\x01' + struct.pack('<f', 2.5)), [2.5])
        self.assertEqual(decode(b'\x02\x03'), [None, Ellipsis])
        regs = decode(b'\x04\x09')
        self.assertEqual((type(regs[0]), regs[0].n), (Reg, 9))
        self.assertEqual(decode(b'\x05\x01\x05\x00'), [True, False])
        self.assertEqual(decode(b'\x06\x00\x00\xf8\x3f\x00\x00\x00\x00'), [1.5])
        self.assertEqual(decode(b'\x07\xfe\xff\xff\xff'), [-2])
        self.assertEqual(decode(b'\x08\x01\x09\x00\x00', ['a', 'b']), ['b', 'a'])
        with self.assertRaisesRegex(ValueError, 'push type 10'):
            decode(b'\x0a')

    def test_constant_pool_references_become_literals(self):
        pool = b'\x88' + H(2 + 3 + 3) + H(2) + b'xy\x00' + b'zw\x00'
        push = b'\x96' + H(2) + b'\x08\x01'
        self.assertEqual(as2asm.decode(pool + push), [{'op': 0x96, 'args': ['zw']}])

    def test_branches_are_encoded_as_offsets_and_decoded_as_indices(self):
        forward = [{'op': 0x99, 'target': 2}, {'op': 0x17}, {'op': 0x17}]
        self.assertEqual(as2asm.encode(forward), b'\x99\x02\x00\x01\x00\x17\x17')
        self.assertEqual(as2asm.decode(as2asm.encode(forward)), forward)
        backward = [{'op': 0x17}, {'op': 0x9D, 'target': 0}]
        self.assertEqual(as2asm.encode(backward), b'\x17\x9d\x02\x00\xfa\xff')
        self.assertEqual(as2asm.decode(as2asm.encode(backward)), backward)
        to_end = [{'op': 0x99, 'target': 1}]
        self.assertEqual(as2asm.decode(as2asm.encode(to_end, end=True)), to_end)

    def test_define_function_round_trips_with_exact_bytes(self):
        ins = {'op': 0x9B, 'func': {'name': 'f', 'v2': False, 'params': ['a', 'bc'], 'body': [{'op': 0x17}]}}
        code = b'\x9b' + H(2 + 2 + 2 + 3 + 2) + b'f\x00' + H(2) + b'a\x00bc\x00' + H(1) + b'\x17'
        self.assertEqual(as2asm.encode([ins]), code)
        self.assertEqual(as2asm.decode(code), [ins])

    def test_define_function2_round_trips_with_exact_bytes(self):
        ins = {'op': 0x8E, 'func': {'name': '', 'v2': True, 'regcount': 4, 'flags': 0x0141,
                                    'params': [(1, 'x'), (2, 'yz')], 'body': [{'op': 0x17}, {'op': 0x17}]}}
        hdr = b'\x00' + H(2) + b'\x04' + H(0x0141) + b'\x01x\x00' + b'\x02yz\x00' + H(2)
        code = b'\x8e' + H(len(hdr)) + hdr + b'\x17\x17'
        self.assertEqual(as2asm.encode([ins]), code)
        self.assertEqual(as2asm.decode(code), [ins])

    def test_function_bodies_decode_with_the_enclosing_pool(self):
        pool = b'\x88' + H(2 + 2) + H(1) + b'k\x00'
        body = b'\x96' + H(2) + b'\x08\x00'
        func = b'\x9b' + H(2 + 2 + 2) + b'f\x00' + H(0) + H(len(body)) + body
        decoded = as2asm.decode(pool + func)
        self.assertEqual(decoded[0]['func']['body'], [{'op': 0x96, 'args': ['k']}])

    def test_records_with_small_bodies(self):
        cases = [
            ({'op': 0x87, 'args': 5}, b'\x87\x01\x00\x05'),
            ({'op': 0x9A, 'args': 1}, b'\x9a\x01\x00\x01'),
            ({'op': 0x8C, 'args': 'lbl'}, b'\x8c\x04\x00lbl\x00'),
            ({'op': 0x9F, 'args': b'\x01'}, b'\x9f\x01\x00\x01'),
            ({'op': 0x81, 'args': b'\x02\x00'}, b'\x81\x02\x00\x02\x00'),
            ({'op': 0x8D}, b'\x8d\x00\x00'),
        ]
        for ins, code in cases:
            self.assertEqual(as2asm.encode([ins]), code, ins)
        for ins, code in cases[:-1]:
            self.assertEqual(as2asm.decode(code), [ins], ins)
        self.assertEqual(as2asm.decode(b'\x8d\x00\x00'), [{'op': 0x8D}])

    def test_a_string_ends_at_its_terminator_and_the_push_goes_on(self):
        self.assertEqual(as2asm.decode(b'\x96\x06\x00\x00hi\x00\x02\x03')[0]['args'], ['hi', None, Ellipsis])


def package_bytes(names, imports=(), exports=()):
    """An uncompressed v584 package. exports: (class, outer, name index, name number, data) tuples; imports:
    (class package index, class name index, outer, name index, name number)."""
    def fs(i):
        if max(map(ord, names[i]), default=0) > 255:        # not Latin-1: stored as UTF-16, length negated
            raw = (names[i] + '\0').encode('utf-16le')
            return struct.pack('<i', -(len(raw) // 2)) + raw
        raw = names[i].encode('latin-1') + b'\0'
        return struct.pack('<i', len(raw)) + raw
    header = struct.pack('<IHHi', 0x9E2A83C1, 584, 0, 0) + b'\x05\x00\x00\x00None\x00' + struct.pack('<I', 0)
    tables_at = len(header) + 24
    name_table = b''.join(fs(i) + b'\0' * 8 for i in range(len(names)))
    imp_off = tables_at + len(name_table)
    exp_off = imp_off + 28 * len(imports)
    data_at = exp_off + 68 * len(exports)
    imp_table = b''.join(struct.pack('<7i', cp, 0, cn, 0, outer, on, onn) for cp, cn, outer, on, onn in imports)
    exp_table, blobs = b'', b''
    for cls, outer, name, num, data in exports:
        exp_table += (struct.pack('<6i', cls, 0, outer, name, num, 0) + struct.pack('<Q', 0x1234)
                      + struct.pack('<2i', len(data), data_at + len(blobs)) + struct.pack('<Ii', 0, 0)
                      + b'\0' * 16 + struct.pack('<I', 0))
        blobs += data
    counts = struct.pack('<6i', len(names), tables_at, len(exports), exp_off, len(imports), imp_off)
    return header + counts + name_table + imp_table + exp_table + blobs


NAMES = ['None', 'RawData', 'ArrayProperty', 'IntProperty', 'BoolProperty', 'StructProperty', 'Pkg', 'Sub', 'Mov',
         'Core', 'Engine', 'Ref', 'Unit', 'Own Class', 'Ωπ-é']


def prop(name, typ, size, extra=b'', payload=b''):
    return (struct.pack('<ii', NAMES.index(name), 0) + struct.pack('<ii', NAMES.index(typ), 0)
            + struct.pack('<ii', size, 0) + extra + payload)


def raw_export(gfx, before=b'', length=None):
    body = struct.pack('<i', len(gfx) if length is None else length) + gfx
    data = struct.pack('<i', 0) + before + prop('RawData', 'ArrayProperty', 4 + len(gfx), payload=body)
    return data + struct.pack('<ii', NAMES.index('None'), 0)


class UpkChecks(unittest.TestCase):
    def package(self, gfx=b'GFXdata', **kw):
        exports = [(0, 0, NAMES.index('Pkg'), 0, b''), (0, 1, NAMES.index('Sub'), 0, b''),
                   (0, 2, NAMES.index('Mov'), 0, raw_export(gfx, **kw))]
        return package_bytes(NAMES, exports=exports)

    def test_header_and_tables_are_read(self):
        data = package_bytes(NAMES, imports=[(9, 12, 0, 9, 0)], exports=[(0, 0, 6, 0, b'abcd')])
        pk = upk.Pkg(data=data)
        self.assertEqual((pk.ver, pk.name_count, pk.exp_count, pk.imp_count), (584, len(NAMES), 1, 1))
        self.assertEqual(pk.names, NAMES)
        e = pk.exports[0]
        self.assertEqual((e['cls'], e['sup'], e['outer'], e['name'], e['size'], e['flags']), (0, 0, 0, 'Pkg', 4, 0x1234))
        self.assertEqual(data[e['off']:e['off'] + 4], b'abcd')
        self.assertEqual(data[e['pos'] + 32:e['pos'] + 36], struct.pack('<i', 4), 'pos is the entry start')
        self.assertEqual(pk.imports, [{'cls': 'Unit', 'pkg': 'Core', 'outer': 0, 'name': 'Core'}])

    def test_the_package_is_read_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'p.upk')
            with open(path, 'wb') as f:
                f.write(self.package())
            self.assertEqual(upk.Pkg(path).name_count, len(NAMES))

    def test_strings_are_latin_1_or_utf_16(self):
        data = package_bytes(NAMES, )
        pk = upk.Pkg(data=data)
        self.assertEqual(pk.names, NAMES, 'a negative length is a UTF-16 string, in characters')
        latin = package_bytes(['None', 'café'])
        self.assertEqual(upk.Pkg(data=latin).names, ['None', 'café'])
        s, end = pk.fstring(pk.name_off)
        self.assertEqual((s, end), ('None', pk.name_off + 4 + 5))
        wide = struct.pack('<i', -3) + 'ab\0'.encode('utf-16le') + b'tail'
        s, end = upk.Pkg.fstring(type('D', (), {'d': wide})(), 0)
        self.assertEqual((s, end), ('ab', 4 + 6))

    def test_numbered_names(self):
        pk = upk.Pkg(data=self.package())
        self.assertEqual(pk.fname(NAMES.index('Mov'), 0), 'Mov')
        self.assertEqual(pk.fname(NAMES.index('Mov'), 3), 'Mov_2')

    def test_object_names_and_paths(self):
        data = package_bytes(
            NAMES,
            imports=[(9, 12, 0, 9, 0), (9, 12, -1, 10, 0)],              # Core; Engine inside Core
            exports=[(0, 0, 6, 0, b''), (0, 1, 7, 0, b''), (0, 2, 8, 3, b''),   # Pkg.Sub.Mov_2
                     (-2, -2, 11, 0, b''), (3, 0, 11, 1, b'')])           # Ref in Engine, of class Engine
        pk = upk.Pkg(data=data)
        self.assertEqual([pk.objname(i) for i in (0, 1, 3, -1, -2)], ['', 'Pkg', 'Mov_2', 'Core', 'Engine'])
        self.assertEqual(pk.path(3), 'Pkg.Sub.Mov_2')
        self.assertEqual(pk.path(4), 'Core.Engine.Ref')
        self.assertEqual(pk.path(-2), 'Core.Engine')
        self.assertEqual(pk.path(0), '')
        self.assertEqual(pk.clsname(pk.exports[3]), 'Engine', 'a class that is an import')
        self.assertEqual(pk.clsname(pk.exports[4]), 'Mov_2', 'a class that is an export')
        self.assertEqual(pk.clsname(pk.exports[0]), 'Class', 'no class means Class')

    def test_find_export(self):
        pk = upk.Pkg(data=self.package())
        index, e = upk.find_export(pk, 'Pkg.Sub.Mov')
        self.assertEqual((index, e['name']), (3, 'Mov'))
        with self.assertRaisesRegex(upk.PackageError, r"export 'Pkg\.Nope' not found"):
            upk.find_export(pk, 'Pkg.Nope')

    def test_raw_data_is_found_after_other_properties(self):
        before = (prop('IntProperty', 'IntProperty', 4, payload=b'\x01\x02\x03\x04')
                  + prop('BoolProperty', 'BoolProperty', 0, extra=b'\x01\x00\x00\x00')
                  + prop('Sub', 'StructProperty', 3, extra=struct.pack('<ii', 6, 0), payload=b'xyz'))
        pk = upk.Pkg(data=self.package(before=before))
        e = pk.exports[2]
        tp, dp, size = upk.raw_data_span(pk, e)
        self.assertEqual(size, 4 + len(b'GFXdata'))
        base = 4 + len(before)                                  # after the NetIndex and the other properties
        self.assertEqual((tp, dp), (base, base + 24))
        self.assertEqual(upk.extract(pk, 'Pkg.Sub.Mov'), b'GFXdata')

    def test_a_missing_raw_data_property_is_an_error(self):
        data = struct.pack('<i', 0) + struct.pack('<ii', NAMES.index('None'), 0)
        pk = upk.Pkg(data=package_bytes(NAMES, exports=[(0, 0, 8, 0, data)]))
        with self.assertRaisesRegex(upk.PackageError, 'RawData not found'):
            upk.raw_data_span(pk, pk.exports[0])
        not_array = struct.pack('<i', 0) + prop('RawData', 'IntProperty', 4, payload=b'\0' * 4) \
            + struct.pack('<ii', NAMES.index('None'), 0)
        pk = upk.Pkg(data=package_bytes(NAMES, exports=[(0, 0, 8, 0, not_array)]))
        with self.assertRaisesRegex(upk.PackageError, 'RawData not found'):
            upk.raw_data_span(pk, pk.exports[0])

    def test_a_raw_data_length_that_disagrees_with_its_property_is_an_error(self):
        pk = upk.Pkg(data=self.package(length=3))
        with self.assertRaisesRegex(upk.PackageError, r'RawData length 3 does not match its property size 11'):
            upk.extract(pk, 'Pkg.Sub.Mov')

    def test_movie(self):
        self.assertEqual(upk.movie(self.package(b'GFXabc'), 'Pkg.Sub.Mov'), b'GFXabc')
        self.assertEqual(upk.movie(self.package(b'FWSabc'), 'Pkg.Sub.Mov'), b'FWSabc')
        with self.assertRaisesRegex(upk.PackageError, r'Pkg\.Sub\.Mov is not an uncompressed GFx movie'):
            upk.movie(self.package(b'CWSabc'), 'Pkg.Sub.Mov')
        with self.assertRaisesRegex(upk.PackageError, r'^export .FlashMovie\.HUD. not found'):
            upk.movie(self.package(b'GFXabc'))
        with self.assertRaisesRegex(upk.PackageError, r'unreadable package \(error\)'):
            upk.movie(self.package(b'GFXabc')[:20], 'Pkg.Sub.Mov')

    def test_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'p.upk')
            with open(path, 'wb') as f:
                f.write(self.package())
            out = io.StringIO()
            old = sys.argv
            try:
                sys.argv = ['upk.py', path, 'sub\\.mov']
                with contextlib.redirect_stdout(out):
                    upk.main()
                lines = out.getvalue().splitlines()
                self.assertEqual(lines[0], 'ver 584 names %d exports 3 imports 0' % len(NAMES))
                self.assertEqual(len(lines), 2, 'the pattern filters, ignoring case')
                self.assertTrue(lines[1].startswith('     3 Class                  Pkg.Sub.Mov '), lines[1])
                self.assertIn('size=%d' % len(raw_export(b'GFXdata')), lines[1])
                out = io.StringIO()
                sys.argv = ['upk.py', path]
                with contextlib.redirect_stdout(out):
                    upk.main()
                self.assertEqual(len(out.getvalue().splitlines()), 4)
            finally:
                sys.argv = old


def named(entries):
    return H(len(entries)) + b''.join(H(i) + n.encode() + b'\0' for i, n in entries)


def place2(depth, char=None):
    return tag(26, bytes([0x02 if char is not None else 0x00]) + H(depth) + (H(char) if char is not None else b''))


def sprite_of(sid, *tags):
    return tag(39, H(sid) + H(1) + b''.join(tags) + tag(1, b'') + tag(0, b''))


def matrix_bytes():
    return BitWriter().matrix().data()


class SwfdepsChecks(unittest.TestCase):
    def movie(self, *tags):
        return swfdeps.Movie(data=movie(list(tags)))

    def test_definitions_are_indexed_including_nested_ones(self):
        shape_code, shape_body, _, _ = rich_shape(1)
        m = self.movie(tag(shape_code, shape_body), sprite_of(10, tag(22, H(11) + b'rest')),
                       tag(2, H(5) + b'duplicate'), tag(39, b'x'))
        self.assertEqual(set(m.defs), {5, 10, 11})
        self.assertEqual(m.defs[5], (shape_code, shape_body), 'the first definition of an id wins')
        self.assertEqual(m.defs[11][0], 22, 'a shape inside a sprite is still defined')
        self.assertEqual(m.defs[10][0], 39)

    def test_exports_and_imports_are_read_at_any_depth(self):
        imports = tag(57, b'lib.swf\x00' + named([(9, 'Name'), (8, 'Other')]))
        m = self.movie(tag(56, named([(1, 'one'), (2, 'two')])), sprite_of(10, tag(56, named([(3, 'deep')]))), imports)
        self.assertEqual(m.exports, {1: 'one', 2: 'two', 3: 'deep'})
        self.assertEqual(m.imports, {9: ('lib.swf', 'Name'), 8: ('lib.swf', 'Other')})

    def test_a_movie_is_read_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'm.gfx')
            with open(path, 'wb') as f:
                f.write(movie([sprite_of(4)]))
            self.assertEqual(set(swfdeps.Movie(path).defs), {4})

    def test_sprite_placements(self):
        m = self.movie(sprite_of(10, place2(1, 20), place2(2), tag(70, b'\x02\x00' + H(3) + H(30)),
                                 tag(70, b'\x00\x00' + H(4) + H(99)), tag(4, H(40) + H(5) + matrix_bytes()),
                                 tag(26, b'\x00' + H(6) + H(98))))
        self.assertEqual(m.refs(10), {20, 30, 40})

    def test_shape_bitmaps(self):
        code, body, _, bitmaps = rich_shape(3)
        m = self.movie(tag(code, body))
        self.assertEqual(m.refs(5), bitmaps)
        self.assertEqual(swfdeps.shape_bitmaps(code, body), bitmaps)

    def test_edit_text_font(self):
        rect = BitWriter().u(1, 5).u(0, 1).u(0, 1).u(0, 1).u(0, 1).data()   # a 1-bit rectangle, padded
        with_font = tag(37, H(20) + rect + H(0x0001) + H(12))
        without = tag(37, H(21) + rect + H(0x0000))
        self.assertEqual(self.movie(with_font, without).refs(20), {12})
        self.assertEqual(self.movie(with_font, without).refs(21), set())

    def test_buttons(self):
        records = b'\x01' + H(31) + H(1) + matrix_bytes() + b'\x02' + H(32) + H(2) + matrix_bytes() + b'\x00'
        button = tag(7, H(30) + records)
        cxform = BitWriter().u(1, 1).u(1, 1).u(3, 4)
        for _ in range(8):
            cxform.u(5, 3)
        cx = cxform.data()
        records2 = (b'\x01' + H(41) + H(1) + matrix_bytes() + cx + b'\x02' + H(42) + H(2) + matrix_bytes() + cx
                    + b'\x00')
        button2 = tag(34, H(40) + b'\x00' + H(0) + records2)
        no_cx = BitWriter().u(0, 1).u(0, 1).u(2, 4).data()
        button2b = tag(34, H(50) + b'\x00' + H(0) + b'\x01' + H(51) + H(1) + matrix_bytes() + no_cx + b'\x00')
        m = self.movie(button, button2, button2b)
        self.assertEqual(m.refs(30), {31, 32})
        self.assertEqual(m.refs(40), {41, 42})
        self.assertEqual(m.refs(50), {51})

    def test_other_definitions_have_no_references(self):
        self.assertEqual(self.movie(tag(48, H(9) + b'font')).refs(9), set())

    def test_closure_follows_references_and_ignores_cycles(self):
        code, body, _, _ = rich_shape(1)                                   # shape 5, bitmap 7
        m = self.movie(tag(code, body), tag(20, H(7) + b'bits'), sprite_of(10, place2(1, 5), place2(2, 11)),
                       sprite_of(11, place2(1, 10)))
        self.assertEqual(m.closure([10]), {10, 5, 7, 11})
        self.assertEqual(m.closure([99]), {99}, 'an undefined id is kept, not followed')
        self.assertEqual(m.closure([]), set())

    def run_main(self, data, *roots):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'm.gfx')
            with open(path, 'wb') as f:
                f.write(data)
            old, out = sys.argv, io.StringIO()
            try:
                sys.argv = ['swfdeps.py', path, *[str(r) for r in roots]]
                with contextlib.redirect_stdout(out):
                    swfdeps.main()
            finally:
                sys.argv = old
        return out.getvalue()

    def test_command_line_report(self):
        code, body, _, _ = rich_shape(1)
        bitmap = tag(20, H(7) + b'bits')
        sprite = sprite_of(10, place2(1, 5))
        image = tag(1001, H(8) + bytes(7) + bytes([5]) + b'a.tga')
        image2 = tag(1001, H(13) + bytes(7) + b'\x00\x00alt\x00')
        font = tag(48, H(12) + b'font')
        imports = tag(57, b'x.swf\x00' + named([(9, 'Name')]))
        out = self.run_main(movie([tag(code, body), bitmap, sprite, image, image2, font, imports]), 10, 8, 13, 9, 12, 77)
        sizes = len(body) + len(H(7) + b'bits') + len(H(10) + H(1) + place2(1, 5) + tag(1, b'') + tag(0, b'')) \
            + len(H(8) + bytes(7) + bytes([5]) + b'a.tga') + len(H(13) + bytes(7) + b'\x00\x00alt\x00') \
            + len(H(12) + b'font')

        def row(kind, ids):
            return '  %-18s %4d  %s\n' % (kind, len(ids), ids)
        expected = (
            'closure of [10, 8, 13, 9, 12, 77]: 8 characters, %d bytes of definitions\n' % sizes
            + row('BitsLossless', [7]) + row('Font2', [12]) + row('GFxExternalImage', [8, 13])
            + row('Imported', [9]) + row('Shape', [5]) + row('Sprite', [10])
            + '    external image 8 -> a.tga\n    external image 13 -> alt\n'
            + "    imported 9 -> ('x.swf', 'Name')\n    font 12\n  undefined ids: [77]\n")
        self.assertEqual(out, expected)

    def test_command_line_report_truncates_long_lists(self):
        sprites = [sprite_of(i) for i in range(1, 14)]
        out = self.run_main(movie(sprites), *range(1, 14))
        self.assertIn('  %-18s %4d  %s\n' % ('Sprite', 13, list(range(1, 13)) + ['...']), out)
        self.assertNotIn('undefined', out)

    def test_kind_names(self):
        self.assertEqual(swfdeps.NAMES[39], 'Sprite')
        self.assertEqual(swfdeps.NAMES[1003], 'GFxGradientImage')


if __name__ == '__main__':
    unittest.main()
