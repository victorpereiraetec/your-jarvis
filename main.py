"""Jarvis — assistente pessoal para Windows. Rode: python main.py

Janela principal + mini player (frameless, sempre no topo) + atalhos globais +
ponte com o Spotify via extensão Spicetify e Windows SMTC. Tudo local, porta fixa em 127.0.0.1.
"""
import ctypes, json, re, secrets, sys, threading, time, webbrowser, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import voice
from agent import Agent
from brain import Brain, BrainError, PROVIDERS, ORDER
from commands import Commands, key, set_volume, opener, fold
from engine import Engine
from hotkey import Hotkeys
from nowplaying import NowPlaying
from spotify import Bridge
from store import Store
from sysinfo import MACHINE

ROOT = Path(__file__).parent
DATA = ROOT / "data"
UI = ROOT / "ui"
DATA.mkdir(exist_ok=True)
TOKEN = secrets.token_urlsafe(16)
PORT = 0
PORTS = range(8765, 8776)

MAIN_WIN = None
MINI_WIN = None
MINI_SHOWN = [False]
HOTKEYS = None


class Config:
    DEFAULTS = {"user": "", "mode": "auto", "voice_reply": False, "wake": False, "clip": False,
                "voice": "pt-BR-AntonioNeural", "voice_rate": 8,
                "providers": {}, "apps": {}, "hotkeys": {"mini": "ctrl+alt+j", "focus": "ctrl+alt+space"}}

    def __init__(self, path):
        self.p, self.d = path, dict(self.DEFAULTS)
        if path.exists():
            try:
                self.d.update(json.loads(path.read_text("utf-8")))
            except Exception:
                pass
        self.save()

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v
        self.save()

    def save(self):
        self.p.write_text(json.dumps(self.d, ensure_ascii=False, indent=2), "utf-8")


def toggle_mini():
    """Mostra/esconde o mini player. Seguro quando a janela não existe (modo headless)."""
    if MINI_WIN is None:
        return False
    try:
        if MINI_SHOWN[0]:
            MINI_WIN.hide()
        else:
            MINI_WIN.show()
            MINI_WIN.restore()
        MINI_SHOWN[0] = not MINI_SHOWN[0]
        return True
    except Exception:
        return False


def focus_main():
    """Traz a janela principal para a frente e pede foco no campo de texto."""
    try:
        if MAIN_WIN is not None:
            MAIN_WIN.show()
            MAIN_WIN.restore()
        API.engine.push(type="focus")
    except Exception:
        pass


