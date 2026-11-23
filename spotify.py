"""Ponte com o Spotify: o Jarvis enfileira comandos, a extensão Spicetify executa.

Fluxo: a extensão roda dentro do Spotify, faz GET /spicetify/next a cada ~700 ms,
executa o que houver e POSTa /spicetify/state com faixa, progresso e volume.
Sem OAuth, sem chave, sem internet extra — só o Spotify aberto.
"""
import threading, time

STATE_KEYS = ("playing", "title", "artist", "album", "art", "position", "duration",
              "volume", "shuffle", "repeat", "liked")


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = []
        self.acks = {}
        self.state = {k: (False if k == "playing" else 0 if k in ("position", "duration", "volume", "repeat") else "")
                      for k in STATE_KEYS}
        self.seen = 0.0
        self.seq = 0
        self.last_error = ""

    def online(self):
        return time.time() - self.seen < 8

    def cmd(self, action, **kw):
        """Enfileira e devolve o id do comando (0 se a extensão está offline)."""
        if not self.online():
            return 0
        with self.lock:
            self.seq += 1
            cid = self.seq
            self.pending.append({"id": cid, "action": action, **kw})
            if len(self.pending) > 16:
                self.pending = self.pending[-16:]
        return cid

    def ack(self, data):
        """A extensão confirma o que realmente aconteceu — sem isso o Jarvis mentiria."""
        try:
            cid = int(data.get("id") or 0)
        except Exception:
            return False
        if cid <= 0:
            return False
        with self.lock:
            self.acks[cid] = {"ok": bool(data.get("ok")), "error": str(data.get("error") or "")[:200]}
            if len(self.acks) > 64:
                for k in sorted(self.acks)[:-32]:
                    self.acks.pop(k, None)
        self.last_error = "" if data.get("ok") else str(data.get("error") or "falhou")[:200]
        return True

    def wait(self, cid, timeout=3.0):
        """Espera a confirmação de um comando. None = a extensão não respondeu."""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if cid in self.acks:
                    return self.acks.pop(cid)
            time.sleep(0.05)
        return None

    def take(self):
        with self.lock:
            out, self.pending = self.pending, []
        return out

    def update(self, data):
        if not isinstance(data, dict):
            return False
        with self.lock:
            for k in STATE_KEYS:
                if k in data:
                    self.state[k] = data[k]
            self.state["title"] = str(self.state.get("title") or "")[:160]
            self.state["artist"] = str(self.state.get("artist") or "")[:160]
        self.seen = time.time()
        return True

    def snapshot(self):
        with self.lock:
            d = dict(self.state)
        d["online"] = self.online()
        d["has_command"] = bool(self.pending)
        d["last_error"] = self.last_error
        return d
