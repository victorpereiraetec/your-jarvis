"""Agente: laço que decide, chama ferramenta de verdade e volta com a resposta.

Protocolo JSON em texto puro, de propósito: funciona em qualquer provider
OpenAI-compatível (Groq, Gemini, OpenRouter, Ollama, DeepSeek), inclusive nos
grátis que não implementam function calling nativo.
"""
import datetime, json, re

import tools
from brain import PROVIDERS

MAX_STEPS = 4


class Agent:
    def __init__(self, api):
        self.api = api

    # ------------------------------------------------------------------ prompt
    def prompt(self):
        api = self.api
        mem = "; ".join(m["text"] for m in api.store.list("memory", 25)) or "nada ainda"
        spotify = "conectado" if api.now.online() else "offline"
        return (
            f"Você é Jarvis, o assistente pessoal de {api.name} neste PC Windows. "
            "Fale português do Brasil, direto e calmo, sem bajulação, sem disclaimers.\n\n"
            "REGRA PRINCIPAL — ferramenta antes de palavra:\n"
            "Quando a resposta exigir agir (abrir app, rodar comando, mexer em arquivo, controlar o Spotify, "
            "criar tarefa/lembrete/memória, ver o PC), responda APENAS com um objeto JSON, sem texto em volta "
            "e sem bloco de código:\n"
            '{"tool": "nome_da_ferramenta", "args": {"arg": "valor"}}\n'
            "Uma ferramenta por vez. Você receberá uma linha 'RESULTADO DA FERRAMENTA:' e então escolhe: "
            "chamar outra ou responder. Nunca diga que fez algo sem ter chamado a ferramenta. "
            "Nunca invente saída de comando.\n\n"
            "Se não precisar de ferramenta, responda em 1 a 3 frases. Conhecimento geral não precisa de ferramenta.\n\n"
            f"FERRAMENTAS:\n{tools.catalog()}\n\n"
            f"Spotify: {spotify}. Memória sobre {api.name}: {mem}. "
            f"Agora: {datetime.datetime.now():%d/%m/%Y %H:%M}."
        )

    # ------------------------------------------------------------------ parse
    @staticmethod
    def parse(raw):
        """Acha o primeiro objeto JSON com 'tool'. Tolera texto em volta e ```."""
        raw = re.sub(r"```(?:json)?", "", raw)
        dec = json.JSONDecoder()
        for m in re.finditer(r"\{", raw):
            try:
                obj, _ = dec.raw_decode(raw[m.start():])
            except Exception:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
                args = obj.get("args")
                return {"tool": obj["tool"].strip(), "args": args if isinstance(args, dict) else {}}
        return None

    # ------------------------------------------------------------------ laço
    def run(self, text, history=None):
        msgs = [{"role": "system", "content": self.prompt()}]
        msgs += (history or [])[-6:]
        msgs.append({"role": "user", "content": text})
        via = ""
        for _ in range(MAX_STEPS):
            raw, pid = self.api.brain.ask(msgs)
            via = PROVIDERS[pid]["label"]
            act = self.parse(raw)
            if not act:
                return {"reply": raw.strip(), "via": via}
            out = tools.run(act["tool"], self.api, act["args"])
            msgs.append({"role": "assistant", "content": raw})
            msgs.append({"role": "user", "content": (
                f"RESULTADO DA FERRAMENTA:\n{out}\n\n"
                "Se já tem o que precisa, responda ao usuário em 1 a 3 frases. "
                "Se falta algo, chame outra ferramenta com JSON puro.")})
        raw, pid = self.api.brain.ask(msgs + [{"role": "user", "content": "Responda agora, sem JSON, em 1 a 3 frases."}])
        return {"reply": raw.strip(), "via": PROVIDERS[pid]["label"]}
