"""Comandos locais: resolvem pedidos simples sem gastar IA (rápido, grátis e offline)."""
import re, os, sys, time, json, datetime, subprocess, unicodedata, urllib.parse, webbrowser

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
NUM = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
       "oito": 8, "nove": 9, "dez": 10, "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40, "meia": 0.5}
UNIT = {"s": 1, "seg": 1, "segundo": 1, "segundos": 1, "min": 60, "minuto": 60, "minutos": 60,
        "h": 3600, "hora": 3600, "horas": 3600}
DUR = r"(\d+|" + "|".join(NUM) + r")\s*(segundos?|minutos?|horas?|min|seg|h)\b"

APPS = {
    "spotify": "spotify:", "chrome": "chrome", "google chrome": "chrome", "whatsapp": "whatsapp:",
    "calculadora": "calc", "bloco de notas": "notepad", "notepad": "notepad", "explorador": "explorer",
    "explorador de arquivos": "explorer", "discord": "discord:", "vscode": "code", "vs code": "code",
    "terminal": "wt", "cmd": "cmd", "paint": "mspaint", "configuracoes": "ms-settings:",
    "youtube": "https://youtube.com", "google": "https://google.com", "gmail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com", "gemini": "https://gemini.google.com",
    "deepseek": "https://chat.deepseek.com", "claude": "https://claude.ai", "github": "https://github.com",
}
VK = dict(play=0xB3, next=0xB0, prev=0xB1, mute=0xAD, down=0xAE, up=0xAF)


def fold(s):  # minúsculo e sem acento, mantendo o mesmo tamanho do texto
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def key(name, n=1):
    if sys.platform != "win32":
        return False
    import ctypes
    u = ctypes.windll.user32
    for _ in range(n):
        u.keybd_event(VK[name], 0, 0, 0)
        u.keybd_event(VK[name], 0, 2, 0)
    return True


