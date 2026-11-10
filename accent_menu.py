#!/usr/bin/env python3
"""Menu de acentos: Ctrl+Alt+<letra> abre um menu; 1-9 escolhe (Shift = maiúscula).

Linux:   `accent_menu.py --install` registra os atalhos no KDE; cada atalho roda
         `accent_menu.py <letra>`. O caractere é inserido via clipboard + Shift+Insert
         simulado por /dev/uinput (funciona em Wayland e X11, qualquer aplicação).
         Para abrir no cursor de texto, `--input-method` roda como método de entrada
         do KWin: um painel invisível que o KWin posiciona no cursor de texto.
Windows: `pythonw accent_menu.py` fica residente com RegisterHotKey e digita o
         caractere com SendInput(KEYEVENTF_UNICODE). `--install` adiciona ao Startup.
"""
import array
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk

# Edite aqui. Depois de mudar letras/atalho, rode `--install` de novo.
ACCENTS = {
    "a": "áàâãä",
    "e": "éêèë",
    "i": "íìîï",
    "o": "óôõòö",
    "u": "úùûü",
    "c": "ç",
    "n": "ñ",
}
MODIFIERS = ("ctrl", "alt")

SCRIPT = os.path.abspath(__file__)


# ---------------------------------------------------------------- menu (Tk)

# Paleta escura (combina com Breeze Dark) e fonte do sistema.
COLORS = {
    "bg": "#1c1d23", "border": "#363844", "tile": "#272932", "accent": "#3daee9",
    "text": "#eef0f5", "muted": "#7d8192", "on_accent": "#0d1b24",
}
FONT = "Segoe UI" if sys.platform == "win32" else "Noto Sans"
TILE_W, TILE_H, GAP, PAD = 34, 42, 3, 4


def _round_rect(canvas, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, outline="", **kw)


