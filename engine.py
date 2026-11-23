"""Motor em segundo plano: timers, lembretes e histórico da área de transferência."""
import threading, time


class Engine:
    def __init__(self, store, cfg, speak):
        self.store, self.cfg, self.speak = store, cfg, speak
        self.events, self.timers = [], {}
        self.lock = threading.Lock()
        self._n, self._clip = 0, None
        threading.Thread(target=self.loop, daemon=True).start()

    def push(self, **e):
        with self.lock:
            self.events.append(e)

    def drain(self):
        with self.lock:
            ev, self.events = self.events, []
        return ev

    def add_timer(self, secs, label=""):
        self._n += 1
        self.timers[self._n] = {"end": time.time() + secs, "label": label}
        return self._n

    def cancel(self, id=None):
        if id is None:
            self.timers.clear()
        else:
            self.timers.pop(id, None)

    def list_timers(self):
        now = time.time()
        return [{"id": i, "label": t["label"], "left": max(0, int(t["end"] - now))}
                for i, t in sorted(self.timers.items())]

    def alert(self, text):
        self.push(type="alert", text=text)
        if self.cfg.get("voice_reply"):
            self.speak(text)

    def loop(self):
        while True:
            now = time.time()
            try:
                for r in self.store.due(now):
                    self.store.update(r["id"], done=1)
                    self.alert("Lembrete: " + r["text"])
                for i, t in list(self.timers.items()):
                    if t["end"] <= now:
                        del self.timers[i]
                        self.alert("Timer finalizado" + (": " + t["label"] if t["label"] else "."))
                self.watch_clip()
            except Exception:
                pass
            time.sleep(1)

    def watch_clip(self):
        if not self.cfg.get("clip"):
            return
        try:
            import pyperclip
            txt = pyperclip.paste()
        except Exception:
            return
        if txt and txt != self._clip and len(txt) < 3000:
            self._clip = txt
            self.store.add("clip", txt)
            self.store.prune("clip", 50)
