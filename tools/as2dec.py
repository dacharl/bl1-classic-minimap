"""Turn swfdump.py action listings into readable pseudo-AS2 via a symbolic stack.
Usage: python -I as2dec.py listing.txt startline endline
"""
import re, sys

BIN = {'Add2': '+', 'Add': '+', 'Subtract': '-', 'Multiply': '*', 'Divide': '/', 'Modulo': '%',
       'Less2': '<', 'Less': '<', 'Greater': '>', 'Equals2': '==', 'Equals': '==', 'StrictEquals': '===',
       'And': '&&', 'Or': '||', 'BitAnd': '&', 'BitOr': '|', 'BitXor': '^', 'BitLShift': '<<',
       'BitRShift': '>>', 'BitURShift': '>>>', 'StringAdd': '+', 'StringEquals': 'eq', 'InstanceOf': 'instanceof'}

line_re = re.compile(r'^(\s*)([0-9a-f]{4}) (\w+) ?(.*)$')

def split_args(s):
    out, cur, q, depth = [], '', None, 0
    for ch in s:
        if q:
            cur += ch
            if ch == q and not cur.endswith('\\' + q): q = None
            continue
        if ch in '\'"': q = ch; cur += ch; continue
        if ch == ',' and depth == 0: out.append(cur.strip()); cur = ''; continue
        cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

def member(obj, name):
    if len(name) > 2 and name[0] == "'" and re.match(r"^'[A-Za-z_$][\w$]*'$", name):
        return '%s.%s' % (obj, name[1:-1])
    return '%s[%s]' % (obj, name)

def var(name):
    return name[1:-1] if name.startswith("'") else 'eval(%s)' % name

def run(lines):
    st = []; out = []
    for raw in lines:
        if raw.strip().startswith('function '):
            out.append(raw.rstrip()); st = []; continue
        if raw.strip() == '}':
            out.append(raw.rstrip()); continue
        m = line_re.match(raw)
        if not m: continue
        ind, off, op, arg = m.groups()
        pop = lambda: st.pop() if st else '?'
        emit = lambda s: out.append('%s%s: %s' % (ind, off, s))
        if op == 'Push': st.extend(split_args(arg))
        elif op == 'Pop':
            v = pop()
            if not re.match(r"^[\w'.]+$", v): emit(v)
        elif op == 'PushDuplicate': st.append(st[-1] if st else '?')
        elif op == 'StackSwap':
            a = pop(); b = pop(); st += [a, b]
        elif op == 'GetVariable': st.append(var(pop()))
        elif op == 'SetVariable': v = pop(); n = pop(); emit('%s = %s' % (var(n), v))
        elif op in ('DefineLocal',): v = pop(); n = pop(); emit('var %s = %s' % (var(n), v))
        elif op == 'DefineLocal2': emit('var %s' % var(pop()))
        elif op == 'GetMember': n = pop(); o = pop(); st.append(member(o, n))
        elif op == 'SetMember': v = pop(); n = pop(); o = pop(); emit('%s = %s' % (member(o, n), v))
        elif op == 'StoreRegister':
            v = st[-1] if st else '?'; emit('%s = %s' % (arg, v)); st[-1:] = [arg] if st else []
        elif op in ('CallFunction', 'NewObject'):
            n = pop(); k = pop()
            try: k = int(float(k))
            except ValueError: k = 0
            a = [pop() for _ in range(k)]
            st.append('%s%s(%s)' % ('new ' if op == 'NewObject' else '', var(n), ', '.join(a)))
        elif op in ('CallMethod', 'NewMethod'):
            n = pop(); o = pop(); k = pop()
            try: k = int(float(k))
            except ValueError: k = 0
            a = [pop() for _ in range(k)]
            f = o if n in ("''", 'undefined') else member(o, n)
            st.append('%s%s(%s)' % ('new ' if op == 'NewMethod' else '', f, ', '.join(a)))
        elif op in BIN: b = pop(); a = pop(); st.append('(%s %s %s)' % (a, BIN[op], b))
        elif op == 'Not': st.append('!%s' % pop())
        elif op in ('Increment', 'Decrement'): st.append('(%s %s 1)' % (pop(), '+' if op == 'Increment' else '-'))
        elif op in ('ToNumber', 'ToString', 'ToInteger', 'TypeOf'): st.append('%s(%s)' % (op, pop()))
        elif op == 'InitArray':
            k = int(float(pop())); st.append('[%s]' % ', '.join(pop() for _ in range(k)))
        elif op == 'InitObject':
            k = int(float(pop())); kv = []
            for _ in range(k): v = pop(); n = pop(); kv.append('%s: %s' % (n, v))
            st.append('{%s}' % ', '.join(kv))
        elif op == 'If': emit('if %s goto %s' % (pop(), arg));
        elif op == 'Jump': emit('goto %s' % arg)
        elif op == 'Return': emit('return %s' % pop())
        elif op == 'GotoFrame2' or op == 'GoToLabel': emit('%s %s' % (op, arg or pop()))
        elif op in ('Stop', 'Play'): emit(op.lower() + '()')
        elif op == 'Delete' : n = pop(); o = pop(); emit('delete %s' % member(o, n))
        elif op == 'Extends': s = pop(); c = pop(); emit('%s extends %s' % (c, s))
        elif op == 'ConstantPool': pass
        else: emit('<%s %s>' % (op, arg))
    return out

if __name__ == '__main__':
    lines = open(sys.argv[1]).read().splitlines()[int(sys.argv[2]) - 1:int(sys.argv[3])]
    print('\n'.join(run(lines)))