def show_menu(letter, anchor=None):
    """Mostra o menu da letra e retorna o caractere escolhido (ou None).

    anchor: (x, y, altura) do cursor de texto na tela, ou uma função que o retorna
    (chamada com a janela já montada, para a busca rodar em paralelo com o Tk). O menu
    abre logo acima do ponto; sem espaço, abaixo. None: o gerenciador de janelas decide.
    """
    chars = ACCENTS[letter]
    result = None
    state = {"sel": 0, "upper": False}

    # O Tk capitaliza a classe: WM_CLASS vira "Accent-menu", que é o que a regra do KWin casa.
    root = tk.Tk(className="accent-menu")
    root.title(f"Acentos: {letter}")
    root.withdraw()  # só aparece depois de posicionado
    root.resizable(False, False)
    root.attributes("-topmost", True)
    if sys.platform == "win32":
        root.overrideredirect(True)  # no KDE quem tira a borda é a regra do KWin

    k = root.winfo_fpixels("1i") / 96  # escala para telas HiDPI (Windows DPI-aware)
    tile_w, tile_h, gap, pad = (round(v * k) for v in (TILE_W, TILE_H, GAP, PAD))
    width = len(chars) * tile_w + (len(chars) - 1) * gap + 2 * pad
    height = tile_h + 2 * pad
    cv = tk.Canvas(root, width=width, height=height, bg=COLORS["bg"], bd=0,
                   highlightthickness=1, highlightbackground=COLORS["border"])
    cv.pack()

    tiles = []  # (retângulo, glifo, número)
    x = pad + 1
    for i, ch in enumerate(chars):
        tag = f"tile{i}"
        rect = _round_rect(cv, x, pad + 1, x + tile_w, pad + 1 + tile_h, 7 * k, tags=tag)
        glyph = cv.create_text(x + tile_w / 2, pad + 17 * k, font=(FONT, 14), tags=tag)
        num = cv.create_text(x + tile_w / 2, pad + tile_h - 6 * k, text=str(i + 1),
                             font=(FONT, 7, "bold"), tags=tag)
        cv.tag_bind(tag, "<Enter>", lambda e, i=i: select(i))
        cv.tag_bind(tag, "<Button-1>", lambda e, i=i: choose(i))
        tiles.append((rect, glyph, num))
        x += tile_w + gap

    def render():
        for i, (rect, glyph, num) in enumerate(tiles):
            on = i == state["sel"]
            ch = chars[i].upper() if state["upper"] else chars[i]
            cv.itemconfig(rect, fill=COLORS["accent" if on else "tile"])
            cv.itemconfig(glyph, text=ch, fill=COLORS["on_accent" if on else "text"])
            cv.itemconfig(num, fill=COLORS["on_accent" if on else "muted"])

    def select(i):
        state["sel"] = i % len(chars)
        render()

    def set_upper(upper):
        state["upper"] = upper
        render()

    def choose(i, upper=None):
        nonlocal result
        upper = state["upper"] if upper is None else upper
        result = chars[i].upper() if upper else chars[i]
        root.destroy()

    def on_key(event):
        k = event.keysym
        if k == "Escape":
            return root.destroy()
        if k in ("Shift_L", "Shift_R"):
            return set_upper(True)
        if k in ("Left", "Right"):
            return select(state["sel"] + (1 if k == "Right" else -1))
        if k in ("Return", "KP_Enter", "space"):
            return choose(state["sel"])
        n = _digit(event)
        if n and n <= len(chars):
            choose(n - 1, upper=bool(event.state & 0x1))

    def on_release(event):
        if event.keysym in ("Shift_L", "Shift_R"):
            set_upper(False)

    render()
    root.bind("<KeyPress>", on_key)
    root.bind("<KeyRelease>", on_release)
    root.bind("<FocusOut>", lambda e: e.widget is root and root.destroy())
    if callable(anchor):
        anchor = anchor()
    if anchor:
        ax, ay, ah = anchor
        left, top, right, _ = _screen_bounds(root, ax, ay)
        margin = round(6 * k)
        y = ay - height - margin
        if y < top:  # sem espaço acima: abaixo do cursor (ou do ponteiro do mouse)
            y = ay + (ah or round(20 * k)) + margin
        x = min(max(ax - pad - tile_w // 2, left), right - width)
        root.geometry(f"+{x}+{y}")
    root.deiconify()
    root.after(10, root.focus_force)
    root.after(15000, root.destroy)  # nunca fica preso na tela se não ganhar o foco
    root.mainloop()
    return result


def _screen_bounds(root, x, y):
    """(esq, topo, dir, base) do monitor que contém o ponto. No Linux/XWayland a tela
    X cobre todos os monitores; no Windows pega a área útil do monitor certo."""
    if sys.platform != "win32":
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromPoint(wintypes.POINT(x, y), 2), ctypes.byref(info))
    r = info.rcWork  # 2 = MONITOR_DEFAULTTONEAREST
    return r.left, r.top, r.right, r.bottom


def _digit(event):
    """Dígito 1-9 pela tecla física, para funcionar também com Shift (que vira '!')."""
    if event.keysym.startswith("KP_") and event.keysym[3:].isdigit():
        return int(event.keysym[3:])
    # Keycode da fileira de números: X11 1..9 = 10..18, Windows VK '1'..'9' = 49..57.
    n = event.keycode - (48 if sys.platform == "win32" else 9)
    return n if 1 <= n <= 9 else None


# ---------------------------------------------------------------- Linux

# Comandos de clipboard: (listar tipos, ler tipo, escrever tipo) por seleção.
def _clip_cmds(selection):
    if os.environ.get("WAYLAND_DISPLAY"):
        p = ["--primary"] if selection == "primary" else []
        return (["wl-paste", *p, "--list-types"],
                lambda t: ["wl-paste", *p, "--no-newline", "--type", t],
                lambda t: ["wl-copy", *p, "--type", t])
    s = ["-selection", selection]
    return (["xclip", "-o", *s, "-t", "TARGETS"],
            lambda t: ["xclip", "-o", *s, "-t", t],
            lambda t: ["xclip", "-i", *s, "-t", t])


def _clip_save(selection):
    list_cmd, read_cmd, _ = _clip_cmds(selection)
    types = subprocess.run(list_cmd, capture_output=True, text=True).stdout.split()
    types = [t for t in types if "/" in t]  # descarta TARGETS, TIMESTAMP etc. do X11
    if not types:
        return None
    data = subprocess.run(read_cmd(types[0]), capture_output=True).stdout
    return types[0], data


def _clip_set_all(items):
    """items: {seleção: (mime, bytes)}. Escreve todas em paralelo."""
    procs = []
    for selection, (mime, data) in items.items():
        _, _, write_cmd = _clip_cmds(selection)
        p = subprocess.Popen(write_cmd(mime), stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.stdin.write(data)
        p.stdin.close()
        procs.append(p)
    for p in procs:
        p.wait()  # wl-copy/xclip fazem fork e seguem servindo; o pai sai logo


# linux/uinput.h
UI_SET_EVBIT, UI_SET_KEYBIT = 0x40045564, 0x40045565
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
EV_SYN, EV_KEY = 0, 1
KEY_LEFTSHIFT, KEY_INSERT = 42, 110


def uinput_open(keys):
    """Cria um teclado virtual que só tem `keys`. Retorna o fd."""
    import fcntl
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    for k in keys:
        fcntl.ioctl(fd, UI_SET_KEYBIT, k)
    # struct uinput_user_dev: name[80], input_id, ff_effects_max, abs*[64] x4
    os.write(fd, struct.pack("80sHHHHi", b"accent-menu", 3, 1, 1, 1, 0) + bytes(64 * 4 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(0.15)  # o compositor precisa enxergar o dispositivo novo
    return fd


def uinput_tap(fd, keys):
    """Pressiona as teclas em ordem e solta na ordem inversa."""
    def emit(type_, code, value):
        os.write(fd, struct.pack("llHHi", 0, 0, type_, code, value))
    for k in keys:
        emit(EV_KEY, k, 1)
        emit(EV_SYN, 0, 0)
    for k in reversed(keys):
        emit(EV_KEY, k, 0)
        emit(EV_SYN, 0, 0)


def uinput_close(fd):
    import fcntl
    time.sleep(0.05)  # deixa o compositor consumir os eventos antes de sumir com o device
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)


def press_keys(*keys):
    fd = uinput_open(keys)
    try:
        uinput_tap(fd, keys)
    finally:
        uinput_close(fd)


# ---- posição do cursor de texto: método de entrada Wayland
#
# No Wayland só o método de entrada sabe onde fica o cursor de texto de outro app.
# `--input-method` é um método de entrada mínimo (zwp_input_method_v1, iniciado pelo
# KWin) que só cria um painel "overlay" de 1x1 transparente: o KWin coloca esse painel
# no cursor de texto do app com foco. O menu lê a posição do painel pelo KWin.

IM_STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "accent-menu-im-active")
CARET_H = 20  # altura presumida da linha: o KWin põe o painel logo abaixo do cursor


class _Wayland:
    """O suficiente do protocolo Wayland (formato binário sobre socket unix)."""

    def __init__(self, sock):
        self.sock, self.buf, self.last_id = sock, b"", 1  # 1 = wl_display

    def new_id(self):
        self.last_id += 1
        return self.last_id

    def send(self, obj, opcode, *args, fds=()):
        payload = b"".join(a if isinstance(a, bytes) else struct.pack("<i", a) for a in args)
        msg = struct.pack("<II", obj, ((8 + len(payload)) << 16) | opcode) + payload
        anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))] if fds else []
        self.sock.sendmsg([msg], anc)

    def events(self):
        data = self.sock.recv(65536)
        if not data:
            raise EOFError("o compositor fechou a conexão")
        self.buf += data
        while len(self.buf) >= 8:
            obj, word = struct.unpack_from("<II", self.buf)
            size = word >> 16
            if len(self.buf) < size:
                break
            yield obj, word & 0xFFFF, self.buf[8:size]
            self.buf = self.buf[size:]

    @staticmethod
    def string(text):
        b = text.encode() + b"\0"
        return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


