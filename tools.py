"""Ferramentas que o Jarvis executa de verdade na máquina.

Acesso total ao PC é decisão do dono da máquina: este módulo não pede permissão,
mas registra cada chamada em data/agent.log (ferramenta, argumentos, resultado).
Cada ferramenta recebe (api, args) e devolve texto curto — o que o modelo lê de volta.
"""
import datetime, json, re, subprocess, sys, time, webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
AUDIT = DATA / "agent.log"
MAX_OUT = 3500
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

TOOLS = {}
SCHEMAS = {}


def tool(name, args, desc):
    """Registra uma ferramenta. args = {nome: 'tipo (opcional|obrigatório)'}."""
    def deco(fn):
        TOOLS[name] = fn
        SCHEMAS[name] = {"args": args, "desc": desc}
        return fn
    return deco


def catalog():
    """Lista compacta para o prompt do modelo."""
    out = []
    for name, s in SCHEMAS.items():
        a = ", ".join(f"{k}: {v}" for k, v in s["args"].items())
        out.append(f"- {name}({a}) — {s['desc']}")
    return "\n".join(out)


def _clip(s, n=MAX_OUT):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n[... corte: {len(s)} caracteres no total]"


def _audit(name, args, out):
    try:
        DATA.mkdir(exist_ok=True)
        line = (f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{name}\t"
                f"{json.dumps(args, ensure_ascii=False)[:500]}\t"
                f"{str(out)[:500].replace(chr(10), ' ').replace(chr(9), ' ')}\n")
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def run(name, api, args):
    """Executa uma ferramenta pelo nome. Devolve texto — nunca levanta."""
    fn = TOOLS.get(name)
    if not fn:
        return f"Ferramenta desconhecida: {name}. Disponíveis: {', '.join(TOOLS)}."
    try:
        out = fn(api, args or {})
    except subprocess.TimeoutExpired:
        out = "Erro: o comando passou do tempo limite e foi encerrado."
    except Exception as e:
        out = f"Erro em {name}: {type(e).__name__}: {e}"
    out = _clip(out)
    _audit(name, args or {}, out)
    return out


# ---------------------------------------------------------------- sistema

@tool("run_shell", {"command": "string (PowerShell, obrigatório)", "timeout": "int 1-300 (opcional, padrão 60)"},
      "Executa um comando PowerShell e devolve stdout/stderr/exit code. Acesso total ao PC.")
def run_shell(api, a):
    cmd = str(a.get("command") or "").strip()
    if not cmd:
        return "Erro: comando vazio."
    timeout = max(1, min(300, int(a.get("timeout") or 60)))
    full = "$ErrorActionPreference='Continue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + cmd
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", full],
                       cwd=str(Path.home()), capture_output=True, timeout=timeout,
                       creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    out = p.stdout or ""
    if (p.stderr or "").strip():
        out += "\n[stderr]\n" + p.stderr
    return f"exit={p.returncode}\n{out.strip() or '(sem saída)'}"


@tool("sysinfo", {}, "A máquina inteira: CPU, RAM, discos, GPU, rede, bateria e processos.")
def t_sysinfo(api, a):
    d = api.sysinfo()
    if d.get("error"):
        return d["error"]
    p, m, s = d["processor"], d["memory"], d["system"]
    top = (d["processes"]["by_cpu"] or [{}])[0].get("name")
    disks = "; ".join(f"{x['mount']} {x['percent']:.0f}%" for x in d["storage"]["disks"])
    bits = [f"{p['name']} · {p['cores']}n/{p['threads']}t · CPU {p['usage']:.0f}%",
            f"RAM {m['percent']:.0f}% ({m['used_gb']:.1f}/{m['total_gb']:.1f} GB)",
            f"discos: {disks}" if disks else "",
            f"rede ↓{d['network']['down']:.1f} ↑{d['network']['up']:.1f} MB/s",
            f"ligado há {s['uptime'] // 3600}h"]
    if d.get("battery_info"):
        bits.append(f"bateria {d['battery_info']['percent']:.0f}%")
    if top:
        bits.append(f"mais CPU: {top}")
    return " · ".join(b for b in bits if b)


@tool("lock_pc", {}, "Bloqueia a sessão do Windows.")
def t_lock(api, a):
    if sys.platform != "win32":
        return "Só Windows."
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "PC bloqueado."


@tool("notify", {"text": "string (obrigatório)"}, "Mostra um aviso na janela do Jarvis e fala se a voz estiver ativa.")
def t_notify(api, a):
    text = str(a.get("text") or "").strip()
    if not text:
        return "Erro: texto vazio."
    api.engine.alert(text)
    return "Aviso exibido."


