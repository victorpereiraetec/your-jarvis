"""Voz: ouvir pelo microfone e falar as respostas.

A fala usa as vozes neurais do Edge (edge-tts) — as mesmas do "Ler em voz alta"
do navegador, bem mais naturais que a voz padrão do Windows. Se não houver
internet ou o pacote faltar, cai para o SAPI local (pyttsx3) sem quebrar nada.

Só é usada na conversa: respostas do chat e quando você chama "Jarvis".
"""
import asyncio, os, queue, re, tempfile, threading, time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# Vozes pt disponíveis no edge-tts, com nome amigável para a interface.
VOICES = [
    {"id": "pt-BR-AntonioNeural", "name": "Antônio", "note": "Brasil · masculina · natural", "gender": "m"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca", "note": "Brasil · feminina · natural", "gender": "f"},
    {"id": "pt-BR-ThalitaMultilingualNeural", "name": "Thalita", "note": "Brasil · feminina · multilíngue", "gender": "f"},
    {"id": "pt-PT-DuarteNeural", "name": "Duarte", "note": "Portugal · masculina", "gender": "m"},
    {"id": "pt-PT-RaquelNeural", "name": "Raquel", "note": "Portugal · feminina", "gender": "f"},
]

_CFG = {"voice": "pt-BR-AntonioNeural", "rate": 8}
_q = queue.Queue()
_lock = threading.Lock()
_started = False
_gen = [0]                      # muda a cada fala nova; fala antiga para de tocar
_state = {"speaking": False, "engine": "", "text": ""}


class Skip(Exception):
    """Não entendeu nada / silêncio."""


# ---------------------------------------------------------------- ajustes
def configure(voice_name=None, rate=None):
    """Define a voz e a velocidade (rate em %, -50 a +50)."""
    if voice_name:
        _CFG["voice"] = str(voice_name)
    if rate is not None:
        try:
            _CFG["rate"] = max(-50, min(50, int(rate)))
        except (TypeError, ValueError):
            pass


def info():
    edge = mixer = True
    try:
        import edge_tts  # noqa: F401
    except Exception:
        edge = False
    try:
        import pygame  # noqa: F401
    except Exception:
        mixer = False
    engine = _state["engine"] or ("edge-tts" if edge and mixer else "sapi")
    return {"voice": _CFG["voice"], "rate": _CFG["rate"], "engine": engine,
            "edge": bool(edge and mixer), "speaking": _state["speaking"], "voices": VOICES}


# ---------------------------------------------------------------- falar
def speak(text):
    """Enfileira uma fala. Uma fala nova interrompe a anterior."""
    text = _clean(text)
    if not text:
        return
    _ensure_worker()
    _gen[0] += 1
    _stop_audio()
    while True:
        try:
            _q.get_nowait()
        except queue.Empty:
            break
    _q.put((text, _gen[0]))


def stop():
    """Cala a boca do Jarvis agora."""
    _gen[0] += 1
    _stop_audio()
    while True:
        try:
            _q.get_nowait()
        except queue.Empty:
            break
    _state["speaking"] = False


def _ensure_worker():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, daemon=True, name="voice").start()


def _worker():
    while True:
        text, gen = _q.get()
        if gen != _gen[0]:
            continue
        try:
            _say(text, gen)
        except Exception:
            pass


def _say(text, gen):
    _state["speaking"] = True
    _state["text"] = text[:120]
    try:
        for chunk in _chunks(text):
            if gen != _gen[0]:
                return
            if _edge(chunk, gen):
                continue
            _sapi(chunk)
            return
    finally:
        if gen == _gen[0]:
            _state["speaking"] = False


def _edge(text, gen):
    """Gera o mp3 com voz neural e toca. False = deixa o SAPI tentar."""
    try:
        import edge_tts
    except Exception:
        return False
    path = tempfile.mktemp(prefix="jarvis-", suffix=".mp3")
    try:
        asyncio.run(edge_tts.Communicate(text, _CFG["voice"],
                                         rate=f"{_CFG['rate']:+d}%").save(path))
        if not os.path.getsize(path):
            return False
        if _play(path, gen):
            _state["engine"] = "edge-tts"
            return True
        return False
    except Exception:
        return False
    finally:
        for _ in range(4):
            try:
                os.remove(path)
                break
            except OSError:
                time.sleep(0.05)


def _play(path, gen):
    try:
        import pygame
    except Exception:
        return False
    with _lock:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.stop()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception:
            return False
    t0 = time.time()
    while pygame.mixer.music.get_busy():
        if gen != _gen[0] or time.time() - t0 > 180:
            _stop_audio()
            return True
        time.sleep(0.04)
    return True


def _stop_audio():
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def _sapi(text):
    """Plano B offline: voz do próprio Windows (robótica, mas funciona)."""
    try:
        import pyttsx3
    except Exception:
        return
    try:
        eng = pyttsx3.init()
        for v in eng.getProperty("voices"):
            s = (v.name + " " + str(v.languages)).lower()
            if "pt-br" in s or "brazil" in s or "maria" in s or "portugu" in s:
                eng.setProperty("voice", v.id)
                break
        eng.setProperty("rate", 180)
        eng.say(text)
        eng.runAndWait()
        _state["engine"] = "sapi"
    except Exception:
        pass


# ---------------------------------------------------------------- texto
def _clean(text):
    """Tira markdown/código/URLs para não ler asteriscos em voz alta."""
    t = str(text or "")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"(?<!\w)[*_~#>]+|[*_~#]+(?!\w)", "", t)
    t = re.sub(r"https?://\S+", "link", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _chunks(text, limit=600):
    """Divide respostas longas em pedaços faláveis."""
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for s in re.split(r"(?<=[.!?…])\s+", text):
        if buf and len(buf) + len(s) + 1 > limit:
            parts.append(buf)
            buf = s
        else:
            buf = (buf + " " + s).strip()
    if buf:
        parts.append(buf)
    return parts or [text]


# ---------------------------------------------------------------- ouvir
def listen_once(timeout=6, limit=10):
    try:
        import speech_recognition as sr
    except ImportError:
        raise RuntimeError("Instale a voz: pip install SpeechRecognition PyAudio edge-tts pygame")
    rec = sr.Recognizer()
    try:
        with sr.Microphone() as src:
            rec.adjust_for_ambient_noise(src, 0.3)
            audio = rec.listen(src, timeout=timeout, phrase_time_limit=limit)
        return rec.recognize_google(audio, language="pt-BR")
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        raise Skip()
    except sr.RequestError as e:
        raise RuntimeError(f"Reconhecimento de voz indisponível: {e}")