def run_input_method():
    """Método de entrada: mantém o painel invisível e grava se há texto ativo."""
    def set_active(active):
        with open(IM_STATE, "w") as f:
            f.write("1" if active else "0")

    w = _Wayland(socket.socket(fileno=int(os.environ.pop("WAYLAND_SOCKET"))))
    registry, sync = w.new_id(), w.new_id()
    w.send(1, 1, registry)  # wl_display.get_registry
    w.send(1, 0, sync)  # wl_display.sync: avisa quando a lista de globais terminou
    globals_, listing = {}, True
    while listing:
        for obj, op, p in w.events():
            if obj == registry and op == 0:  # global(name, interface, version)
                n = struct.unpack_from("<I", p, 4)[0]
                globals_[p[8:8 + n - 1].decode()] = struct.unpack_from("<I", p)[0]
            listing = listing and obj != sync

    def bind(iface):
        obj = w.new_id()
        w.send(registry, 0, globals_[iface], w.string(iface), 1, obj)  # versão 1 basta
        return obj

    compositor, shm = bind("wl_compositor"), bind("wl_shm")
    panel, im = bind("zwp_input_panel_v1"), bind("zwp_input_method_v1")

    fd = os.memfd_create("accent-menu-panel")
    os.ftruncate(fd, 4)  # 1 pixel ARGB8888 transparente (memfd começa zerado)
    pool, buffer, surface, region, panel_surface = (w.new_id() for _ in range(5))
    w.send(shm, 0, pool, 4, fds=[fd])  # wl_shm.create_pool
    w.send(pool, 0, buffer, 0, 1, 1, 4, 0)  # create_buffer(offset, w, h, stride, ARGB8888)
    w.send(compositor, 0, surface)  # create_surface
    w.send(compositor, 1, region)  # create_region: vazia, cliques atravessam o painel
    w.send(surface, 5, region)  # set_input_region
    w.send(panel, 0, panel_surface, surface)  # get_input_panel_surface
    w.send(panel_surface, 1)  # set_overlay_panel: o KWin posiciona no cursor de texto
    w.send(surface, 1, buffer, 0, 0)  # attach
    w.send(surface, 6)  # commit
    set_active(False)
    while True:
        for obj, op, p in w.events():
            if obj == im and op == 0:  # activate(contexto)
                set_active(True)
            elif obj == im and op == 1:  # deactivate(contexto): o cliente destrói o contexto
                set_active(False)
                w.send(struct.unpack_from("<I", p)[0], 0)
            elif obj == 1 and op == 0:  # wl_display.error
                sys.exit(f"erro do compositor: {p!r}")