def set_volume(level):
    """Volume exato via pycaw quando disponível; senão, teclas (aproximado)."""
    level = max(0, min(100, int(level)))
    try:
        from pycaw.pycaw import AudioUtilities
        from comtypes import CLSCTX_ALL
        from ctypes import cast, POINTER
        from pycaw.pycaw import IAudioEndpointVolume
        dev = AudioUtilities.GetSpeakers()
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(level / 100, None)
        return True
    except Exception:
        pass
    ok = key("down", 50)
    key("up", level // 2)
    return ok


def opener(target):
    if target.startswith("http"):
        webbrowser.open(target)
    elif sys.platform == "win32":
        os.startfile(target)
    else:
        subprocess.Popen(["xdg-open", target])


def sysinfo():
    from sysinfo import MACHINE
    return MACHINE.snapshot()


def secs(m):
    n = m.group(1)
    n = float(n) if n.isdigit() else NUM[n]
    return int(n * UNIT[m.group(2)])


def when(t):
    """Acha 'em 10 minutos' ou 'às 18:30'. Devolve (timestamp, (início, fim)) ou (None, None)."""
    m = re.search(r"\bem " + DUR, t)
    if m:
        return time.time() + secs(m), m.span()
    m = re.search(r"\bas (\d{1,2})(?:[:h]?(\d{2}))?(?:h|\s*horas?)?\b", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h < 24 and mi < 60:
            d = datetime.datetime.now().replace(hour=h, minute=mi, second=0, microsecond=0)
            if d.timestamp() <= time.time():
                d += datetime.timedelta(days=1)
            return d.timestamp(), m.span()
    return None, None


class Commands:
    def __init__(self, api):
        self.a = api

    def routine(self, t):
        for r in self.a.store.list("routine"):
            n = fold(r["text"])
            if t in (n, "rotina " + n, "executa rotina " + n, "modo " + n, "ativa modo " + n, "ativa rotina " + n):
                return r

    def run(self, raw, depth=0):
        """Devolve a resposta (texto) ou None se não for um comando local."""
        a, n = self.a, self.a.name
        r = re.sub(r"\s+", " ", raw).strip(" .,!?;:")
        t = fold(r)
        m = re.match(r"(?:(?:ei|oi|ola|e ai|ok)[ ,]+)?(?:jarvis|sexta[ -]?feira)\b[ ,]*", t)
        if m:
            r, t = r[m.end():].strip(" .,!?;:"), t[m.end():].strip(" .,!?;:")
        G = lambda m, g=1: r[m.start(g):m.end(g)].strip()
        if not t:
            return f"Pois não, {n}?"

        rt = self.routine(t)
        if rt and depth < 2:
            steps = json.loads(rt["extra"] or "[]")
            for s in steps:
                self.run(s, depth + 1)
            return f"Rotina {rt['text']} executada, {n}."

        if re.search(r"que horas|horas sao|hora atual", t):
            return f"São {datetime.datetime.now():%H:%M}, {n}."
        if re.search(r"que dia (e )?hoje|data de hoje|qual a data", t):
            d = datetime.date.today()
            return f"Hoje é {DIAS[d.weekday()]}, {d:%d/%m/%Y}."

        # --- lembretes e timers
        if re.match(r"(?:me )?(?:lembra|lembre|avisa|avise)(?: me)?\b", t) and not re.match(r"lembra que", t):
            ts, sp = when(t)
            body = re.sub(r"^(?:me )?(?:lembra|lembre|avisa|avise)(?: me)?\s*(?:de |que |para )?", "",
                          (r[:sp[0]] + " " + r[sp[1]:]) if sp else r, flags=re.I).strip(" ,")
            body = re.sub(r"^(?:me )?(?:lembra|lembre|avisa|avise)(?: me)?\s*(?:de |que |para )?", "", body, flags=re.I)
            if not ts:
                return f"Quando devo te lembrar, {n}? Diga, por exemplo, \"em 10 minutos\" ou \"às 18:30\"."
            a.store.add("reminder", body or "Lembrete", due=ts)
            return f"Combinado, {n}. Lembrete para {datetime.datetime.fromtimestamp(ts):%H:%M}: {body or 'lembrete'}."
        m = re.match(r"(?:timer|cronometro|temporizador|alarme)\s*(?:de|para|em)?\s*" + DUR, t)
        if m:
            s = secs(m)
            a.engine.add_timer(s)
            return f"Timer de {s // 60} min {s % 60} s iniciado." if s % 60 else f"Timer de {s // 60} minutos iniciado."
        if re.match(r"(?:cancela|para|apaga) (?:os |todos os )?timers?", t):
            a.engine.cancel()
            return "Timers cancelados."

        # --- tarefas
        m = re.match(r"(?:adiciona|add|nova|criar|cria|anota)\s+(?:uma )?tarefa\s*(?:de |para |:)?\s*(.+)", t)
        if m:
            a.store.add("task", G(m))
            return f"Tarefa adicionada, {n}."
        if re.search(r"minhas tarefas|lista (?:de )?tarefas|quais (?:sao )?(?:as )?(?:minhas )?tarefas", t):
            ts = [x for x in a.store.list("task") if not x["done"]]
            return ("Suas tarefas abertas: " + "; ".join(x["text"] for x in ts) + ".") if ts else f"Nenhuma tarefa aberta, {n}."
        m = re.match(r"(?:conclui|concluir|finaliza|feito)\s+(?:a )?tarefa\s+(\d+)", t)
        if m:
            a.store.update(int(m.group(1)), done=1)
            return "Tarefa concluída."

        # --- hábitos
        m = re.match(r"(?:cria|criar|novo|adiciona)\s+(?:o )?habito\s+(?:de |:)?\s*(.+)", t)
        if m:
            a.store.add("habit", G(m), extra=json.dumps({"streak": 0, "last": ""}))
            return f"Hábito criado: {G(m)}."
        m = re.match(r"(?:fiz|marca|marcar|conclui)\s+(?:o )?habito\s+(?:de )?(.+)", t)
        if m:
            q = fold(G(m))
            for h in a.store.list("habit"):
                if q in fold(h["text"]):
                    return a.habit_done(h["id"])
            return "Não achei esse hábito."

        # --- memória
        m = re.match(r"(?:lembra|lembre) (?:que |de que )(.+)", t) or \
            re.match(r"(?:anota|guarda|memoriza|salva|grava)(?: isso)?[: ]+(?:que )?(.+)", t)
        if m:
            a.store.add("memory", G(m))
            return f"Guardei na memória, {n}."
        if re.search(r"o que (?:voce )?(?:sabe|lembra) (?:sobre|de) mim", t):
            ms = a.store.list("memory", 15)
            return ("Eu sei que: " + "; ".join(x["text"] for x in ms) + ".") if ms else "Ainda não sei nada sobre você. Diga \"lembra que...\"."
        m = re.search(r"o que (?:eu )?copiei|ultimo copiado", t)
        if m:
            cs = a.store.list("clip", 3)
            return ("Copiados recentes: " + " | ".join(c["text"][:80] for c in cs)) if cs else "O histórico de copiados está vazio ou desligado."

        # --- música e volume
        m = re.match(r"(?:toca|tocar|coloca|poe)\s+(.+?)(?:\s+no spotify)?$", t)
        if m and not re.match(r"(?:a )?(?:musica|faixa)$", m.group(1)):
            q = re.sub(r"\s+no spotify$", "", G(m), flags=re.I)
            if a.now.cmd("play_query", value=q):
                return f"Tocando \"{q}\" no Spotify."
            opener("spotify:search:" + urllib.parse.quote(q))
            return f"Abri a busca de \"{q}\" no Spotify. É só dar play."
        if re.search(r"que (?:musica|faixa) (?:esta )?tocando|o que (?:esta|ta) tocando|qual (?:e )?a musica", t):
            d = a.now.snapshot()
            if not d.get("online"):
                return "Não achei o Spotify aberto, " + n + "."
            if not d.get("title"):
                return "O Spotify está aberto, mas não está tocando nada."
            extra = f" — {d['artist']}" if d.get("artist") else ""
            return f"Tocando agora: {d['title']}{extra}."
        if re.match(r"(?:aleatorio|shuffle|modo aleatorio)", t):
            if a.now.cmd("shuffle"):
                return "Modo aleatório alternado."
        if re.match(r"(?:pausa|pausar|pause|para (?:a )?musica|continua|continuar|retoma|play|da play|toca)\b", t):
            if a.now.cmd("toggle"):
                return f"Feito, {n}."
            return f"Feito, {n}." if key("play") else "Controle de mídia só funciona no Windows."
        if re.match(r"(?:proxima|pula|passa)\b", t):
            if a.now.cmd("next"):
                return "Próxima."
            return "Próxima." if key("next") else "Controle de mídia só funciona no Windows."
        if re.match(r"(?:anterior|volta a musica|musica anterior)\b", t):
            return "Voltando." if key("prev") else "Controle de mídia só funciona no Windows."
        m = re.search(r"volume (?:para |em |no )?(\d{1,3})", t)
        if m:
            set_volume(m.group(1))
            return f"Volume em {min(100, int(m.group(1)))}%."
        if re.search(r"(?:aumenta|sobe|aumentar).*volume|volume.*(?:mais alto|sobe)", t):
            key("up", 5)
            return "Aumentei o volume."
        if re.search(r"(?:abaixa|diminui|baixa|reduz).*volume|volume.*(?:mais baixo|abaixa)", t):
            key("down", 5)
            return "Abaixei o volume."
        if re.match(r"(?:muta|mudo|silencia)", t):
            key("mute")
            return "Pronto."

        # --- abrir apps, pesquisar, PC
        m = re.match(r"(?:pesquisa|pesquisar|procura|busca)\s+(.+?)(?:\s+no (google|youtube))?$", t)
        if m:
            q = urllib.parse.quote(G(m))
            site = m.group(2) or "google"
            opener(f"https://www.youtube.com/results?search_query={q}" if site == "youtube"
                   else f"https://www.google.com/search?q={q}")
            return f"Pesquisando \"{G(m)}\" no {site.capitalize()}."
        m = re.match(r"(?:abre|abra|abrir|inicia|iniciar|executa)\s+(?:o |a |os |as )?(.+)", t)
        if m:
            name = G(m).lower()
            apps = {**APPS, **{fold(k): v for k, v in a.cfg.get("apps", {}).items()}}
            if fold(name) in apps:
                try:
                    opener(apps[fold(name)])
                    return f"Abrindo {name}, {n}."
                except Exception as e:
                    return f"Não consegui abrir {name}: {e}"
            return f"Não conheço o app \"{name}\". Você pode adicioná-lo em data/config.json, na chave \"apps\"."
        if re.search(r"como esta (?:o )?(?:meu )?(?:pc|computador)|status do (?:pc|computador)|uso de (?:cpu|memoria)", t):
            i = sysinfo()
            if not i or i.get("error"):
                return "Instale o psutil (pip install psutil) para eu ver o PC."
            nome = (i.get("processor") or {}).get("name") or ""
            up = (i.get("system") or {}).get("uptime") or 0
            top = ((i.get("processes") or {}).get("by_cpu") or [{}])[0].get("name")
            txt = f"CPU em {i['cpu']:.0f}%" + (f" ({nome})" if nome else "")
            txt += f", RAM em {i['ram']:.0f}% ({i['ram_gb']} de {i['ram_total']} GB) e disco em {i['disk']:.0f}%."
            if up:
                dias, horas = up // 86400, up % 86400 // 3600
                txt += f" Ligado há {dias} dia(s) e {horas}h." if dias else f" Ligado há {horas}h."
            if top:
                txt += f" Quem mais pesa na CPU agora: {top}."
            return txt
        if re.search(r"qual (?:e )?(?:o |a )?(?:processador|cpu|placa de video|gpu|memoria|ram)", t):
            i = sysinfo()
            if not i or i.get("error"):
                return "Instale o psutil (pip install psutil) para eu ver o PC."
            p, m = i["processor"], i["memory"]
            gpus = i.get("graphics") or []
            txt = f"{p['name']}, {p['cores']} núcleos e {p['threads']} threads, a {p['freq']/1000:.1f} GHz."
            txt += f" {m['total_gb']:.0f} GB de RAM ({m['used_gb']:.1f} GB em uso)."
            if gpus:
                txt += " Placa de vídeo: " + ", ".join(g["name"] for g in gpus[:2]) + "."
            return txt
        if re.match(r"(?:bloqueia|trava)\s+(?:o |a )?(?:pc|computador|tela)", t):
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return "Bloqueando."
            return "Só funciona no Windows."
        if re.fullmatch(r"(?:obrigad[oa]|valeu|brigado)", t):
            return f"Sempre às ordens, {n}."
        return None
