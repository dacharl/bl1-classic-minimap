"""AS2 action bytecode: decode to a small IR, re-encode, and build new code.

IR instruction: {'op': code, 'args': ..., 'target': index (Jump/If), 'func': {...} (DefineFunction/2)}.
Jumps point at instruction indices, so instructions can change length (e.g. constant-pool references
rewritten as literal strings) and encode() recomputes every branch offset.
"""
import struct

OPS = {
    'NextFrame': 0x04, 'PrevFrame': 0x05, 'Play': 0x06, 'Stop': 0x07, 'Add': 0x0A, 'Subtract': 0x0B,
    'Multiply': 0x0C, 'Divide': 0x0D, 'Equals': 0x0E, 'Less': 0x0F, 'And': 0x10, 'Or': 0x11, 'Not': 0x12,
    'Pop': 0x17, 'ToInteger': 0x18, 'GetVariable': 0x1C, 'SetVariable': 0x1D, 'StringAdd': 0x21,
    'GetProperty': 0x22, 'SetProperty': 0x23, 'Trace': 0x26, 'Delete': 0x3A, 'Delete2': 0x3B,
    'DefineLocal': 0x3C, 'CallFunction': 0x3D, 'Return': 0x3E, 'Modulo': 0x3F, 'NewObject': 0x40,
    'DefineLocal2': 0x41, 'InitArray': 0x42, 'InitObject': 0x43, 'TypeOf': 0x44, 'TargetPath': 0x45,
    'Add2': 0x47, 'Less2': 0x48, 'Equals2': 0x49, 'ToNumber': 0x4A, 'ToString': 0x4B, 'PushDuplicate': 0x4C,
    'StackSwap': 0x4D, 'GetMember': 0x4E, 'SetMember': 0x4F, 'Increment': 0x50, 'Decrement': 0x51,
    'CallMethod': 0x52, 'NewMethod': 0x53, 'StrictEquals': 0x66, 'Greater': 0x67,
    'StoreRegister': 0x87, 'ConstantPool': 0x88, 'DefineFunction2': 0x8E, 'Push': 0x96, 'Jump': 0x99,
    'GetURL2': 0x9A, 'DefineFunction': 0x9B, 'If': 0x9D, 'GotoFrame2': 0x9F, 'GoToLabel': 0x8C,
}
NAMES = {v: k for k, v in OPS.items()}
BRANCHES = (0x99, 0x9D)


class Reg:
    def __init__(self, n):
        self.n = n

    def __repr__(self):
        return 'r%d' % self.n


def _cstr(b, p):
    j = b.index(b'\0', p)
    return b[p:j].decode('latin-1'), j + 1


def _decode_push(body, pool):
    q, vals = 0, []
    while q < len(body):
        t = body[q]; q += 1
        if t == 0:
            s, q = _cstr(body, q); vals.append(s)
        elif t == 1:
            vals.append(struct.unpack_from('<f', body, q)[0]); q += 4
        elif t == 2:
            vals.append(None)
        elif t == 3:
            vals.append(Ellipsis)  # undefined
        elif t == 4:
            vals.append(Reg(body[q])); q += 1
        elif t == 5:
            vals.append(bool(body[q])); q += 1
        elif t == 6:
            hi, lo = struct.unpack_from('<II', body, q); q += 8
            vals.append(struct.unpack('<d', struct.pack('<II', lo, hi))[0])
        elif t == 7:
            vals.append(struct.unpack_from('<i', body, q)[0]); q += 4
        elif t in (8, 9):
            i = body[q] if t == 8 else struct.unpack_from('<H', body, q)[0]
            q += 1 if t == 8 else 2
            vals.append(pool[i])
        else:
            raise ValueError('push type %d' % t)
    return vals