KWIN_QUERY_JS = """
const a = workspace.activeWindow, c = workspace.cursorPos;
let panel = null;
for (const w of workspace.windowList())
  if (w.inputMethod && !w.hidden) panel = [w.frameGeometry.x, w.frameGeometry.y];
callDBus("%s", "/", "org.accentmenu.Probe", "Result", JSON.stringify({
  cursor: [c.x, c.y], panel: panel,
  client: a ? [a.clientGeometry.x, a.clientGeometry.y] : null}));
"""


def _kwin_query():
    """{'cursor', 'panel', 'client'} do KWin, via um script KWin temporário."""
    import warnings
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    result = {}
    loop = GLib.MainLoop()

    def on_call(conn, sender, path, iface, method, params, invocation):
        result.update(json.loads(params.unpack()[0]))
        invocation.return_value(None)
        loop.quit()

    node = Gio.DBusNodeInfo.new_for_xml(
        '<node><interface name="org.accentmenu.Probe"><method name="Result">'
        '<arg type="s" direction="in"/></method></interface></node>')
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        reg = bus.register_object("/", node.interfaces[0], on_call, None, None)
    plugin = f"accent-menu-{os.getpid()}"
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), plugin + ".js")
    with open(path, "w") as f:
        f.write(KWIN_QUERY_JS % bus.get_unique_name())

    def call(obj, iface, method, args=None, reply=None):
        return bus.call_sync("org.kde.KWin", obj, iface, method, args,
                             reply and GLib.VariantType(reply), 0, 500, None)
    try:
        sid = call("/Scripting", "org.kde.kwin.Scripting", "loadScript",
                   GLib.Variant("(ss)", (path, plugin)), "(i)").unpack()[0]
        call(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
        GLib.timeout_add(300, loop.quit)
        loop.run()
        call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", GLib.Variant("(s)", (plugin,)))
    finally:
        os.remove(path)
        bus.unregister_object(reg)
    return result or None


def _linux_anchor():
    """Posição do cursor de texto na tela; sem ela, a do mouse. None fora do KDE."""
    try:
        kwin = _kwin_query()
    except Exception:
        return None
    if not kwin:
        return None
    try:
        with open(IM_STATE) as f:
            typing = f.read() == "1"
    except OSError:
        typing = False
    # Painel na origem exata da janela = o app ainda não informou o cursor de texto.
    if typing and kwin["panel"] and kwin["panel"] != kwin["client"]:
        x, y = kwin["panel"]
        return x, y - CARET_H, CARET_H
    return kwin["cursor"][0], kwin["cursor"][1], 0


PASTE_KEYS = (KEY_LEFTSHIFT, KEY_INSERT)
SELECTIONS = ("clipboard", "primary")


def run_linux(letter):
    # Em paralelo com a abertura do menu: acha o cursor de texto e, enquanto o menu
    # está aberto, cria o teclado virtual (~150 ms até o compositor reconhecer) e
    # salva o clipboard atual.
    found = {}
    locator = threading.Thread(target=lambda: found.update(anchor=_linux_anchor()))
    locator.start()
    prep = {}
    worker = threading.Thread(target=lambda: prep.update(
        fd=uinput_open(PASTE_KEYS), saved={s: _clip_save(s) for s in SELECTIONS}))
    worker.start()
    choice = show_menu(letter, anchor=lambda: (locator.join(), found.get("anchor"))[1])
    worker.join()
    if "saved" not in prep:
        sys.exit("Falha ao preparar a colagem (sem acesso a /dev/uinput?). Rode --install.")
    try:
        if not choice:
            return
        # Shift+Insert cola o CLIPBOARD na maioria dos apps e a PRIMARY em alguns
        # terminais; por isso preenchemos as duas e restauramos depois.
        _clip_set_all({s: ("text/plain;charset=utf-8", choice.encode()) for s in SELECTIONS})
        time.sleep(0.03)  # a janela anterior recupera o foco
        uinput_tap(prep["fd"], PASTE_KEYS)
    finally:
        uinput_close(prep["fd"])
    time.sleep(0.3)  # o app lê o clipboard de forma assíncrona
    _clip_set_all({s: item for s, item in prep["saved"].items() if item})


QT_MODS = {"ctrl": 0x04000000, "shift": 0x02000000, "alt": 0x08000000, "meta": 0x10000000}
KGLOBALACCEL = ["gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel",
                "--object-path", "/kglobalaccel", "--method"]
APPS_DIR = os.path.expanduser("~/.local/share/applications")


def _kde_action(letter):
    name = f"accent-menu-{letter}.desktop"
    return name, f"['{name}', '_launch', 'Acentos {letter}', 'Acentos {letter}']"


KWIN_RULE = "accent-menu"
MISSING = "<ausente>"
# Regra do KWin para a janela do menu: sem borda, fora da barra de tarefas/Alt+Tab e
# sem prevenção de roubo de foco. (2 = forçar; wmclassmatch 1 = exato)
KWIN_RULE_KEYS = {
    "Description": "Menu de acentos", "wmclass": "Accent-menu", "wmclassmatch": "1",
    "noborder": "true", "noborderrule": "2", "skiptaskbar": "true", "skiptaskbarrule": "2",
    "skipswitcher": "true", "skipswitcherrule": "2", "skippager": "true", "skippagerrule": "2",
    "fsplevel": "0", "fsplevelrule": "2",
}
# Chaves que versões anteriores gravavam (placement) ou que o KWin cria ao migrar a regra.
KWIN_STALE_KEYS = ("placement", "placementrule")
KWIN_MIGRATED_KEYS = ("decorationpolicy", "decorationpolicyrule")


def _kwin_rule(enable):
    cfg = ["--file", "kwinrulesrc", "--group"]

    def write(group, key, *value):
        subprocess.run(["kwriteconfig6", *cfg, group, "--key", key, *value], check=True)

    # Formato antigo: General/rules + count. O KWin 6.8 migra para General/Order
    # (e noborder -> decorationpolicy) na primeira leitura; tratamos os dois.
    for list_key in ("rules", "Order"):
        current = subprocess.run(["kreadconfig6", *cfg, "General", "--key", list_key,
                                  "--default", MISSING], capture_output=True, text=True).stdout.strip()
        if current == MISSING:
            if list_key == "Order":
                continue
            current = ""
        ids = [r for r in current.split(",") if r and r != KWIN_RULE] + ([KWIN_RULE] if enable else [])
        write("General", list_key, ",".join(ids))
        if list_key == "rules":
            write("General", "count", str(len(ids)))
    for key, value in KWIN_RULE_KEYS.items():
        write(KWIN_RULE, key, *([value] if enable else ["--delete"]))
    for key in KWIN_STALE_KEYS + (() if enable else KWIN_MIGRATED_KEYS):
        write(KWIN_RULE, key, "--delete")
    subprocess.run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/KWin",
                    "--method", "org.kde.KWin.reconfigure"], stdout=subprocess.DEVNULL)


