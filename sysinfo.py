"""Radiografia ao vivo da máquina.

Uma amostra por segundo em segundo plano alimenta gráficos e números: CPU
(total e por núcleo), memória, discos, rede, bateria e processos. O que é
estático (modelo, Windows, GPU, tipo dos discos) é lido uma vez e cacheado.

Só psutil é obrigatório. O resto (GPU, tipo de disco, Wi-Fi) usa registro do
Windows e comandos nativos com fallback silencioso — se não der, o campo some.
"""
import json, os, platform, socket, subprocess, threading, time
from collections import deque

try:
    import psutil
except ImportError:  # o app avisa na interface
    psutil = None

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ---------------------------------------------------------------- estático
def _reg(path, name, default=""):
    if os.name != "nt":
        return default
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return default


def _volume_label(mount):
    if os.name != "nt":
        return ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(mount), buf, 261, None, None, None, None, 0)
        return buf.value if ok else ""
    except Exception:
        return ""


def _gpus():
    """Nome, VRAM e driver lidos direto do registro — sem WMI, sem espera."""
    out, seen = [], set()
    if os.name != "nt":
        return out
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            total = winreg.QueryInfoKey(k)[0]
        for i in range(total):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                    sub = winreg.EnumKey(k, i)
            except OSError:
                continue
            if not sub.isdigit():
                continue
            path = base + "\\" + sub
            name = str(_reg(path, "DriverDesc") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            raw = _reg(path, "HardwareInformation.qwMemorySize", 0)
            try:
                vram = round(int(raw) / 2 ** 30, 1) if raw else None
            except Exception:
                vram = None
            out.append({"name": name, "vram_gb": vram,
                        "driver": str(_reg(path, "DriverVersion") or "")})
    except Exception:
        pass
    return out


def _static():
    bios = r"HARDWARE\DESCRIPTION\System\BIOS"
    win = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    maker = str(_reg(bios, "SystemManufacturer") or "").strip()
    model = str(_reg(bios, "SystemProductName") or "").strip()
    if maker.lower() in ("system manufacturer", "default string"):
        maker = ""
    if model.lower() in ("system product name", "default string"):
        model = ""
    product = str(_reg(win, "ProductName") or "Windows")
    edition = str(_reg(win, "DisplayVersion") or "")
    build = _reg(win, "CurrentBuild", "")
    ubr = _reg(win, "UBR", 0)
    board_maker = str(_reg(bios, "BaseBoardManufacturer") or "").strip()
    board_prod = str(_reg(bios, "BaseBoardProduct") or "").strip()
    return {
        "host": socket.gethostname(),
        "user": os.environ.get("USERNAME", ""),
        "arch": platform.machine() or "",
        "cpu_name": str(_reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                             "ProcessorNameString") or platform.processor()).strip(),
        "model": f"{maker} {model}".strip() if model else "",
        "board": " ".join(x for x in (board_maker, board_prod) if x),
        "os": f"{product} {edition}".strip(),
        "build": f"{build}.{ubr}" if build else "",
        "gpus": _gpus(),
    }


