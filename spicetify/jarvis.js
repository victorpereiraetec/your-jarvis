// Jarvis — extensão Spicetify
// Coloque em: %APPDATA%\spicetify\Extensions\jarvis.js
// Ative com:  spicetify config extensions jarvis.js && spicetify apply
//
// Ela conversa com o Jarvis rodando em 127.0.0.1 (portas 8765-8775):
//   GET  /spicetify/next   -> recebe comandos
//   POST /spicetify/state  -> devolve faixa, progresso, volume
//   POST /spicetify/ack    -> confirma se o comando realmente funcionou
// Nada sai da máquina.

(function () {
  if (window.__jarvisLoaded) return;
  window.__jarvisLoaded = true;

  const PORTS = [8765, 8766, 8767, 8768, 8769, 8770, 8771, 8772, 8773, 8774, 8775];
  let base = null;
  let lastState = 0;
  let busy = false;
  let lastError = "";

  const log = (...a) => console.log("[jarvis]", ...a);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  async function findHost() {
    if (base) return base;
    for (const p of PORTS) {
      try {
        const r = await fetch(`http://127.0.0.1:${p}/spicetify/ping`, { cache: "no-store" });
        if (r.ok) {
          base = `http://127.0.0.1:${p}`;
          log("conectado em", base);
          return base;
        }
      } catch (e) {}
    }
    return null;
  }

  function ready() {
    return window.Spicetify && Spicetify.Player && Spicetify.Player.data;
  }

  function snapshot() {
    try {
      const d = Spicetify.Player.data || {};
      const m = (d.item && d.item.metadata) || {};
      let art = m.image_url || m.image_xlarge_url || "";
      if (!art && d.item && d.item.images && d.item.images[0]) art = d.item.images[0].url || "";
      // O Spotify entrega a capa como URI (spotify:image:<hash>), não como URL.
      // Sem converter, a interface recebe um endereço inválido e a arte some.
      if (art.indexOf("spotify:image:") === 0) {
        art = "https://i.scdn.co/image/" + art.slice("spotify:image:".length);
      }
      return {
        playing: !!Spicetify.Player.isPlaying(),
        title: m.title || "",
        artist: m.artist_name || m.artist_names || "",
        album: m.album_title || "",
        art,
        position: Spicetify.Player.getProgress() || 0,
        duration: Spicetify.Player.getDuration() || 0,
        volume: typeof Spicetify.Player.getVolume === "function"
          ? Math.round((Spicetify.Player.getVolume() || 0) * 100) : 0,
        shuffle: !!(d.shuffle && (d.shuffle.enabled !== undefined ? d.shuffle.enabled : d.shuffle)),
        repeat: (d.repeat || 0)
      };
    } catch (e) {
      return { playing: false, title: "", artist: "", art: "", position: 0, duration: 0, volume: 0 };
    }
  }

  async function report(force) {
    const now = Date.now();
    if (!force && now - lastState < 1500) return;
    lastState = now;
    const b = await findHost();
    if (!b) return;
    try {
      await fetch(b + "/spicetify/state", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(snapshot())
      });
    } catch (e) {
      base = null;
    }
  }

  async function ack(c, ok, error) {
    const b = await findHost();
    if (!b) return;
    try {
      await fetch(b + "/spicetify/ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: c.id, ok: !!ok, error: error || "" })
      });
    } catch (e) {
      base = null;
    }
  }

  // Busca a primeira faixa. A API autenticada (CosmosAsync) é a mais estável;
  // a SearchAPI interna fica como reserva para versões diferentes do Spicetify.
  async function searchTrack(q) {
    try {
      if (Spicetify.CosmosAsync) {
        const r = await Spicetify.CosmosAsync.get(
          "https://api.spotify.com/v1/search?q=" + encodeURIComponent(q) + "&type=track&limit=1"
        );
        const t = r && r.tracks && r.tracks.items && r.tracks.items[0];
        if (t && t.uri) return t.uri;
        lastError = "api: nenhuma faixa encontrada";
      } else {
        lastError = "api: CosmosAsync indisponível";
      }
    } catch (e) {
      lastError = "api: " + (e && e.message ? e.message : String(e));
      log("busca pela API falhou", e);
    }
    try {
      const api = Spicetify.Platform && Spicetify.Platform.SearchAPI;
      if (api && api.search) {
        const r = await api.search({
          query: q, limit: 10, offset: 0, includeAudiobooks: false,
          includeArtist: true, includeAlbum: true, includePlaylist: true,
          includePodcast: true, includeEpisode: true
        });
        const cand =
          (r.tracks && r.tracks.items && r.tracks.items[0]) ||
          (r.tracksV2 && r.tracksV2.items && (r.tracksV2.items[0].item || r.tracksV2.items[0])) ||
          (r.topResultsV2 && r.topResultsV2.items &&
            (r.topResultsV2.items.find(x => (x.item || x).uri && (x.item || x).uri.indexOf("spotify:track:") === 0) || {}).item);
        if (cand && cand.uri) return cand.uri;
        lastError += " | interna: sem resultado";
      } else {
        lastError += " | interna: indisponível";
      }
    } catch (e) {
      lastError += " | interna: " + (e && e.message ? e.message : String(e));
      log("busca interna falhou", e);
    }
    return "";
  }

  async function playQuery(q) {
    const uri = await searchTrack(q);
    if (!uri) {
      log("nada encontrado para", q);
      return false;
    }
    try {
      const r = Spicetify.Player.playUri(uri);
      if (r && r.then) await r;
    } catch (e) {
      lastError = "playUri: " + (e && e.message ? e.message : String(e));
      log("playUri falhou", e);
      return false;
    }
    await sleep(900);
    if (!Spicetify.Player.isPlaying()) {
      try { Spicetify.Player.play(); } catch (e) {}
      await sleep(600);
    }
    if (!Spicetify.Player.isPlaying()) {
      lastError = "playUri: a reprodução não iniciou";
      return false;
    }
    return true;
  }

  // Devolve true só quando o efeito aconteceu de fato.
  async function run(c) {
    const v = c.value;
    try {
      switch (c.action) {
        case "toggle": Spicetify.Player.togglePlay(); return true;
        case "play":
          if (Spicetify.Player.play) Spicetify.Player.play();
          else if (!Spicetify.Player.isPlaying()) Spicetify.Player.togglePlay();
          return true;
        case "pause":
          if (Spicetify.Player.pause) Spicetify.Player.pause();
          else if (Spicetify.Player.isPlaying()) Spicetify.Player.togglePlay();
          return true;
        case "next": Spicetify.Player.next(); return true;
        case "prev": Spicetify.Player.back(); return true;
        case "volume": {
          if (typeof Spicetify.Player.setVolume !== "function") return false;
          const val = Number(v);
          if (!isFinite(val)) return false;
          Spicetify.Player.setVolume(Math.max(0, Math.min(1, val > 1 ? val / 100 : val)));
          return true;
        }
        case "seek":
          if (!(Number(v) >= 0)) return false;
          Spicetify.Player.seek(Number(v) * 1000);
          return true;
        case "shuffle":
          if (!Spicetify.Player.toggleShuffle) return false;
          Spicetify.Player.toggleShuffle();
          return true;
        case "repeat":
          if (!Spicetify.Player.toggleRepeat) return false;
          Spicetify.Player.toggleRepeat();
          return true;
        case "like":
          if (!Spicetify.Player.toggleHeart) return false;
          Spicetify.Player.toggleHeart();
          return true;
        case "play_query":
          return v ? await playQuery(String(v)) : false;
        case "debug": {
          const out = { cosmos: !!Spicetify.CosmosAsync };
          out.keys = Object.keys(Spicetify.Platform || {})
            .filter(k => /search|session/i.test(k)).join(",");
          try {
            const r = await Spicetify.CosmosAsync.get(
              "https://api.spotify.com/v1/search?q=polo%20branca&type=track&limit=1"
            );
            out.r = r ? ("tracks=" + (r.tracks ? (r.tracks.items || []).length : "ninguem") +
              " top=" + Object.keys(r).join("/")) : "null";
          } catch (e) {
            out.r = "erro " + (e && e.message ? e.message : String(e));
          }
          lastError = JSON.stringify(out).slice(0, 190);
          return false;
        }
        default:
          log("comando desconhecido", c.action);
          return false;
      }
    } catch (e) {
      log("erro no comando", c.action, e);
      return false;
    }
  }

  async function tick() {
    if (busy || !ready()) return;
    busy = true;
    try {
      const b = await findHost();
      if (b) {
        const r = await fetch(b + "/spicetify/next", { cache: "no-store" });
        if (r.ok) {
          const data = await r.json();
          const cmds = data.cmds || [];
          for (const c of cmds) {
            lastError = "";
            const ok = await run(c);
            await ack(c, ok, lastError);
          }
          if (cmds.length) await report(true);
        }
      }
    } catch (e) {
      base = null;
    } finally {
      busy = false;
    }
    await report(false);
  }

  const boot = setInterval(() => {
    if (!ready()) return;
    clearInterval(boot);
    log("pronto");
    setInterval(tick, 700);
    setInterval(() => report(false), 2000);
    tick();
    if (Spicetify.Player.addEventListener) {
      Spicetify.Player.addEventListener("songchange", () => report(true));
      Spicetify.Player.addEventListener("onplaypause", () => report(true));
    }
  }, 1000);
})();