IM_DESKTOP = os.path.join(APPS_DIR, "accent-menu-im.desktop")
KWINRC = ["--file", "kwinrc", "--group", "Wayland", "--key"]


def _set_input_method(enable):
    """Troca o método de entrada do KWin pelo nosso (guardando o anterior) ou o restaura."""
    def read(key):
        return subprocess.run(["kreadconfig6", *KWINRC, key, "--default", MISSING],
                              capture_output=True, text=True).stdout.strip()

    def write(key, *value):  # --notify: o KWin troca o método de entrada na hora
        subprocess.run(["kwriteconfig6", "--notify", *KWINRC, key, *value], check=True)

    current = read("InputMethod")
    if enable:
        with open(IM_DESKTOP, "w") as f:  # VirtualKeyboard=true: aparece nas Configurações
            f.write("[Desktop Entry]\nType=Application\nName=Accent menu\n"
                    f'Exec="{sys.executable}" "{SCRIPT}" --input-method\n'
                    "NoDisplay=true\nX-KDE-Wayland-VirtualKeyboard=true\n")
        if current != IM_DESKTOP:
            write("AccentMenuPreviousInputMethod", current)
            if current not in (MISSING, "") and "plasma.keyboard" not in current:
                print(f"AVISO: o método de entrada anterior ({current}) foi substituído; "
                      "--uninstall o restaura.")
            write("InputMethod", IM_DESKTOP)
        return
    previous = read("AccentMenuPreviousInputMethod")
    if current == IM_DESKTOP:
        write("InputMethod", *(["--delete"] if previous in (MISSING, "") else [previous]))
    write("AccentMenuPreviousInputMethod", "--delete")
    if os.path.exists(IM_DESKTOP):
        os.remove(IM_DESKTOP)