def decode(b, pool=None):
    """Decode actions up to End (0x00) or the end of b. Constant-pool references become literals."""
    pool = list(pool or [])
    instrs, starts, p = [], {}, 0
    pending = []
    while p < len(b):
        start = p
        op = b[p]; p += 1
        if op == 0:
            p = start  # branches may target the End marker itself
            break
        body = b''
        if op >= 0x80:
            ln = struct.unpack_from('<H', b, p)[0]; p += 2
            body = b[p:p + ln]; p += ln
        ins = {'op': op}
        if op == 0x88:
            n = struct.unpack_from('<H', body, 0)[0]; q = 2; pool = []
            for _ in range(n):
                s, q = _cstr(body, q); pool.append(s)
            starts[start] = len(instrs)
            continue  # literals replace the pool
        elif op == 0x96:
            ins['args'] = _decode_push(body, pool)
        elif op in BRANCHES:
            pending.append((ins, p + struct.unpack_from('<h', body, 0)[0]))
        elif op in (0x9B, 0x8E):
            name, q = _cstr(body, 0)
            n = struct.unpack_from('<H', body, q)[0]; q += 2
            f = {'name': name, 'v2': op == 0x8E}
            if op == 0x9B:
                params = []
                for _ in range(n):
                    s, q = _cstr(body, q); params.append(s)
                f['params'] = params
            else:
                f['regcount'] = body[q]; f['flags'] = struct.unpack_from('<H', body, q + 1)[0]; q += 3
                params = []
                for _ in range(n):
                    reg = body[q]; s, q = _cstr(body, q + 1); params.append((reg, s))
                f['params'] = params
            size = struct.unpack_from('<H', body, q)[0]
            f['body'] = decode(b[p:p + size], pool)
            p += size
            ins['func'] = f
        elif op == 0x87:
            ins['args'] = body[0]
        elif op == 0x9A:
            ins['args'] = body[0]
        elif op == 0x9F:
            ins['args'] = body
        elif op == 0x8C:
            ins['args'] = _cstr(body, 0)[0]
        elif body:
            ins['args'] = body
        starts[start] = len(instrs)
        instrs.append(ins)
    starts[p] = len(instrs)
    for ins, target in pending:
        ins['target'] = starts[target]
    return instrs


def _enc_push(vals):
    out = bytearray()
    for v in vals:
        if isinstance(v, Reg):
            out += bytes([4, v.n])
        elif v is None:
            out += b'\x02'
        elif v is Ellipsis:
            out += b'\x03'
        elif isinstance(v, bool):
            out += bytes([5, int(v)])
        elif isinstance(v, int) and -2**31 <= v < 2**31:
            out += b'\x07' + struct.pack('<i', v)
        elif isinstance(v, (int, float)):
            d = struct.pack('<d', float(v))
            lo, hi = struct.unpack('<II', d)
            out += b'\x06' + struct.pack('<II', hi, lo)
        else:
            out += b'\x00' + str(v).encode('latin-1') + b'\0'
    return bytes(out)


def _record(op, body=b''):
    if op < 0x80:
        return bytes([op])
    return bytes([op]) + struct.pack('<H', len(body)) + body


def encode(instrs, end=False):
    """Encode IR to bytes. Branch offsets are solved iteratively (sizes don't depend on them)."""
    chunks = []
    for ins in instrs:
        op = ins['op']
        if op == 0x96:
            chunks.append(_record(op, _enc_push(ins['args'])))
        elif op in BRANCHES:
            chunks.append(None)  # fixed size 5, filled below
        elif op in (0x9B, 0x8E):
            f = ins['func']
            code = encode(f['body'])
            hdr = f['name'].encode('latin-1') + b'\0' + struct.pack('<H', len(f['params']))
            if op == 0x9B:
                for s in f['params']:
                    hdr += s.encode('latin-1') + b'\0'
            else:
                hdr += bytes([f['regcount']]) + struct.pack('<H', f['flags'])
                for reg, s in f['params']:
                    hdr += bytes([reg]) + s.encode('latin-1') + b'\0'
            hdr += struct.pack('<H', len(code))
            chunks.append(_record(op, hdr) + code)
        elif op in (0x87, 0x9A):
            chunks.append(_record(op, bytes([ins['args']])))
        elif op == 0x8C:
            chunks.append(_record(op, ins['args'].encode('latin-1') + b'\0'))
        elif 'args' in ins and isinstance(ins['args'], (bytes, bytearray)):
            chunks.append(_record(op, bytes(ins['args'])))
        else:
            chunks.append(_record(op))
    sizes = [5 if c is None else len(c) for c in chunks]
    pos = [0]
    for s in sizes:
        pos.append(pos[-1] + s)
    out = bytearray()
    for i, (ins, c) in enumerate(zip(instrs, chunks)):
        if c is None:
            off = pos[ins['target']] - pos[i + 1]
            c = _record(ins['op'], struct.pack('<h', off))
        out += c
    if end:
        out += b'\0'
    return bytes(out)


