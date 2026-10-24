"""Decode SteamStub code encryption into a same-length analysis copy.

Classic Borderlands.exe uses SteamStub variant 2.1 (x86): the .bind stub
carries a rolling-XOR header, an XOR'd payload holding the AES key/IV/stolen
block, and an XTEA'd SteamDRMP.dll whose code locates those fields in the
payload. Enhanced BorderlandsGOTY.exe uses variant 3.1 (x64): a 0xF0 XOR'd
header just before the entry point holds the AES key, IV and stolen block.
This follows Steamless (atom0s, commit cd770bf9, Variant21.x86/Variant31.x64)
but only rewrites the encrypted code range. Headers, sections, .bind and the
protected entry point are kept, so file offsets and VAs match the original.
The result is for static analysis only; it is not a runnable game.

usage: steamstub.py <protected.exe> <out.exe>
needs: pefile, pycryptodome
"""
import hashlib
import re
import struct
import sys

import pefile
from Crypto.Cipher import AES

# mov/mov pairs in SteamDRMP.dll that copy payload fields; Steamless' primary
# pattern and its operand offsets (flags, appid, OEP, code VA, size, key, iv).
DRMP_PATTERN = (b"\x8B.{5}\x89.{5}" * 5) + b"\x8D.{5}\x05"
DRMP_FIELDS = (2, 14, 26, 38, 50, 62, 67)
NO_ENCRYPTION = 0x04


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def steam_xor(data, key):
    out = bytearray(data)
    for x in range(0, len(out) & ~3, 4):
        v = u32(data, x)
        struct.pack_into("<I", out, x, v ^ key)
        key = v
    return out, key


def xtea_decrypt_pass1(data, keys):
    delta, mask = 0x9E3779B9, 0xFFFFFFFF
    out = bytearray(data)
    p1 = p2 = 0x55555555
    for x in range(0, len(data) & ~7, 8):
        d1, d2 = struct.unpack_from("<II", data, x)
        v1, v2, s = d1, d2, (delta * 32) & mask
        for _ in range(32):
            v2 = (v2 - ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + keys[(s >> 11) & 3]))) & mask
            s = (s - delta) & mask
            v1 = (v1 - ((((v2 << 4) ^ (v2 >> 5)) + v2) ^ (s + keys[s & 3]))) & mask
        struct.pack_into("<II", out, x, v1 ^ p1, v2 ^ p2)
        p1, p2 = d1, d2
    return out