def install_linux():
    for tool in (("wl-copy", "wl-paste") if os.environ.get("WAYLAND_DISPLAY") else ("xclip",)):
        if not shutil.which(tool):
            print(f"AVISO: '{tool}' não encontrado (Fedora: sudo dnf install wl-clipboard / xclip)")
    if not os.access("/dev/uinput", os.W_OK):
        print("AVISO: sem permissão de escrita em /dev/uinput. Rode uma vez:\n"
              "  echo 'KERNEL==\"uinput\", TAG+=\"uaccess\"' | sudo tee /etc/udev/rules.d/70-uinput-accent-menu.rules\n"
              "  sudo udevadm control --reload && sudo udevadm trigger /dev/uinput")
    if not shutil.which("gdbus") or subprocess.run(
            KGLOBALACCEL + ["org.kde.KGlobalAccel.allMainComponents"], capture_output=True).returncode:
        print("KDE não detectado. Crie atalhos manualmente no seu ambiente:")
        for letter in ACCENTS:
            print(f"  {'+'.join(m.title() for m in MODIFIERS)}+{letter.upper()} -> "
                  f"{sys.executable} {SCRIPT} {letter}")
        return
    _kwin_rule(True)
    os.makedirs(APPS_DIR, exist_ok=True)
    _set_input_method(True)
    mods = sum(QT_MODS[m] for m in MODIFIERS)
    for letter in ACCENTS:
        name, action = _kde_action(letter)
        with open(os.path.join(APPS_DIR, name), "w") as f:
            f.write("[Desktop Entry]\nType=Application\n"
                    f"Name=Acentos {letter}\n"
                    f'Exec="{sys.executable}" "{SCRIPT}" {letter}\n'
                    "NoDisplay=true\nStartupNotify=false\n"
                    "X-KDE-GlobalAccel-CommandShortcut=true\n")
    # O kglobalaccel só aceita o .desktop depois que o cache de serviços o conhece.
    subprocess.run(["kbuildsycoca6"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for letter in ACCENTS:
        name, action = _kde_action(letter)
        key = mods | ord(letter.upper())
        label = f"{'+'.join(m.title() for m in MODIFIERS)}+{letter.upper()}"
        # Logo após recriar o .desktop, o KWin pode ainda não enxergá-lo e recusar o
        # registro em silêncio; por isso conferimos e tentamos de novo.
        for _ in range(20):
            subprocess.run(KGLOBALACCEL + ["org.kde.KGlobalAccel.doRegister", action], check=True,
                           stdout=subprocess.DEVNULL)
            # flags 2|4 = SetPresent (ativa) | NoAutoloading (grava este em vez do salvo)
            subprocess.run(KGLOBALACCEL + ["org.kde.KGlobalAccel.setShortcut", action, f"[{key}]", "6"],
                           check=True, stdout=subprocess.DEVNULL)
            owners = subprocess.run(KGLOBALACCEL + ["org.kde.KGlobalAccel.getGlobalShortcutsByKey", str(key)],
                                    capture_output=True, text=True).stdout
            if name in owners:
                print(f"{label} -> {ACCENTS[letter]}")
                break
            time.sleep(0.25)
        else:
            print(f"ERRO: o KDE não aceitou o atalho {label}. Rode --install de novo.")


def uninstall_linux():
    _kwin_rule(False)
    _set_input_method(False)
    for letter in ACCENTS:
        name, _ = _kde_action(letter)
        subprocess.run(KGLOBALACCEL + ["org.kde.KGlobalAccel.unregister", name, "_launch"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        path = os.path.join(APPS_DIR, name)
        if os.path.exists(path):
            os.remove(path)
    print("Atalhos removidos.")


# ---------------------------------------------------------------- Windows

def _send_unicode(text):
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):  # só para o union ter o tamanho correto
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP, INPUT_KEYBOARD = 0x4, 0x2, 1
    events = []
    for unit in struct.unpack(f"<{len(text.encode('utf-16-le')) // 2}H", text.encode("utf-16-le")):
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=unit, dwFlags=flags)))
    arr = (INPUT * len(events))(*events)
    ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


