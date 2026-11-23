<div align="center">

# 🤖 Jarvis — Base para um Assistente Pessoal

**Um assistente estilo J.A.R.V.I.S. para Windows que não só conversa: ele _executa_ coisas no seu PC.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Plataforma](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![IA](https://img.shields.io/badge/IA-Groq%20%7C%20Gemini%20%7C%20Ollama%20%7C%20mais-8A2BE2)
![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)
![Status](https://img.shields.io/badge/status-base%20para%20estudo-orange)

Feito por **[Victor Pereira](https://github.com/victorpereiraetec)** — estudante da **ETEC** 🎓

</div>

---

## 📖 Sobre o projeto

Este repositório é uma **base** para quem quer construir o seu próprio assistente pessoal. Ele junta, em um código
pequeno e legível, as peças que todo "Jarvis" precisa:

- um **cérebro** que fala com várias IAs gratuitas e troca sozinho quando uma falha;
- um **agente** que decide qual ferramenta usar e a executa de verdade (abrir apps, mexer em arquivos, rodar comandos...);
- **comandos locais** em português que funcionam sem internet e sem gastar IA;
- **voz** (ouvir e falar), **atalhos globais**, **mini player do Spotify** e **monitor do PC** ao vivo.

A ideia é ser fácil de entender e de modificar: cada arquivo tem uma responsabilidade só, e quase tudo é Python
puro com poucas dependências.

> 💡 O projeto nasceu como estudo. Fique à vontade para dar fork, quebrar, remendar e transformar no seu próprio assistente.

---

## ✨ Funcionalidades

| Área | O que faz |
|---|---|
| 🧠 **Cérebro multi-IA** | Groq, Gemini, OpenRouter (DeepSeek e modelos `:free`), OpenCode Zen, DeepSeek, Ollama (local) e OpenAI. No modo **Automático**, se uma IA falhar ou estourar o limite grátis, passa para a próxima. |
| 🛠️ **Agente com ferramentas** | O modelo responde com JSON, o Jarvis executa a ferramenta e devolve o resultado para o modelo, em até 4 passos. |
| ⚡ **Comandos locais** | Horas, data, abrir apps, volume, música, timers, lembretes, tarefas, hábitos, rotinas, memória e status do PC — tudo **sem IA**. |
| 🎵 **Spotify** | Lê e controla o Spotify por 3 caminhos (Spicetify → Windows SMTC → título da janela). |
| 🪟 **Mini player** | Janela sem moldura, sempre no topo, com capa, progresso e controles. |
| ⌨️ **Atalhos globais** | `Ctrl+Alt+J` e `Ctrl+Alt+Space`, sem dependências externas. |
| 🖥️ **Aba "Meu PC"** | CPU (por núcleo), memória, discos, rede, GPU, processos e bateria, atualizados ao vivo. |
| 🎙️ **Voz** | Responde falando (vozes neurais do Edge) e ouve o microfone chamando "Jarvis". |
| 🗒️ **Organização** | Tarefas, lembretes, hábitos com sequência (streak), rotinas e memória permanente. |
| 📜 **Auditoria** | Toda ferramenta executada fica registrada em `data/agent.log`. |

---

## 🚀 Como rodar

### Requisitos

- **Windows 10 ou 11**
- **Python 3.10+** instalado, com a opção **"Add Python to PATH"** marcada

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/victorpereiraetec/your-jarvis.git
cd your-jarvis

# 2. Crie sua configuração a partir do modelo (opcional — o app cria uma sozinho)
copy data\config.example.json data\config.json

# 3. Instale as dependências e abra
iniciar.bat
```

Ou manualmente:

```bash
pip install -r requirements.txt
python main.py
```

### Conectando uma IA

1. Abra a aba **Cérebro** na interface.
2. Cole uma chave grátis e clique em **Testar**:

| Provedor | Onde pegar a chave |
|---|---|
| ⚡ Groq (o mais rápido) | <https://console.groq.com/keys> |
| ✨ Gemini | <https://aistudio.google.com/apikey> |
| 🔀 OpenRouter | <https://openrouter.ai/keys> |
| 🏠 Ollama (local, sem chave) | <https://ollama.com> |

3. Deixe o modo em **Automático** para ter troca de IA em caso de falha.

> ⚠️ **Os nomes de modelos gratuitos mudam com o tempo.** Se um der erro, edite o campo "modelo" no card da IA.

---

## 🧩 Arquitetura

```
┌───────────────────────────────────────────────────────────────┐
│  Interface (ui/index.html + ui/mini.html)  — via pywebview    │
└──────────────────────────────┬────────────────────────────────┘
                               │ HTTP local + token  (127.0.0.1)
┌──────────────────────────────▼────────────────────────────────┐
│  main.py  — servidor, janelas, atalhos, rotas da API          │
└──┬───────────────┬─────────────────┬───────────────────┬──────┘
   │               │                 │                   │
   ▼               ▼                 ▼                   ▼
commands.py     agent.py          engine.py          nowplaying.py
(sem IA)     (laço do agente)  (timers/lembretes)   (Spotify 3 fontes)
                   │
          ┌────────┴────────┐
          ▼                 ▼
      brain.py          tools.py
  (IAs + failover)   (ações no PC)
```

### Fluxo de uma mensagem

1. Você escreve (ou fala) um pedido.
2. `commands.py` tenta resolver **localmente**. Se entender, responde na hora — sem IA, sem internet.
3. Se não entender, o pedido vai para o **agente** (`agent.py`).
4. O agente monta o prompt (ferramentas disponíveis + memória + data/hora) e pergunta ao `brain.py`.
5. Se o modelo responder um JSON `{"tool": "...", "args": {...}}`, o `tools.py` executa e o resultado volta para o modelo.
6. Quando o modelo responde em texto normal, essa é a resposta final (e é falada, se a voz estiver ligada).

> O protocolo de ferramentas é **JSON em texto puro, de propósito**: assim funciona em qualquer provedor
> compatível com a API da OpenAI, inclusive nos gratuitos que não têm _function calling_ nativo.

### Estrutura de arquivos

```
.
├── main.py            # servidor local, janelas, atalhos e rotas da API
├── agent.py           # laço do agente (prompt + protocolo de ferramenta em JSON)
├── tools.py           # ferramentas que mexem na máquina (+ auditoria)
├── brain.py           # provedores de IA e failover automático
├── commands.py        # comandos locais em português (sem IA)
├── store.py           # SQLite — uma tabela, separada por tipo
├── engine.py          # timers, lembretes e histórico da área de transferência
├── voice.py           # microfone (ouvir) e vozes neurais (falar)
├── hotkey.py          # atalhos globais via RegisterHotKey
├── nowplaying.py      # estado do Spotify (Spicetify → SMTC → título da janela)
├── spotify.py         # ponte de comandos com a extensão Spicetify
├── sysinfo.py         # monitor ao vivo do PC
├── ui/                # interface principal e mini player (HTML/CSS/JS puros)
├── spicetify/         # extensão opcional para o Spotify
├── data/              # config, banco e logs (criados localmente, ignorados pelo Git)
├── iniciar.bat        # instala dependências e abre
└── requirements.txt
```

---

## 🛠️ Ferramentas do agente

O agente pode chamar as ferramentas abaixo. Para criar a sua, basta registrar uma função com o decorador `@tool`.

| Ferramenta | Função |
|---|---|
| `run_shell` | Executa um comando PowerShell (acesso total ao PC) |
| `open_app` / `open_url` | Abre aplicativos, arquivos e links |
| `read_file` / `write_file` | Lê e grava arquivos |
| `list_dir` / `find_files` | Lista pastas e busca arquivos |
| `fetch_url` | Baixa o texto de uma página |
| `sysinfo` | Resumo da máquina (CPU, RAM, discos, rede...) |
| `screenshot` | Captura a tela _(requer `pillow`)_ |
| `lock_pc` / `notify` | Bloqueia a sessão / mostra um aviso |
| `spotify` / `now_playing` / `media` / `volume` | Controle de música e volume |
| `add_task` / `list_tasks` / `done_task` | Tarefas |
| `add_reminder` | Lembretes |
| `remember` / `recall` | Memória permanente |

### ➕ Criando uma ferramenta nova

```python
# tools.py
@tool("hora_atual", {}, "Diz que horas são agora.")
def t_hora(api, a):
    import datetime
    return datetime.datetime.now().strftime("%H:%M")
```

Pronto: ela entra automaticamente no catálogo que o modelo enxerga. Cada ferramenta recebe `(api, args)` e devolve
um **texto curto** — é isso que o modelo lê de volta.

---

## 💬 Exemplos de uso

Pedidos compostos (vão para a IA + ferramentas):

- _"Abre o Chrome e pesquisa passagem para Recife"_
- _"Lê o arquivo X e me resume"_
- _"Quanto espaço tem no disco e o que está ocupando mais?"_

Comandos locais (resolvem sem IA e sem internet):

- _"Que horas são?"_ · _"Que dia é hoje?"_
- _"Abre o bloco de notas"_ · _"Volume em 40"_
- _"Timer de 10 minutos"_ · _"Me lembra de beber água em 30 minutos"_
- _"Minhas tarefas"_ · _"Como está o PC?"_ · _"Qual é o processador?"_

---

## 🎵 Spotify

O Jarvis usa o primeiro caminho que estiver ativo:

1. **Extensão Spicetify** — a mais completa: busca e toca por nome, volume e shuffle reais.
2. **Windows SMTC** — o mesmo "tocando agora" do Windows; funciona sem instalar nada.
3. **Título da janela** — último recurso, só faixa e artista.

### Instalando a extensão Spicetify (opcional)

```powershell
Copy-Item ".\spicetify\jarvis.js" "$env:APPDATA\spicetify\Extensions\jarvis.js" -Force
spicetify config extensions jarvis.js
spicetify apply
```

A extensão procura o Jarvis sozinha nas portas 8765–8775.

---

## ⌨️ Atalhos globais

| Atalho | Ação |
|---|---|
| `Ctrl + Alt + J` | Mostra/esconde o mini player |
| `Ctrl + Alt + Space` | Traz a janela principal e foca no campo de texto |

Configuráveis em `data/config.json`, na chave `hotkeys`.

---

## 🎙️ Voz

As dependências de voz já estão no `requirements.txt`. Ative em **Cérebro → Ajustes**:

- **Responder falando** — usa as vozes neurais do Edge (`edge-tts`), com plano B offline (`pyttsx3`).
- **Ouvir Jarvis o tempo todo** — aceita "Jarvis" e também "sexta-feira".

---

## 🔐 Segurança e privacidade

Este projeto dá **acesso total ao computador** para um modelo de IA. Leia com atenção antes de usar.

### Como o app se protege

- O servidor só escuta em `127.0.0.1` e rejeita qualquer `Host` que não seja local.
- As rotas da API exigem um **token aleatório**, gerado a cada execução e injetado na página.
- Só os métodos listados em `Api.PUBLIC` são acessíveis pela interface.
- Toda ferramenta executada é registrada em `data/agent.log`.
- As chaves de API ficam **somente** em `data/config.json`, que está no `.gitignore`.

### ⚠️ Pontos de atenção

- **`run_shell` executa qualquer comando PowerShell sem pedir confirmação.** Uma IA pode errar. Se for usar em
  produção ou em um PC compartilhado, adicione uma etapa de confirmação para ações perigosas.
- As rotas `/spicetify/*` respondem com CORS aberto (`*`), porque a extensão roda dentro do Spotify. Elas só
  controlam o player, mas vale saber.
- O histórico da área de transferência (`clip`) vem **desligado** — senhas copiadas também seriam salvas no banco.
- As mensagens que você manda ao Jarvis são enviadas ao provedor de IA escolhido. Não passe dados sensíveis.

### ✅ Antes de publicar no GitHub (checklist)

- [ ] `data/` **não** está no commit (`git status` deve mostrar só `.gitkeep` e `config.example.json`)
- [ ] Nenhuma chave de API no código (`git grep -nE "gsk_|AIza|sk-"` não deve retornar nada)
- [ ] Nenhum `.db`, `.log` ou `__pycache__` versionado
- [ ] Se uma chave **já foi** exposta em algum lugar, **revogue e gere outra** no painel do provedor

---

## 🗺️ Ideias para evoluir

- [ ] Confirmação antes de ações perigosas (apagar arquivos, desligar o PC)
- [ ] Suporte a Linux e macOS (hoje o foco é Windows)
- [ ] Busca semântica na memória (embeddings)
- [ ] Integração com agenda e e-mail
- [ ] Plugins: uma pasta `plugins/` carregada automaticamente
- [ ] Testes automatizados para o parser do agente e os comandos locais

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Abra uma _issue_ com a ideia ou envie um _pull request_.

1. Faça um fork
2. Crie uma branch: `git checkout -b minha-feature`
3. Commit: `git commit -m "feat: minha feature"`
4. Push: `git push origin minha-feature`
5. Abra um Pull Request

---

## 👨‍💻 Autor

**Victor Pereira** — estudante da ETEC.

[![GitHub](https://img.shields.io/badge/GitHub-victorpereiraetec-181717?logo=github&logoColor=white)](https://github.com/victorpereiraetec)

Este projeto faz parte dos meus estudos de programação e inteligência artificial.

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo [`LICENSE`](LICENSE) para mais detalhes.