class Api:
    """Tudo que a interface pode pedir. Só os métodos em PUBLIC ficam acessíveis."""
    PUBLIC = {"state", "chat", "history", "clear_chat", "items", "add_item", "toggle_item", "del_item",
              "habit_done", "run_routine", "timers", "add_timer", "cancel_timer", "media", "volume",
              "sysinfo", "brain_info", "set_provider", "set_mode", "test_provider", "set_setting",
              "listen", "poll", "open", "spotify_state", "spotify_cmd", "mini_toggle", "win_focus",
              "agent_log", "hotkey_info", "voice_info", "set_voice", "test_voice", "stop_voice"}

    def __init__(self):
        self.cfg = Config(DATA / "config.json")
        self.store = Store(str(DATA / "sexta.db"))
        self.brain = Brain(self.cfg)
        self.engine = Engine(self.store, self.cfg, voice.speak)
        self.cmd = Commands(self)
        self.spotify = Bridge()
        self.now = NowPlaying(self.spotify, set_volume)
        self.agent = Agent(self)
        self._wake = None
        voice.configure(self.cfg.get("voice"), self.cfg.get("voice_rate"))
        if self.cfg.get("wake"):
            self._start_wake()

    @property
    def name(self):
        return self.cfg.get("user") or "chefe"

    # ---------- estado
    def state(self):
        c, s = self.cfg, self.store
        return {"user": c.get("user"), "name": self.name, "mode": c.get("mode"), "brain": self.brain.status(),
                "wake": c.get("wake"), "voice_reply": c.get("voice_reply"), "clip": c.get("clip"),
                "spotify": self.now.online(),
                "counts": {"reminders": s.count("reminder", True), "tasks": s.count("task", True),
                           "habits": s.count("habit"), "timers": len(self.engine.timers)}}

    def poll(self):
        return {"events": self.engine.drain()}

    def open(self, url):
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        elif "." in url:
            webbrowser.open("https://" + url)

    # ---------- mini player e atalhos
    def mini_toggle(self):
        return {"ok": toggle_mini(), "visible": MINI_SHOWN[0]}

    def win_focus(self):
        focus_main()
        return {"ok": True}

    def hotkey_info(self):
        spec = self.cfg.get("hotkeys") or {}
        return {"bindings": spec, "status": (HOTKEYS.status if HOTKEYS else {}),
                "mini": MINI_WIN is not None}

    def agent_log(self, lines=80):
        p = DATA / "agent.log"
        if not p.exists():
            return {"text": "Nenhuma ferramenta executada ainda."}
        rows = p.read_text("utf-8", errors="replace").splitlines()
        return {"text": "\n".join(rows[-max(1, min(500, int(lines))):])}

    # ---------- conversa
    def chat(self, text, speak=None):
        text = (text or "").strip()
        if not text:
            return {"reply": "", "via": ""}
        self.store.add("chat", "u|" + text)
        via = "local"
        try:
            reply = self.cmd.run(text)
        except Exception as e:
            reply, via = f"Erro ao executar o comando: {e}", "erro"
        if reply is None:
            hist = [{"role": "user" if h["text"].startswith("u|") else "assistant", "content": h["text"][2:]}
                    for h in self.store.list("chat", 10, asc=False)[::-1]]
            try:
                res = self.agent.run(text, hist[:-1])
                reply, via = res["reply"], res["via"]
            except BrainError as e:
                reply, via = str(e), "erro"
            except Exception as e:
                reply, via = f"Falha do agente: {type(e).__name__}: {e}", "erro"
        self.store.add("chat", "a|" + reply)
        if speak or (speak is None and self.cfg.get("voice_reply")):
            voice.speak(reply)
        return {"reply": reply, "via": via}

    def history(self):
        return [{"role": "u" if h["text"].startswith("u|") else "a", "text": h["text"][2:]}
                for h in self.store.list("chat", 40)[::-1]]

    def clear_chat(self):
        self.store.clear("chat")
        return {"ok": True}

    # ---------- listas (memória, tarefas, lembretes, hábitos, copiados, rotinas)
    def items(self, kind):
        out = self.store.list(kind)
        if kind == "habit":
            for h in out:
                h["info"] = json.loads(h["extra"] or "{}")
                h["today"] = h["info"].get("last") == datetime.date.today().isoformat()
        if kind == "routine":
            for r in out:
                r["steps"] = json.loads(r["extra"] or "[]")
        return out

    def add_item(self, kind, text, minutes=None, steps=None):
        text = (text or "").strip()
        if kind not in ("memory", "task", "reminder", "habit", "routine") or not text:
            return {"error": "Preencha o texto."}
        if kind == "reminder":
            self.store.add(kind, text, due=time.time() + 60 * float(minutes or 5))
        elif kind == "habit":
            self.store.add(kind, text, extra=json.dumps({"streak": 0, "last": ""}))
        elif kind == "routine":
            st = [s.strip() for s in re.split(r"[;\n]", steps or "") if s.strip()]
            self.store.add(kind, text, extra=json.dumps(st, ensure_ascii=False))
        else:
            self.store.add(kind, text)
        return {"ok": True}

    def toggle_item(self, id):
        it = self.store.get(id)
        if it:
            self.store.update(id, done=0 if it["done"] else 1)
        return {"ok": True}

    def del_item(self, id):
        self.store.delete(id)
        return {"ok": True}

    def habit_done(self, id):
        h = self.store.get(id)
        if not h:
            return "Hábito não encontrado."
        info = json.loads(h["extra"] or "{}")
        today = datetime.date.today()
        if info.get("last") != today.isoformat():
            yest = (today - datetime.timedelta(days=1)).isoformat()
            info["streak"] = info.get("streak", 0) + 1 if info.get("last") == yest else 1
            info["last"] = today.isoformat()
            self.store.update(id, extra=json.dumps(info))
        return f"Marcado! {h['text']}: {info['streak']} dia(s) seguido(s)."

    def run_routine(self, id):
        r = self.store.get(id)
        if not r:
            return {"reply": "Rotina não encontrada."}
        return {"reply": self.cmd.run(r["text"]) or "Nada a executar."}

    # ---------- spotify
    def spotify_state(self):
        return self.now.snapshot()

    def spotify_cmd(self, action="", value=None):
        if not action:
            return {"ok": False, "error": "ação vazia"}
        return {"ok": self.now.cmd(action, value)}

    # ---------- timers, mídia, PC
    def timers(self):
        return self.engine.list_timers()

    def add_timer(self, minutes, label=""):
        self.engine.add_timer(int(float(minutes) * 60), label)
        return {"ok": True}

    def cancel_timer(self, id):
        self.engine.cancel(int(id))
        return {"ok": True}

    def media(self, action):
        if action in ("play", "next", "prev", "mute"):
            return {"ok": key(action)}
        return {"ok": False}

    def volume(self, level):
        return {"ok": set_volume(level)}

    def sysinfo(self):
        return MACHINE.snapshot()

    # ---------- cérebro
    def brain_info(self):
        out = []
        for pid in ORDER:
            p = PROVIDERS[pid]
            c = self.cfg.get("providers", {}).get(pid, {})
            k = c.get("key", "")
            out.append({"id": pid, "label": p["label"], "free": p["free"], "link": p["link"], "note": p["note"],
                        "nokey": bool(p.get("nokey")), "model": c.get("model") or p["model"],
                        "on": bool(c.get("on")), "has_key": bool(k), "tail": k[-4:] if k else ""})
        return {"providers": out, "mode": self.cfg.get("mode"), "status": self.brain.status()}

    def set_provider(self, id, key="", model="", on=None):
        if id not in PROVIDERS:
            return {"error": "IA desconhecida."}
        provs = self.cfg.get("providers", {})
        c = provs.setdefault(id, {})
        if key.strip():
            c["key"] = key.strip()
            if on is None:
                on = True
        if model.strip():
            c["model"] = model.strip()
        if on is not None:
            c["on"] = bool(on)
        self.cfg.set("providers", provs)
        return {"ok": True}

    def set_mode(self, mode):
        self.cfg.set("mode", mode if mode == "auto" or mode in PROVIDERS else "auto")
        return {"ok": True}

    def test_provider(self, id):
        try:
            txt, _ = self.brain.ask([{"role": "user", "content": "Responda apenas: ok"}], only=id)
            return {"ok": True, "text": txt[:80]}
        except BrainError as e:
            return {"ok": False, "text": str(e)[:220]}

    # ---------- ajustes e voz
    def set_setting(self, key, value):
        if key not in ("user", "voice_reply", "wake", "clip"):
            return {"error": "Ajuste inválido."}
        self.cfg.set(key, value)
        if key == "wake" and value:
            self._start_wake()
        if key == "voice_reply" and not value:
            voice.stop()
        return {"ok": True}

    def voice_info(self):
        d = voice.info()
        d["enabled"] = bool(self.cfg.get("voice_reply"))
        return d

    def set_voice(self, voice_name=None, rate=None):
        if voice_name and voice_name not in {v["id"] for v in voice.VOICES}:
            return {"error": "Voz desconhecida."}
        voice.configure(voice_name, rate)
        d = voice.info()
        self.cfg.d["voice"] = d["voice"]
        self.cfg.d["voice_rate"] = d["rate"]
        self.cfg.save()
        return {"ok": True, **d}

    def test_voice(self, text=None):
        voice.speak(text or f"Oi {self.name}. É assim que eu falo agora.")
        return {"ok": True}

    def stop_voice(self):
        voice.stop()
        return {"ok": True}

    def listen(self):
        try:
            return {"text": voice.listen_once()}
        except voice.Skip:
            return {"error": "Não ouvi nada. Tente de novo."}
        except Exception as e:
            return {"error": str(e)}

    def _start_wake(self):
        if self._wake and self._wake.is_alive():
            return
        self._wake = threading.Thread(target=self._wake_loop, daemon=True)
        self._wake.start()

    def _wake_loop(self):
        while self.cfg.get("wake"):
            try:
                txt = voice.listen_once(timeout=4, limit=7)
            except voice.Skip:
                continue
            except Exception as e:
                self.engine.push(type="alert", text=f"Voz desligada: {e}")
                self.cfg.set("wake", False)
                return
            if "jarvis" not in fold(txt) and "sexta" not in fold(txt):
                continue
            cmd = re.sub(r"^.*?(?:jarvis|sexta[ -]?feira)[ ,]*", "", txt, flags=re.I | re.S).strip()
            if not cmd:
                voice.speak("Pois não?")
                try:
                    cmd = voice.listen_once(timeout=5, limit=10)
                except Exception:
                    continue
            res = self.chat(cmd, speak=True)
            self.engine.push(type="chat", user=cmd, reply=res["reply"], via=res["via"])


API = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def page(self, name):
        html = (UI / name).read_text("utf-8").replace("__TOKEN__", TOKEN)
        return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    CORS = {"Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Private-Network": "true"}

    def do_OPTIONS(self):
        self.send(204, b"", "text/plain", self.CORS)

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, b"", "text/plain")
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self.page("index.html")
        if p == "/mini":
            return self.page("mini.html")
        if p == "/art":
            art = DATA / "art.jpg"
            if art.exists():
                return self.send(200, art.read_bytes(), "image/jpeg")
            return self.send(404, b"", "text/plain")
        if p == "/spicetify/ping":
            return self.send(200, b'{"ok":true,"name":"jarvis"}', "application/json; charset=utf-8", self.CORS)
        if p == "/spicetify/next":
            body = json.dumps({"cmds": API.spotify.take()}, ensure_ascii=False).encode("utf-8")
            return self.send(200, body, "application/json; charset=utf-8", self.CORS)
        if p == "/spicetify/state":
            return self.send(200, json.dumps(API.now.snapshot()).encode("utf-8"),
                             "application/json; charset=utf-8", self.CORS)
        self.send(404, b"", "text/plain")

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8", errors="replace") or "{}")

    def do_POST(self):
        if not self.host_ok():
            return self.send(403, b"", "text/plain")
        if self.path.startswith("/spicetify/state"):
            try:
                data = self.read_json()
                API.spotify.update(data)
                out = {"ok": True}
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            return self.send(200, json.dumps(out).encode("utf-8"), "application/json; charset=utf-8", self.CORS)
        if self.path.startswith("/spicetify/ack"):
            try:
                out = {"ok": API.spotify.ack(self.read_json())}
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            return self.send(200, json.dumps(out).encode("utf-8"), "application/json; charset=utf-8", self.CORS)
        if self.headers.get("X-Token") != TOKEN:
            return self.send(403, b"", "text/plain")
        name = self.path.removeprefix("/api/")
        try:
            args = self.read_json()
            if name not in Api.PUBLIC:
                raise ValueError("método inválido")
            out = getattr(API, name)(**args)
        except Exception as e:
            out = {"error": f"{type(e).__name__}: {e}"}
        self.send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")