class Asm:
    """Tiny builder: a.push(...); a.op('GetMember'); a.label('x'); a.jump('x'); a.if_('x')."""

    def __init__(self):
        self.ins, self.labels, self.fix = [], {}, []

    def op(self, *names):
        for n in names:
            self.ins.append({'op': OPS[n]})
        return self

    def push(self, *vals):
        self.ins.append({'op': 0x96, 'args': list(vals)})
        return self

    def label(self, name):
        self.labels[name] = len(self.ins)
        return self

    def jump(self, name):
        self.ins.append({'op': 0x99}); self.fix.append((self.ins[-1], name))
        return self

    def if_(self, name):
        self.ins.append({'op': 0x9D}); self.fix.append((self.ins[-1], name))
        return self

    def store(self, reg):
        self.ins.append({'op': 0x87, 'args': reg})
        return self

    # ---- helpers -------------------------------------------------------------------------------
    def get(self, path):
        """Push the value at a dotted path, e.g. 'map.maps.themap'."""
        parts = path.split('.')
        self.push(parts[0]).op('GetVariable')
        for p in parts[1:]:
            self.push(p).op('GetMember')
        return self

    def set_member(self, path, value_fn):
        """path 'a.b.c' = value pushed by value_fn(self)."""
        obj, member = path.rsplit('.', 1)
        self.get(obj).push(member)
        value_fn(self)
        return self.op('SetMember')

    def set_var(self, name, value_fn):
        self.push(name); value_fn(self)
        return self.op('SetVariable')

    def local(self, name, value_fn):
        self.push(name); value_fn(self)
        return self.op('DefineLocal')

    def call_method(self, obj_fn, method, *arg_fns):
        """obj.method(args) - leaves the result on the stack."""
        for fn in reversed(arg_fns):
            fn(self)
        self.push(len(arg_fns))
        obj_fn(self)
        self.push(method)
        return self.op('CallMethod')

    def build(self):
        for ins, name in self.fix:
            ins['target'] = self.labels[name]
        return self.ins


_BIN = {'+': 'Add2', '-': 'Subtract', '*': 'Multiply', '/': 'Divide', '<': 'Less2', '>': 'Greater',
        '==': 'Equals2', '%': 'Modulo'}


def emit(a, e):
    """Push the value of expression e.

    number / bool / None / Ellipsis(undefined) -> literal      'path.to.var' -> variable (dotted get)
    ('s', text) -> string literal                             (op, x, y) for + - * / < > == %
    ('!', x)                                                  ('mem', obj, name) / ('idx', obj, key)
    ('call', obj, method, *args) -> obj.method(args)          ('fn', name, *args) -> name(args)
    ('new', ClassName, *args)                                 ('eval', x) -> variable named by x's value
    ('newm', obj, ClassName, *args) -> new obj.ClassName(args), e.g. new flash.geom.Matrix(...)
    """
    if isinstance(e, str):
        return a.get(e)
    if not isinstance(e, tuple):
        return a.push(e)
    k = e[0]
    if k == 's':
        return a.push(e[1])
    if k in _BIN:
        emit(a, e[1]); emit(a, e[2])
        return a.op(_BIN[k])
    if k == '!':
        emit(a, e[1])
        return a.op('Not')
    if k == 'eval':
        emit(a, e[1])
        return a.op('GetVariable')
    if k == 'mem':
        emit(a, e[1]); a.push(e[2])
        return a.op('GetMember')
    if k == 'idx':
        emit(a, e[1]); emit(a, e[2])
        return a.op('GetMember')
    if k in ('call', 'fn', 'new', 'newm'):
        args = e[3:] if k in ('call', 'newm') else e[2:]
        for x in reversed(args):
            emit(a, x)
        a.push(len(args))
        if k in ('call', 'newm'):
            emit(a, e[1]); a.push(e[2])
            return a.op('CallMethod' if k == 'call' else 'NewMethod')
        a.push(e[1])
        return a.op('CallFunction' if k == 'fn' else 'NewObject')
    raise ValueError(e)


class Fn(Asm):
    """Statement helpers on top of Asm, for writing functions."""

    def local(self, name, e):
        self.push(name); emit(self, e)
        return self.op('DefineLocal')

    def setv(self, name, e):
        self.push(name); emit(self, e)
        return self.op('SetVariable')

    def setm(self, obj, member, e):
        emit(self, obj); self.push(member); emit(self, e)
        return self.op('SetMember')

    def do(self, e):
        emit(self, e)
        return self.op('Pop')

    def ret(self, e=Ellipsis):
        emit(self, e)
        return self.op('Return')

    def if_not(self, e, label):
        """Jump to label when e is false."""
        emit(self, e); self.op('Not')
        return self.if_(label)


def function(name, params, body_asm):
    """DefineFunction (v1) IR instruction: named function on the current timeline."""
    return {'op': 0x9B, 'func': {'name': name, 'v2': False, 'params': list(params), 'body': body_asm.build()}}


def find_function(instrs, name):
    for ins in instrs:
        if ins['op'] in (0x9B, 0x8E) and ins['func']['name'] == name:
            return ins
    return None