@tool("screenshot", {"path": "string (opcional; padrão data/tela.png)"},
      "Salva um print da tela inteira em arquivo. Precisa de Pillow.")
def t_shot(api, a):
    path = Path(a.get("path") or (DATA / "tela.png"))
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Pillow não instalado (pip install pillow)."
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab().save(path)
    return f"Print salvo em {path}"


# ---------------------------------------------------------------- apps e janelas

@tool("open_app", {"target": "string — nome conhecido (spotify, chrome, vscode…) ou caminho/URL"},
      "Abre um app, arquivo ou URL no PC.")
def t_open_app(api, a):
    from commands import APPS, fold, opener
    target = str(a.get("target") or "").strip()
    if not target:
        return "Erro: alvo vazio."
    apps = {**APPS, **{fold(k): v for k, v in (api.cfg.get("apps") or {}).items()}}
    hit = apps.get(fold(target)) or apps.get(fold(Path(target).stem))
    try:
        opener(hit or target)
        return f"Aberto: {target}"
    except Exception as e:
        return f"Não consegui abrir {target}: {e}"


@tool("open_url", {"url": "string (obrigatório)"}, "Abre uma URL no navegador padrão.")
def t_open_url(api, a):
    url = str(a.get("url") or "").strip()
    if not url:
        return "Erro: URL vazia."
    if not re.match(r"^https?://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"Aberto: {url}"


# ---------------------------------------------------------------- arquivos e web

def _resolve(path):
    p = Path(str(path)).expanduser()
    return p if p.is_absolute() else (Path.home() / p)


@tool("read_file", {"path": "string (obrigatório)", "max_chars": "int (opcional, padrão 20000)"},
      "Lê um arquivo de texto e devolve o conteúdo.")
def t_read(api, a):
    p = _resolve(a.get("path") or "")
    if not p.is_file():
        return f"Arquivo não encontrado: {p}"
    n = max(200, min(60000, int(a.get("max_chars") or 20000)))
    txt = p.read_text(encoding="utf-8", errors="replace")
    head = txt[:n]
    return head + (f"\n[... corte: {len(txt)} caracteres no total]" if len(txt) > n else "")


@tool("write_file", {"path": "string (obrigatório)", "content": "string (obrigatório)"},
      "Cria ou sobrescreve um arquivo de texto. Cria as pastas que faltarem.")
def t_write(api, a):
    p = _resolve(a.get("path") or "")
    if not str(p).strip():
        return "Erro: caminho vazio."
    p.parent.mkdir(parents=True, exist_ok=True)
    body = str(a.get("content") or "")
    p.write_text(body, encoding="utf-8")
    return f"Escrito {len(body)} caracteres em {p}"


@tool("list_dir", {"path": "string (opcional; padrão pasta do usuário)"}, "Lista pastas e arquivos de um diretório com tamanho.")
def t_list(api, a):
    p = _resolve(a.get("path") or Path.home())
    if not p.is_dir():
        return f"Pasta não encontrada: {p}"
    rows = []
    for e in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:200]:
        if e.is_dir():
            rows.append(f"[dir] {e.name}")
        else:
            rows.append(f"{e.stat().st_size:>9}  {e.name}")
    return "\n".join(rows) or "(vazio)"


@tool("find_files", {"pattern": "string — ex.: *.pdf ou contrato* (obrigatório)",
                     "root": "string (opcional; padrão pasta do usuário)", "limit": "int (opcional, padrão 60)"},
      "Procura arquivos por nome em uma árvore de pastas.")
def t_find(api, a):
    pat = str(a.get("pattern") or "").strip()
    if not pat:
        return "Erro: padrão vazio."
    root = _resolve(a.get("root") or Path.home())
    limit = max(1, min(300, int(a.get("limit") or 60)))
    hits = []
    for p in root.rglob(pat):
        hits.append(str(p))
        if len(hits) >= limit:
            break
    return "\n".join(hits) if hits else "Nenhum arquivo encontrado."


@tool("fetch_url", {"url": "string (obrigatório)", "max_chars": "int (opcional, padrão 8000)"},
      "Baixa uma página e devolve o texto limpo (sem HTML).")
def t_fetch(api, a):
    import requests
    url = str(a.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Jarvis)"})
    html = r.text
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    n = max(500, min(40000, int(a.get("max_chars") or 8000)))
    return f"HTTP {r.status_code} · {url}\n\n" + txt[:n]


