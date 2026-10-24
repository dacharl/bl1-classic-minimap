import re, sys, mmap
pat = re.compile(sys.argv[2].encode(), re.I)
with open(sys.argv[1], 'rb') as f:
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    seen = set()
    # ascii
    for mt in re.finditer(rb'[\x20-\x7e]{4,}', m):
        s = mt.group()
        if pat.search(s) and s not in seen:
            seen.add(s); print('A %08x %s' % (mt.start(), s.decode()))
    # utf16le
    for mt in re.finditer(rb'(?:[\x20-\x7e]\x00){4,}', m):
        s = mt.group().decode('utf-16le').encode()
        if pat.search(s) and s not in seen:
            seen.add(s); print('W %08x %s' % (mt.start(), s.decode()))