def _msaa_caret(hwnd):
    """Cursor de texto via MSAA (OBJID_CARET): Chrome, Edge, Firefox, Electron."""
    import ctypes
    from ctypes import wintypes

    class VARIANT(ctypes.Structure):  # só o necessário para VT_I4 = CHILDID_SELF
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("val", ctypes.c_void_p), ("val2", ctypes.c_void_p)]

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                    ("d4", ctypes.c_ubyte * 8)]

    iid_iaccessible = GUID(0x618736E0, 0x3C3D, 0x11CF,
                           (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71))
    OBJID_CARET, VT_I4 = -8, 3
    acc = ctypes.c_void_p()
    if ctypes.windll.oleacc.AccessibleObjectFromWindow(
            hwnd, OBJID_CARET, ctypes.byref(iid_iaccessible), ctypes.byref(acc)) or not acc:
        return None
    # Métodos COM pelo índice na vtable: Release = 2, IAccessible::accLocation = 22.
    acc_location = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *[ctypes.POINTER(wintypes.LONG)] * 4,
                                      VARIANT)(22, "accLocation")
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(2, "Release")
    x, y, w, h = (wintypes.LONG() for _ in range(4))
    try:
        hr = acc_location(acc, ctypes.byref(x), ctypes.byref(y), ctypes.byref(w), ctypes.byref(h),
                          VARIANT(vt=VT_I4))
    finally:
        release(acc)
    if hr or (x.value == y.value == h.value == 0):
        return None
    return x.value, y.value, h.value