# ---------------------------------------------------------------- mídia

@tool("spotify", {"action": "play_query|play|pause|toggle|next|prev|volume|seek|shuffle",
                  "value": "string ou número, depende da ação (opcional)"},
      "Controla o Spotify de verdade (Spicetify ou SMTC do Windows). play_query busca e toca.")
def t_spotify(api, a):
    action = str(a.get("action") or "").strip()
    if not action:
        return "Erro: ação vazia."
    if api.now.cmd(action, a.get("value")):
        return "Comando executado no Spotify."
    if action == "play_query":
        return "Busca por nome só funciona com a extensão Spicetify; para o resto, use play/pause/next."
    return "Spotify offline ou sem controle disponível."


@tool("now_playing", {}, "Diz o que está tocando no Spotify agora (faixa, artista, progresso).")
def t_now(api, a):
    d = api.now.snapshot()
    if not d.get("online"):
        return "Spotify fechado ou sem sessão de mídia."
    if not d.get("title"):
        return "Spotify aberto, nada tocando."
    return (f"{d['title']} — {d.get('artist') or '?'} ({d.get('album') or 'sem álbum'}) · "
            f"{int(d.get('position') or 0)}s de {int(d.get('duration') or 0)}s · "
            f"{'tocando' if d.get('playing') else 'pausado'} · fonte: {d.get('source')}")


@tool("media", {"action": "play|next|prev|mute"}, "Teclas de mídia do Windows (funciona com qualquer player).")
def t_media(api, a):
    from commands import key
    act = str(a.get("action") or "play")
    return "Feito." if key(act) else "Falhou."


@tool("volume", {"level": "int 0-100 (obrigatório)"}, "Define o volume do sistema em porcentagem.")
def t_volume(api, a):
    from commands import set_volume
    lvl = max(0, min(100, int(a.get("level") or 50)))
    set_volume(lvl)
    return f"Volume em {lvl}%."


# ---------------------------------------------------------------- memória, tarefas, lembretes

@tool("add_task", {"text": "string (obrigatório)"}, "Adiciona uma tarefa à lista.")
def t_add_task(api, a):
    text = str(a.get("text") or "").strip()
    if not text:
        return "Erro: tarefa vazia."
    api.store.add("task", text)
    return f"Tarefa adicionada: {text}"


@tool("list_tasks", {"open_only": "bool (opcional, padrão true)"}, "Lista tarefas.")
def t_list_tasks(api, a):
    rows = [t for t in api.store.list("task") if not (a.get("open_only", True) and t["done"])]
    if not rows:
        return "Nenhuma tarefa."
    return "\n".join(f"#{t['id']} {'[x]' if t['done'] else '[ ]'} {t['text']}" for t in rows)


@tool("done_task", {"match": "string — trecho do nome ou #id (obrigatório)"}, "Marca uma tarefa como concluída.")
def t_done_task(api, a):
    q = str(a.get("match") or "").strip().lower().lstrip("#")
    if not q:
        return "Erro: nada para procurar."
    for t in api.store.list("task"):
        if q == str(t["id"]) or q in t["text"].lower():
            api.store.update(t["id"], done=1)
            return f"Concluída: {t['text']}"
    return "Tarefa não encontrada."


@tool("add_reminder", {"text": "string (obrigatório)", "minutes": "número de minutos a partir de agora (int)"},
      "Cria um lembrete que dispara daqui a N minutos.")
def t_add_reminder(api, a):
    text = str(a.get("text") or "").strip()
    if not text:
        return "Erro: lembrete vazio."
    mins = max(0.05, float(a.get("minutes") or 10))
    due = time.time() + 60 * mins
    api.store.add("reminder", text, due=due)
    return f"Lembrete em {mins:g} min: {text}"


@tool("remember", {"text": "string (obrigatório)"}, "Grava um fato na memória permanente do Jarvis.")
def t_remember(api, a):
    text = str(a.get("text") or "").strip()
    if not text:
        return "Erro: memória vazia."
    api.store.add("memory", text)
    return "Guardado."


@tool("recall", {"query": "string (opcional)"}, "Lê a memória permanente (filtra por trecho se quiser).")
def t_recall(api, a):
    rows = api.store.list("memory", 200)
    q = str(a.get("query") or "").lower()
    if q:
        rows = [r for r in rows if q in r["text"].lower()]
    return "\n".join("- " + r["text"] for r in rows[:60]) or "Memória vazia."
