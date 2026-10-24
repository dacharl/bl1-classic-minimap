"""Keep one REA MCP server (and its Ghidra import) alive and feed it tool calls.

REA re-imports a target for every CLI run (~14 min for the BL1 exes), so this
starts `rea-agents mcp` once and serves requests from a spool directory.

  rea_client.py serve <spool>                    run the server loop (background)
  rea_client.py call <spool> <tool> '<json args>' [out.json]
                                                 queue one call, wait, print result

Ghidra/Java come from the same env vars as the ~/.claude.json registration.
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid

REA = ["cmd.exe", "/d", "/c", "npx", "-y", "rea-agents@6.7.0", "mcp"]
ENV = {
    "GHIDRA_INSTALL_DIR": r"C:\Users\Charles\Tools\ghidra_12.1.4_PUBLIC",
    "JAVA_HOME": r"C:\Users\Charles\Tools\jdk-21.0.12.1+1",
    "REA_GHIDRA_STARTUP_TIMEOUT_MS": "2700000",
    "REA_GHIDRA_DISABLED_ANALYZERS": "Decompiler Switch Analysis,Function ID,Call Convention ID,"
                                     "Embedded Media,Non-Returning Functions - Discovered",
}


class Server:
    def __init__(self, log):
        self.proc = subprocess.Popen(REA, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=log, env={**os.environ, **ENV})
        self.pending, self.lock, self.next_id = {}, threading.Lock(), 0
        threading.Thread(target=self._reader, daemon=True).start()
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "rea_client", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def _reader(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            ev = self.pending.get(msg.get("id"))
            if ev is not None and ("result" in msg or "error" in msg):
                ev.append(msg)

    def request(self, method, params):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        box = []
        self.pending[rid] = box
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while not box:
            if self.proc.poll() is not None:
                raise SystemExit("REA server exited")
            time.sleep(0.2)
        del self.pending[rid]
        return box[0]


def serve(spool):
    req_dir, resp_dir = os.path.join(spool, "req"), os.path.join(spool, "resp")
    os.makedirs(req_dir, exist_ok=True)
    os.makedirs(resp_dir, exist_ok=True)
    srv = Server(open(os.path.join(spool, "server.log"), "ab"))
    print("ready", flush=True)
    while True:
        names = sorted(n for n in os.listdir(req_dir) if n.endswith(".json"))
        for name in names:
            path = os.path.join(req_dir, name)
            req = json.load(open(path, encoding="utf-8"))
            os.remove(path)
            t0 = time.time()
            print("call", req["tool"], flush=True)
            msg = srv.request("tools/call", {"name": req["tool"], "arguments": req["args"]})
            msg["elapsed_s"] = round(time.time() - t0, 1)
            tmp = os.path.join(resp_dir, name + ".tmp")
            json.dump(msg, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, os.path.join(resp_dir, name))
            print("done", req["tool"], msg["elapsed_s"], flush=True)
        time.sleep(0.3)


def call(spool, tool, args, out=None):
    name = "%d_%s.json" % (time.time() * 1000, uuid.uuid4().hex[:6])
    tmp = os.path.join(spool, "req", name + ".tmp")
    json.dump({"tool": tool, "args": json.loads(args)}, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, os.path.join(spool, "req", name))
    resp = os.path.join(spool, "resp", name)
    while not os.path.exists(resp):
        time.sleep(0.5)
    msg = json.load(open(resp, encoding="utf-8"))
    text = "\n".join(c.get("text", "") for c in msg.get("result", {}).get("content", []))
    if out:
        open(out, "w", encoding="utf-8").write(text or json.dumps(msg))
        print("wrote", out, len(text), "chars,", msg.get("elapsed_s"), "s",
              "ERROR" if msg.get("error") or msg.get("result", {}).get("isError") else "")
    else:
        print(text or json.dumps(msg))


if __name__ == "__main__":
    if sys.argv[1] == "serve":
        serve(sys.argv[2])
    elif sys.argv[1] == "call":
        call(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)
