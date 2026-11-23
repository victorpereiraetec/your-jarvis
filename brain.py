"""Cérebro: fala com várias IAs pelo mesmo formato (OpenAI-compatível) e troca
automaticamente quando uma falha ou chega no limite grátis."""
import re, time, requests

PROVIDERS = {
    "groq": dict(label="Groq", url="https://api.groq.com/openai/v1/chat/completions",
                 model="openai/gpt-oss-120b", link="console.groq.com/keys", free=True,
                 note="Muito rápida, plano grátis generoso."),
    "gemini": dict(label="Gemini", url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                   model="gemini-2.5-flash", link="aistudio.google.com/apikey", free=True,
                   note="Chave grátis no Google AI Studio."),
    "openrouter": dict(label="OpenRouter (DeepSeek e outros)", url="https://openrouter.ai/api/v1/chat/completions",
                       model="deepseek/deepseek-chat-v3.1:free", link="openrouter.ai/keys", free=True,
                       note="Dá acesso a modelos grátis, inclusive DeepSeek. Troque o modelo por qualquer um com sufixo :free."),
    "opencode": dict(label="OpenCode Zen", url="https://opencode.ai/zen/v1/chat/completions",
                     model="", link="opencode.ai/zen", free=True,
                     note="Preencha o nome de um modelo gratuito listado no site."),
    "deepseek": dict(label="DeepSeek (API direta)", url="https://api.deepseek.com/chat/completions",
                     model="deepseek-chat", link="platform.deepseek.com", free=False,
                     note="Muito barato, mas pago por uso."),
    "ollama": dict(label="Ollama (roda no seu PC)", url="http://localhost:11434/v1/chat/completions",
                   model="llama3.2", link="ollama.com", free=True, nokey=True,
                   note="Sem internet e sem limite. Precisa de um PC mais forte."),
    "openai": dict(label="ChatGPT (API paga)", url="https://api.openai.com/v1/chat/completions",
                   model="gpt-4o-mini", link="platform.openai.com/api-keys", free=False,
                   note="O ChatGPT grátis do site não tem API. Esta opção é paga por uso."),
}
ORDER = ["groq", "gemini", "openrouter", "opencode", "deepseek", "ollama", "openai"]


class BrainError(Exception):
    pass


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cool = {}

    def pcfg(self, pid):
        c = self.cfg.get("providers", {}).get(pid, {})
        return c.get("key", ""), c.get("model") or PROVIDERS[pid]["model"], c.get("on", False)

    def usable(self):
        out = []
        for pid in ORDER:
            key, model, on = self.pcfg(pid)
            if on and model and (key or PROVIDERS[pid].get("nokey")):
                out.append(pid)
        return out

    def status(self):
        mode = self.cfg.get("mode", "auto")
        ids = self.usable() if mode == "auto" else [mode]
        ids = [i for i in ids if i in self.usable()]
        if not ids:
            return None
        pid = next((i for i in ids if self.cool.get(i, 0) <= time.time()), ids[0])
        return {"id": pid, "label": PROVIDERS[pid]["label"], "model": self.pcfg(pid)[1]}

    def ask(self, messages, only=None):
        mode = self.cfg.get("mode", "auto")
        ids = [only] if only else (self.usable() if mode == "auto" else [mode])
        if not ids or (not only and not [i for i in ids if i in self.usable()]):
            raise BrainError("Nenhuma IA configurada. Abra a aba Cérebro e cole uma chave grátis (Groq ou Gemini).")
        errs = []
        for pid in ids:
            if not only and self.cool.get(pid, 0) > time.time():
                continue
            try:
                return self._call(pid, messages), pid
            except Exception as e:
                errs.append(f"{PROVIDERS[pid]['label']}: {e}")
                if "429" in str(e):
                    self.cool[pid] = time.time() + 90
        raise BrainError("Todas as IAs falharam. " + " | ".join(errs))

    def _call(self, pid, messages):
        key, model, _ = self.pcfg(pid)
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = "Bearer " + key
        r = requests.post(PROVIDERS[pid]["url"], headers=h, timeout=45,
                          json={"model": model, "messages": messages, "temperature": 0.6, "max_tokens": 700})
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code} {r.text[:100]}")
        txt = r.json()["choices"][0]["message"].get("content") or ""
        txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
        if not txt:
            raise Exception("resposta vazia")
        return txt