# ---------------------------------------------------------------- ao vivo
class Machine:
    def __init__(self):
        self.static = _static()
        self.history = {k: deque(maxlen=60) for k in ("cpu", "ram", "net", "disk")}
        self.cur = {"cpu": 0.0, "per_core": [], "freq": 0.0, "max_freq": 0.0,
                    "ram": 0.0, "down": 0.0, "up": 0.0, "read": 0.0, "write": 0.0}
        self.physical = []
        self.ssid = ""
        self._net = None
        self._disk = None
        self._t = time.time()
        self._procs = []
        self._procs_at = 0.0
        if psutil is not None:
            threading.Thread(target=self._loop, daemon=True, name="machine").start()
            threading.Thread(target=self._physical, daemon=True, name="machine-disks").start()
            threading.Thread(target=self._wifi, daemon=True, name="machine-wifi").start()

    # ---------------- amostragem
    def _loop(self):
        try:
            psutil.cpu_percent(None, percpu=True)
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(None)
                except Exception:
                    pass
        except Exception:
            pass
        n = 0
        while True:
            try:
                self._sample()
                if n and n % 60 == 0:
                    threading.Thread(target=self._wifi, daemon=True).start()
            except Exception:
                pass
            n += 1
            time.sleep(1.0)

    def _sample(self):
        now = time.time()
        dt = max(0.25, now - self._t)
        self._t = now
        per = psutil.cpu_percent(None, percpu=True) or []
        cpu = sum(per) / len(per) if per else 0.0
        try:
            f = psutil.cpu_freq()
            freq, maxf = float(f.current or 0), float(f.max or 0)
        except Exception:
            freq = maxf = 0.0
        mem = None
        try:
            mem = psutil.virtual_memory()
        except Exception:
            pass
        try:
            net = psutil.net_io_counters()
        except Exception:
            net = None
        try:
            dio = psutil.disk_io_counters()
        except Exception:
            dio = None
        down = up = read = write = 0.0
        if self._net is not None and net is not None:
            down = max(0.0, (net.bytes_recv - self._net.bytes_recv) / dt / 2 ** 20)
            up = max(0.0, (net.bytes_sent - self._net.bytes_sent) / dt / 2 ** 20)
        if self._disk is not None and dio is not None:
            read = max(0.0, (dio.read_bytes - self._disk.read_bytes) / dt / 2 ** 20)
            write = max(0.0, (dio.write_bytes - self._disk.write_bytes) / dt / 2 ** 20)
        self._net, self._disk = net, dio
        self.cur = {"cpu": round(cpu, 1), "per_core": [round(x, 1) for x in per],
                    "freq": freq, "max_freq": maxf,
                    "ram": round(mem.percent, 1) if mem else 0.0,
                    "down": round(down, 2), "up": round(up, 2),
                    "read": round(read, 2), "write": round(write, 2)}
        self.history["cpu"].append(self.cur["cpu"])
        self.history["ram"].append(self.cur["ram"])
        self.history["net"].append(self.cur["down"])
        self.history["disk"].append(round(read + write, 2))

    # ---------------- estáticos de segunda mão
    def _physical(self):
        if os.name != "nt":
            return
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=25, creationflags=CREATE_NO_WINDOW,
                encoding="utf-8", errors="replace")
            data = json.loads(p.stdout or "[]")
        except Exception:
            return
        if isinstance(data, dict):
            data = [data]
        media = {0: "", 3: "HDD", 4: "SSD", 5: "SCM"}
        bus = {1: "SCSI", 3: "ATA", 7: "USB", 8: "RAID", 10: "SAS", 11: "SATA",
               14: "Virtual", 16: "Storage Spaces", 17: "NVMe", 18: "SCM", 19: "UFS"}
        rows = []
        for d in data:
            try:
                size = float(d.get("Size") or 0) / 2 ** 30
            except Exception:
                size = 0.0
            m, b = d.get("MediaType"), d.get("BusType")
            # O ConvertTo-Json do PowerShell 5.1 entrega enums como texto.
            media_txt = m if isinstance(m, str) and not m.isdigit() else media.get(int(m or 0), "")
            bus_txt = b if isinstance(b, str) and not b.isdigit() else bus.get(int(b or 0), "")
            if media_txt == "Unspecified":
                media_txt = ""
            rows.append({"name": str(d.get("FriendlyName") or "Disco").strip(),
                         "media": media_txt, "bus": bus_txt, "gb": round(size)})
        self.physical = rows

    def _wifi(self):
        if os.name != "nt":
            return
        try:
            p = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                               capture_output=True, text=True, timeout=10,
                               creationflags=CREATE_NO_WINDOW, encoding="oem", errors="replace")
            for line in (p.stdout or "").splitlines():
                if "SSID" in line and "BSSID" not in line:
                    val = line.split(":", 1)[-1].strip()
                    if val:
                        self.ssid = val
                        return
        except Exception:
            pass

    # ---------------- processos
    def _processes(self):
        if psutil is None:
            return {"count": 0, "by_cpu": [], "by_mem": []}
        if self._procs and time.time() - self._procs_at < 2.0:
            rows = self._procs
        else:
            n = psutil.cpu_count() or 1
            rows = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    i = p.info
                    pid = i.get("pid") or 0
                    name = str(i.get("name") or "?")
                    if pid in (0, 4) or name.lower() in ("system idle process", "idle", "system"):
                        continue
                    mi = i.get("memory_info")
                    rows.append({"pid": pid,
                                 "name": name.replace(".exe", ""),
                                 "cpu": round(float(i.get("cpu_percent") or 0) / n, 1),
                                 "mem": round((mi.rss if mi else 0) / 2 ** 20, 1)})
                except Exception:
                    continue
            self._procs, self._procs_at = rows, time.time()
        by_cpu = sorted((r for r in rows if r["cpu"] >= 0.3), key=lambda r: -r["cpu"])[:5]
        by_mem = sorted(rows, key=lambda r: -r["mem"])[:5]
        return {"count": len(rows), "by_cpu": by_cpu, "by_mem": by_mem}

    # ---------------- leitura
    def _disks(self):
        out, system_pct = [], 0.0
        root = os.path.abspath(os.sep).rstrip("\\").lower()
        for p in psutil.disk_partitions(all=False):
            if not p.fstype or "cdrom" in (p.opts or ""):
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            if u.total <= 0:
                continue
            if p.mountpoint.rstrip("\\").lower() == root:
                system_pct = round(u.percent, 1)
            out.append({"mount": p.device.rstrip("\\"),
                        "label": _volume_label(p.mountpoint),
                        "fs": p.fstype,
                        "total_gb": round(u.total / 2 ** 30, 1),
                        "free_gb": round(u.free / 2 ** 30, 1),
                        "used_gb": round(u.used / 2 ** 30, 1),
                        "percent": round(u.percent, 1)})
        if out and not system_pct:
            system_pct = out[0]["percent"]
        return out, system_pct

    def _netinfo(self):
        ip, iface = "", ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.35)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        if ip:
            try:
                for name, addrs in psutil.net_if_addrs().items():
                    for a in addrs:
                        if a.family == socket.AF_INET and a.address == ip:
                            iface = name
                            break
                    if iface:
                        break
            except Exception:
                pass
        return {"ip": ip, "iface": iface, "ssid": self.ssid}

    def snapshot(self):
        if psutil is None:
            return {"error": "Instale o psutil (pip install psutil) para eu ver o PC."}
        c, s = self.cur, self.static
        try:
            mem = psutil.virtual_memory()
        except Exception:
            mem = type("M", (), {"total": 0, "used": 0, "available": 0, "percent": 0.0})()
        try:
            swap = psutil.swap_memory()
        except Exception:
            swap = None
        disks, system_pct = self._disks()
        procs = self._processes()
        net = self._netinfo()
        bat, batinfo = None, None
        try:
            b = psutil.sensors_battery()
            if b:
                bat = round(b.percent, 0)
                left = None
                if b.secsleft is not None and b.secsleft >= 0:
                    left = int(b.secsleft)
                batinfo = {"percent": bat, "plugged": bool(b.power_plugged), "secsleft": left}
        except Exception:
            pass
        temp = None
        try:
            for _, entries in (psutil.sensors_temperatures() or {}).items():
                if entries:
                    temp = round(entries[0].current, 0)
                    break
        except Exception:
            pass
        try:
            boot = psutil.boot_time()
            uptime = int(time.time() - boot)
        except Exception:
            boot, uptime = 0, 0
        return {
            # números antigos, mantidos para comandos e ferramentas
            "cpu": c["cpu"], "ram": c["ram"], "disk": system_pct,
            "ram_gb": round(mem.used / 2 ** 30, 1),
            "ram_total": round(mem.total / 2 ** 30, 1),
            "battery": bat,
            # blocos ricos
            "system": {"host": s["host"], "user": s["user"], "os": s["os"],
                       "build": s["build"], "arch": s["arch"], "model": s["model"],
                       "board": s["board"], "uptime": uptime,
                       "boot": time.strftime("%d/%m/%Y %H:%M", time.localtime(boot)) if boot else ""},
            "processor": {"name": s.get("cpu_name") or platform.processor() or "CPU",
                          "cores": psutil.cpu_count(logical=False) or 0,
                          "threads": psutil.cpu_count(logical=True) or 0,
                          "usage": c["cpu"], "per_core": c["per_core"],
                          "freq": c["freq"], "max_freq": c["max_freq"], "temp": temp},
            "memory": {"percent": round(mem.percent, 1),
                       "total_gb": round(mem.total / 2 ** 30, 1),
                       "used_gb": round(mem.used / 2 ** 30, 1),
                       "free_gb": round(mem.available / 2 ** 30, 1),
                       "swap_percent": round(swap.percent, 1) if swap else None,
                       "swap_used_gb": round(swap.used / 2 ** 30, 1) if swap else None,
                       "swap_total_gb": round(swap.total / 2 ** 30, 1) if swap else None},
            "storage": {"disks": disks, "physical": self.physical,
                        "read": c["read"], "write": c["write"]},
            "network": {"down": c["down"], "up": c["up"], **net},
            "graphics": s["gpus"],
            "battery_info": batinfo,
            "processes": procs,
            "history": {k: list(v) for k, v in self.history.items()},
        }

    def legacy(self):
        d = self.snapshot()
        if d.get("error"):
            return None
        return {k: d[k] for k in ("cpu", "ram", "disk", "ram_gb", "ram_total", "battery")}


MACHINE = Machine()