def _caret_pos_windows(hwnd):
    """(x, y, altura) do cursor de texto da janela; sem cursor, a posição do mouse."""
    import ctypes
    from ctypes import wintypes

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT)]

    user32 = ctypes.windll.user32
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    pt = wintypes.POINT()
    thread = user32.GetWindowThreadProcessId(hwnd, None)
    if user32.GetGUIThreadInfo(thread, ctypes.byref(info)) and info.hwndCaret:
        pt.x, pt.y = info.rcCaret.left, info.rcCaret.top
        user32.ClientToScreen(info.hwndCaret, ctypes.byref(pt))
        return pt.x, pt.y, info.rcCaret.bottom - info.rcCaret.top
    caret = _msaa_caret(info.hwndFocus or hwnd)
    if caret:
        return caret
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y, 0


def run_windows():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    # Coordenadas reais de outros processos (MSAA) só batem com as nossas se formos DPI-aware.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    ctypes.windll.ole32.CoInitialize(None)  # MSAA precisa de COM para falar com outros processos
    win_mods = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "meta": 0x8}
    MOD_NOREPEAT, WM_HOTKEY = 0x4000, 0x0312
    mods = sum(win_mods[m] for m in MODIFIERS) | MOD_NOREPEAT
    letters = list(ACCENTS)
    registered = 0
    for i, letter in enumerate(letters, 1):
        if user32.RegisterHotKey(None, i, mods, ord(letter.upper())):
            registered += 1
        else:
            print(f"Não foi possível registrar o atalho da letra '{letter}' (já está em uso?)")
    if not registered:
        sys.exit("Nenhum atalho registrado (o programa já está rodando?)")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message != WM_HOTKEY:
            continue
        previous = user32.GetForegroundWindow()
        choice = show_menu(letters[msg.wParam - 1], anchor=_caret_pos_windows(previous))
        if choice:
            user32.SetForegroundWindow(previous)
            time.sleep(0.05)
            _send_unicode(choice)


def install_windows():
    startup = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
    path = os.path.join(startup, "accent-menu.pyw")
    with open(path, "w", encoding="utf-8") as f:  # caminhos com acento (C:\Users\João)
        f.write(f"import runpy\nrunpy.run_path({SCRIPT!r}, run_name='__main__')\n")
    print(f"Inicialização automática criada: {path}\n"
          f"Para iniciar agora: pythonw \"{SCRIPT}\"")


# ---------------------------------------------------------------- main

def main(args):
    windows = sys.platform == "win32"
    if args == ["--install"]:
        return install_windows() if windows else install_linux()
    if args == ["--uninstall"] and not windows:
        return uninstall_linux()
    if args == ["--input-method"] and not windows:
        return run_input_method()
    if not args and windows:
        return run_windows()
    if len(args) == 1 and args[0] in ACCENTS:
        if not windows:
            return run_linux(args[0])
        choice = show_menu(args[0])
        if choice:
            _send_unicode(choice)
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