def _screen():
    try:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def main():
    global API, PORT, MAIN_WIN, MINI_WIN, HOTKEYS
    API = Api()
    srv = None
    forced = [int(a) for a in sys.argv[1:] if a.isdigit()]
    for port in forced or PORTS:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        print("Nenhuma porta livre em 8765-8775. Feche outra instância do Jarvis.")
        return
    PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    view = ""
    if "--view" in sys.argv:
        try:
            view = "#" + sys.argv[sys.argv.index("--view") + 1].strip().lstrip("#")
        except IndexError:
            view = ""
    url = f"http://127.0.0.1:{PORT}/" + view
    print(f"Jarvis rodando em {url}")

    if "--no-window" in sys.argv:
        while True:
            time.sleep(3600)

    sw, sh = _screen()
    mw, mh = 360, 108
    hk = (API.cfg.get("hotkeys") or {})
    try:
        import webview
        MAIN_WIN = webview.create_window("Jarvis", url, width=1180, height=760, min_size=(900, 600),
                                         background_color="#000000", text_select=True)
        try:
            MINI_WIN = webview.create_window("Jarvis", url + "mini", width=mw, height=mh,
                                             x=sw - mw - 40, y=sh - mh - 80, frameless=True, on_top=True,
                                             resizable=False, hidden=True, draggable=True, shadow=True,
                                             background_color="#000000")
        except TypeError:
            MINI_WIN = None
        HOTKEYS = Hotkeys([
            {"spec": hk.get("mini", "ctrl+alt+j"), "cb": toggle_mini},
            {"spec": hk.get("focus", "ctrl+alt+space"), "cb": focus_main},
        ])
        HOTKEYS.start()
        webview.start()
    except ImportError:
        print("pywebview não instalado; abrindo no navegador (pip install pywebview para janela própria).")
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
