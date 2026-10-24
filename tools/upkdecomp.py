"""Decompress a UE3 (BL1) LZO-compressed package into a flat, uncompressed .upk.
Usage: python -I upkdecomp.py in.u out.u
"""
import struct, sys

TAG = 0x9E2A83C1

def lzo1x_decompress(src, out_len):
    dst = bytearray()
    ip = 0
    n = len(src)
    def get():
        nonlocal ip
        b = src[ip]; ip += 1; return b
    def copy_match(dist, length):
        start = len(dst) - dist
        if start < 0:
            raise ValueError('bad dist')
        for i in range(length):
            dst.append(dst[start + i])
    t = get()
    state = 0
    if t > 17:
        t -= 17
        dst += src[ip:ip+t]; ip += t
        state = 4 if t >= 4 else t
        t = get()
    else:
        pass
    first = True
    while True:
        if not first:
            t = get()
        first = False
        if t < 16:
            if state == 0:
                # literal run
                if t == 0:
                    while src[ip] == 0:
                        t += 255; ip += 1
                    t += 15 + get()
                t += 3
                dst += src[ip:ip+t]; ip += t
                state = 4
                continue
            elif state != 4:
                # short match after short literal
                dist = 1 + (t >> 2) + (get() << 2)
                copy_match(dist, 2)
                lit = t & 3
            else:
                dist = 1 + 0x800 + (t >> 2) + (get() << 2)
                copy_match(dist, 3)
                lit = t & 3
        elif t >= 64:
            dist = 1 + ((t >> 2) & 7) + (get() << 3)
            length = (t >> 5) - 1 + 2
            copy_match(dist, length)
            lit = t & 3
        elif t >= 32:
            length = t & 31
            if length == 0:
                while src[ip] == 0:
                    length += 255; ip += 1
                length += 31 + get()
            length += 2
            b0 = get(); b1 = get()
            dist = 1 + ((b0 | (b1 << 8)) >> 2)
            copy_match(dist, length)
            lit = b0 & 3
        else:  # 16..31
            length = t & 7
            if length == 0:
                while src[ip] == 0:
                    length += 255; ip += 1
                length += 7 + get()
            length += 2
            b0 = get(); b1 = get()
            dist = ((t & 8) << 11) + ((b0 | (b1 << 8)) >> 2)
            if dist == 0:
                break  # end of stream
            dist += 0x4000
            copy_match(dist, length)
            lit = b0 & 3
        state = lit
        if lit:
            dst += src[ip:ip+lit]; ip += lit
    if len(dst) != out_len:
        raise ValueError('size mismatch %d != %d' % (len(dst), out_len))
    return bytes(dst)


def main(inp, outp):
    data = open(inp, 'rb').read()
    assert struct.unpack_from('<I', data, 0)[0] == TAG
    # locate the compressed chunk table: flags==2 followed by count, then entries whose
    # compressedOffset points at a chunk TAG.
    for pos in range(0x20, 0x200):
        flags, count = struct.unpack_from('<II', data, pos)
        if flags not in (1, 2, 4) or not (0 < count < 4096):
            continue
        ok = True
        chunks = []
        for i in range(count):
            uo, us, co, cs = struct.unpack_from('<4i', data, pos + 8 + 16 * i)
            if co <= 0 or co + 4 > len(data):
                ok = False; break
            # stored chunks (compressed size == uncompressed size) have no chunk header
            if struct.unpack_from('<I', data, co)[0] != TAG and not (cs == us and co + cs <= len(data)):
                ok = False; break
            chunks.append((uo, us, co, cs))
        if ok:
            break
    else:
        raise SystemExit('chunk table not found')
    print('flags', flags, 'chunks', count, 'table@', hex(pos))
    total = max(uo + us for uo, us, _, _ in chunks)
    out = bytearray(total)
    first_uo = chunks[0][0]
    out[:first_uo] = data[:first_uo]
    for uo, us, co, cs in chunks:
        if struct.unpack_from('<I', data, co)[0] != TAG:  # stored chunk
            out[uo:uo + us] = data[co:co + cs]
            continue
        tag, bsz, csz, usz = struct.unpack_from('<4I', data, co)
        nblocks = (usz + bsz - 1) // bsz
        p = co + 16
        blocks = [struct.unpack_from('<II', data, p + 8 * j) for j in range(nblocks)]
        p += 8 * nblocks
        w = uo
        for bc, bu in blocks:
            dec = lzo1x_decompress(data[p:p+bc], bu)
            out[w:w+bu] = dec
            w += bu; p += bc
    # clear compression flags + chunk count so tools treat it as uncompressed
    struct.pack_into('<II', out, pos, 0, 0)
    open(outp, 'wb').write(out)
    print('wrote', outp, len(out))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
