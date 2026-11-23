"""Estado real do Spotify, com três fontes em ordem de prioridade.

1. Extensão Spicetify (`spotify.py`) — mais rica: volume, busca e play por URI.
2. Windows SMTC (`winrt`) — o mesmo "tocando agora" que o Windows mostra.
   Funciona sem instalar nada no Spotify: lê faixa, capa, progresso e controla.
3. Título da janela do spotify.exe — último recurso, só faixa e artista.

O problema da versão anterior era depender só da fonte 1: sem a extensão
instalada, o Jarvis não tinha olhos no player e anunciava "offline" com o
Spotify tocando. Agora há sempre uma fonte viva enquanto o Spotify existir.
"""
import asyncio, ctypes, ctypes.wintypes as wt, hashlib, queue, threading, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ART = DATA / "art.jpg"

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING


# ------------------------------------------------------------------ SMTC (WinRT)
class Smtc:
    """Sessão de mídia do Windows. Precisa dos pacotes winrt-* (requirements)."""

    def __init__(self):
        self.state = None
        self.art_key = ""
        self.loop = None
        self.ready = False
        self.error = ""
        self.cmds = queue.Queue()
        self._art_hash = ""
        threading.Thread(target=self._thread, daemon=True, name="smtc").start()

    def _thread(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"

    async def _main(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )
        self.loop = asyncio.get_running_loop()
        self.mgr = await SessionManager.request_async()
        self.ready = True
        while True:
            try:
                await self._poll()
                self._drain()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self.state = None
            await asyncio.sleep(0.7)

    def _pick(self):
        best = None
        try:
            sessions = list(self.mgr.get_sessions() or [])
        except Exception:
            sessions = []
        for s in sessions:
            try:
                app = (s.source_app_user_model_id or "").lower()
            except Exception:
                continue
            if "spotify" not in app:
                continue
            try:
                playing = int(s.get_playback_info().playback_status) == PLAYING
            except Exception:
                playing = False
            if playing:
                return s
            best = best or s
        return best

    async def _poll(self):
        s = self._pick()
        if s is None:
            self.state = None
            return
        info = await s.try_get_media_properties_async()
        tl = s.get_timeline_properties()
        pb = s.get_playback_info()
        playing = int(pb.playback_status) == PLAYING
        pos = tl.position.total_seconds() if tl else 0.0
        end = tl.end_time.total_seconds() if tl else 0.0
        # O SMTC atualiza a posição em blocos de ~4 s. last_updated_time diz
        # quanto tempo passou desde o último bloco: somar isso dá o segundo exato.
        try:
            upd = tl.last_updated_time if tl else None
            if upd is not None and playing:
                if upd.tzinfo is None:
                    upd = upd.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - upd).total_seconds()
                if 0 < age < 60:
                    pos += age
        except Exception:
            pass
        if end > 0:
            pos = min(pos, end)
        self.state = {
            "playing": playing,
            "title": (info.title or "") if info else "",
            "artist": (info.artist or "") if info else "",
            "album": (info.album_title or "") if info else "",
            "position": max(0.0, pos),
            "duration": max(0.0, end),
            "volume": None,
            "shuffle": None,
            "repeat": None,
        }
        try:
            if info and info.thumbnail:
                await self._save_art(info.thumbnail)
        except Exception:
            pass

    async def _save_art(self, ref):
        stream = await ref.open_read_async()
        size = int(stream.size or 0)
        if size <= 0 or size > 8_000_000:
            return
        from winrt.windows.storage.streams import DataReader
        reader = DataReader(stream)
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        data = bytes(buf)
        h = hashlib.sha1(data).hexdigest()[:10]
        if h == self._art_hash:
            return
        DATA.mkdir(exist_ok=True)
        ART.write_bytes(data)
        self._art_hash = h
        self.art_key = h

    def _drain(self):
        s = self._pick()
        while True:
            try:
                action, value = self.cmds.get_nowait()
            except queue.Empty:
                return
            if s is None:
                continue
            coro = self._act(s, action, value)
            if coro is not None:
                asyncio.ensure_future(coro)

    async def _act(self, s, action, value):
        try:
            if action == "toggle":
                await s.try_toggle_play_pause_async()
            elif action == "play":
                await s.try_play_async()
            elif action == "pause":
                await s.try_pause_async()
            elif action == "next":
                await s.try_skip_next_async()
            elif action == "prev":
                await s.try_skip_previous_async()
            elif action == "seek" and value is not None:
                from datetime import timedelta
                await s.try_change_playback_position_async(timedelta(seconds=float(value)))
            elif action == "shuffle":
                await s.try_change_shuffle_active_async(True)
        except Exception:
            pass
        await self._poll()

    def cmd(self, action, value=None):
        if not self.ready or not self.state:
            return False
        self.cmds.put((action, value))
        if action == "play":
            self.state["playing"] = True
        elif action == "pause":
            self.state["playing"] = False
        elif action == "toggle":
            self.state["playing"] = not self.state.get("playing")
        return True

    def snapshot(self):
        st = self.state
        if not st:
            return None
        d = dict(st)
        d["source"] = "windows"
        d["at"] = time.time()
        d["art"] = f"/art?v={self.art_key}" if self.art_key else ""
        return d


