"""Build an asset-free movie from project code and independently authored stubs.

The five native-facing functions model the documented test contract, not game
bytecode. Empty shapes replace all artwork. This fixture exercises our builder,
AS2 and mod logic; it cannot verify copied game functions, art or Scaleform.
"""
import struct

from as2asm import Fn, function
from swfbuild import build, tag
import as2asm


def movie(tags):
    payload = b'\x08\x00\x00\x18\x01\x00' + b''.join(tags) + tag(1, b'') + tag(0, b'')
    return b'FWS\x08' + struct.pack('<I', 8 + len(payload)) + payload


def sprite(sid, children=(), labels=()):
    placements = [tag(26, b'\x02' + struct.pack('<HH', depth, child)) for depth, child in children]
    frames = [tag(43, label.encode() + b'\0') + tag(1, b'') for label in labels] or [tag(1, b'')]
    return tag(39, struct.pack('<HH', sid, max(1, len(labels)))
               + b''.join(placements + frames) + tag(0, b''))


def native_contract():
    functions = []
    a = Fn().local('target', ('eval', 'clip'))
    a.local('depth', ('call', 'map.maps', 'getNextHighestDepth'))
    a.local('newObject', ('call', 'target', 'duplicateMovieClip', ('+', 'frame', 'depth'), 'depth'))
    a.do(('call', 'newObject', 'gotoAndStop', 'frame'))
    a.push('newClip').get('newObject').op('TargetPath', 'DefineLocal')
    a.do(('fn', 'UpdateLandmark', 'newClip', 'x', 'y', 'r'))
    a.ret('newClip')
    functions.append(function('AddLandmark', ('clip', 'x', 'y', 'r', 'frame'), a))

    a = Fn().local('target', ('eval', 'clip'))
    for field, value, extent in (('_x', 'x', '_width'), ('_y', 'y', '_height')):
        a.setm('target', field, ('+', ('mem', 'map.maps.themap', field),
                               ('*', value, ('mem', 'map.maps.themap', extent))))
    a.setm('target', '_rotation', 'r').ret()
    functions.append(function('UpdateLandmark', ('clip', 'x', 'y', 'r'), a))

    a = Fn().setm('map.maps.themap', '_xscale', 'scale').setm('map.maps.themap', '_yscale', 'scale')
    a.setm('map.maps.themap', '_x', ('*', -0.5, 'map.maps.themap._width'))
    a.setm('map.maps.themap', '_y', ('*', -0.5, 'map.maps.themap._height')).ret()
    functions.append(function('SetMapScale', ('scale',), a))

    a = Fn().setm('_root', 'LoadDLCPackage', 'pkg')
    a.do(('call', 'map.maps', 'gotoAndStop', 'frame')).ret()
    functions.append(function('InitDLC', ('frame', 'pkg'), a))

    a = Fn().local('tint', ('new', 'Color', ('eval', 'clip')))
    a.do(('call', 'tint', 'setRGB', 'color')).ret()
    functions.append(function('SetMarkerColor', ('color', 'clip'), a))
    return functions


def build_fixture():
    status = movie([
        sprite(1040), sprite(1050), sprite(1066, [(1, 1050)], ['questionmark']),
        sprite(1132, [(1, 1066)]), sprite(1154, [(1, 1040), (5, 1040), (8, 1132)]),
        tag(12, as2asm.encode(native_contract(), end=True)),
    ])
    enhanced = movie([tag(2, struct.pack('<H', sid) + b'\x08\x00\x00\x00\x00\x00')
                      for sid in (108, 110, 179)])
    data, _ = build(movie([]), status, enhanced)
    return data