def stub_header_location(pe, data):
    """The stub entry copies the header with `mov [ebp-x], VA; ...; mov ecx, dwords`
    and seeds the XOR chain with `mov [ebp-y], key`; read those immediates."""
    ep_off = pe.get_offset_from_rva(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
    if u32(data, ep_off - 4) != 0xC0DEC0DE:
        raise SystemExit("not SteamStub 2.x: no 0xC0DEC0DE before the entry point")
    code = data[ep_off:ep_off + 0x80]
    if not code.startswith(bytes.fromhex("5351525657558BEC81EC00100000C7")):
        raise SystemExit("entry stub does not match the Variant 2.1 x86 signature")
    va = u32(code, 0x11)                                  # mov [ebp-80h], imm32
    count = u32(code, code.index(b"\xB9", 0x15) + 1)      # mov ecx, imm32 (dwords)
    key = u32(code, code.index(b"\xC7\x85", 0x20) + 6)    # mov [ebp-3BCh], imm32
    return va, count * 4, key


def decrypt_code(data, text_off, size, aes_key, enc_iv, stolen):
    iv = AES.new(aes_key, AES.MODE_ECB).decrypt(enc_iv)
    plain = AES.new(aes_key, AES.MODE_CBC, iv).decrypt(stolen + data[text_off:text_off + size])
    out = bytearray(data)
    out[text_off:text_off + size] = plain[:size]
    return bytes(out), plain[size:]


def decode31(data, pe):
    ep_off = pe.get_offset_from_rva(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
    hdr, _ = steam_xor(data[ep_off - 0xF0:ep_off], u32(data, ep_off - 0xF0))
    if u32(hdr, 4) != 0xC0DEC0DF:
        raise SystemExit("not SteamStub 3.1 x64: header signature mismatch")
    code_va, appid, flags = struct.unpack_from("<Q", hdr, 0x48)[0], u32(hdr, 0x38), u32(hdr, 0x3C)
    info = {"appid": appid, "flags": flags, "oep": struct.unpack_from("<Q", hdr, 0x20)[0],
            "code_va": code_va}
    if flags & NO_ENCRYPTION:
        raise SystemExit("code section is not encrypted (flags %#x)" % flags)
    # Steamless decrypts the whole raw section (not CodeSectionRawSize).
    sec = next(s for s in pe.sections
               if s.VirtualAddress <= code_va < s.VirtualAddress + s.Misc_VirtualSize)
    info["encrypted_size"] = sec.SizeOfRawData
    out, extra = decrypt_code(data, sec.PointerToRawData, sec.SizeOfRawData,
                              bytes(hdr[0x58:0x78]), bytes(hdr[0x78:0x88]), bytes(hdr[0x88:0x98]))
    return out, extra, info


def decode(src):
    data = open(src, "rb").read()
    pe = pefile.PE(data=data, fast_load=True)
    if pe.FILE_HEADER.Machine == 0x8664:
        return decode31(data, pe)
    base = pe.OPTIONAL_HEADER.ImageBase
    va_off = lambda va: pe.get_offset_from_rva(va - base)

    hva, hsize, hkey = stub_header_location(pe, data)
    hdr, key = steam_xor(data[va_off(hva):va_off(hva) + hsize], hkey)
    payload_va, payload_size, appid = u32(hdr, 0x24), u32(hdr, 0x28), u32(hdr, 0x2C)
    drmp_va_at, drmp_size_at, xtea_at = u32(hdr, 0x3C), u32(hdr, 0x40), u32(hdr, 0x44)

    payload, _ = steam_xor(data[va_off(payload_va):va_off(payload_va) + payload_size], key)
    drmp_va, drmp_size = u32(payload, drmp_va_at), u32(payload, drmp_size_at)
    keys = [u32(payload, o) for o in range(xtea_at, len(payload) - 3, 4)]
    drmp = xtea_decrypt_pass1(data[va_off(drmp_va):va_off(drmp_va) + drmp_size], keys)

    m = re.search(DRMP_PATTERN, bytes(drmp), re.S)
    if not m:
        raise SystemExit("SteamDRMP.dll field pattern not found")
    flags_at, appid_at, oep_at, code_va_at, size_at, key_at, iv_at = (
        u32(drmp, m.start() + f) for f in DRMP_FIELDS)
    flags = u32(payload, flags_at)
    code_va, enc_size = u32(payload, code_va_at), u32(payload, size_at)
    info = {
        "appid": appid, "payload_appid": u32(payload, appid_at), "flags": flags,
        "oep": u32(payload, oep_at), "code_va": code_va, "encrypted_size": enc_size,
        "drmp_size": drmp_size,
    }
    if flags & NO_ENCRYPTION:
        raise SystemExit("code section is not encrypted (flags %#x)" % flags)

    out, extra = decrypt_code(data, va_off(code_va), enc_size, bytes(payload[key_at:key_at + 32]),
                              bytes(payload[iv_at:iv_at + 16]), bytes(payload[iv_at + 16:iv_at + 32]))
    return out, extra, info


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    out, extra, info = decode(sys.argv[1])
    open(sys.argv[2], "wb").write(out)
    open(sys.argv[2] + ".extra.bin", "wb").write(extra)
    for k, v in info.items():
        print("%-15s %#x" % (k, v))
    print("sha256         ", hashlib.sha256(out).hexdigest())


if __name__ == "__main__":
    main()