# ------------------------------------------------------------------ janela (último recurso)
class SpotifyWindow:
    """Lê 'Artista - Faixa' do título da janela do Spotify. Sem progresso, sem controle."""

    def __init__(self):
        self.state = None

    def poll(self):
        title = self._title()
        if not title:
            self.state = None
            return
        parts = [p.strip() for p in title.split(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            artist, song = parts
        else:
            artist, song = "", title
        if song.lower() in ("spotify", "spotify premium", "spotify free", ""):
            self.state = None
            return
        self.state = {
            "playing": None,
            "title": song,
            "artist": artist,
            "album": "",
            "position": 0.0,
            "duration": 0.0,
            "volume": None,
            "source": "janela",
        }

    @staticmethod
    def _title():
        user32 = ctypes.windll.user32
        out = []

        def cb(hwnd, _):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                import psutil
                name = psutil.Process(pid.value).name().lower()
            except Exception:
                return True
            if name.startswith("spotify"):
                n = user32.GetWindowTextLengthW(hwnd)
                if n > 0:
                    b = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, b, n + 1)
                    if b.value:
                        out.append(b.value)
            return True

        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        user32.EnumWindows(CB(cb), 0)
        return out[0] if out else ""


# ------------------------------------------------------------------ fachada
class NowPlaying:
    """Uma única verdade sobre o Spotify, consumida por API, mini player e agente."""

    def __init__(self, bridge=None, volume_setter=None):
        self.bridge = bridge
        self.volume_setter = volume_setter
        self.last_error = ""
        self.smtc = Smtc()
        self.window = SpotifyWindow()
        self._win_at = 0.0
        threading.Thread(target=self._loop, daemon=True, name="nowplaying").start()

    def _loop(self):
        while True:
            if time.time() - self._win_at > 1.5:
                self._win_at = time.time()
                try:
                    self.window.poll()
                except Exception:
                    self.window.state = None
            time.sleep(0.5)

    # ---------------- leitura
    def snapshot(self):
        now = time.time()
        if self.bridge is not None and self.bridge.online():
            d = self.bridge.snapshot()
            d["source"] = "spicetify"
            d["at"] = now
            d["position"] = (d.get("position") or 0) / 1000.0
            d["duration"] = (d.get("duration") or 0) / 1000.0
            # Compatibilidade: extensões antigas mandam a capa como URI do Spotify.
            art = d.get("art") or ""
            if art.startswith("spotify:image:"):
                art = "https://i.scdn.co/image/" + art[len("spotify:image:"):]
            d["art"] = art
            d["online"] = True
            return d
        d = self.smtc.snapshot()
        if d:
            d["online"] = True
            return d
        w = self.window.state
        if w:
            d = dict(w)
            d["online"] = True
            d["at"] = now
            d["art"] = ""
            return d
        return {"online": False, "source": None, "playing": False, "title": "", "artist": "",
                "album": "", "position": 0.0, "duration": 0.0, "volume": None, "art": "", "at": now}

    def online(self):
        return self.snapshot().get("online", False)

    # ---------------- controle
    SMTC_ACTIONS = {"toggle", "play", "pause", "next", "prev", "seek", "shuffle"}

    def cmd(self, action, value=None):
        if self.bridge is not None and self.bridge.online():
            cid = self.bridge.cmd(action, value=value)
            if not cid:
                self.last_error = "a extensão não aceitou o comando"
                return False
            if action == "play_query":
                res = self.bridge.wait(cid, 4.0)
                if res is None:
                    self.last_error = "a extensão não confirmou a busca"
                    return False
                self.last_error = res.get("error", "")
                return res["ok"]
            return True
        if action == "volume":
            if self.volume_setter and value is not None:
                try:
                    v = float(value)
                    self.volume_setter(v * 100 if v <= 1 else v)
                    return True
                except Exception:
                    return False
            return False
        if action in self.SMTC_ACTIONS and self.smtc.state is not None:
            return self.smtc.cmd(action, value)
        # sem fonte com controle: teclas de mídia do Windows
        try:
            from commands import key
            mapped = {"toggle": "play", "play": "play", "pause": "play",
                      "next": "next", "prev": "prev"}.get(action)
            return key(mapped) if mapped else False
        except Exception:
            return False
