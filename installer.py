#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calyx installer - graphical, multi-page (tkinter ships with Python: no dependency).

Pages : Home (Install Now / Custom Installation / License)  ->  Progress  ->  Result

Expected layout next to this file:
    calyx.py   LICENSE   assets/header.png  assets/windows.png  assets/linux.png  assets/macos.png
    examples/  (optional)

No display / no tkinter :   python3 installer.py --cli --target linux
"""
import os
import re
import sys
import stat
import shutil
import struct
import queue
import argparse
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
if os.name == "nt":
    CURRENT = "windows"
elif sys.platform == "darwin":
    CURRENT = "macos"
else:
    CURRENT = "linux"
TARGETS = {"windows": "Windows", "linux": "Linux", "macos": "macOS"}
BITS = struct.calcsize("P") * 8  # 64 ou 32 : architecture de Python, donc de Calyx


def read_version():
    try:
        with open(os.path.join(HERE, "calyx.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


VERSION = read_version()


def asset(name):
    return os.path.join(HERE, "assets", name)


def read_license():
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
        p = os.path.join(HERE, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                return f.read()
    return "No LICENSE file was found next to the installer."


# ----------------------------------------------------------------------
#  Dossiers par défaut selon le système
# ----------------------------------------------------------------------

def default_paths(target):
    if target != CURRENT:
        # Export : on prépare l'arborescence dans un dossier, à copier sur l'autre machine
        base = os.path.join(HOME, "Calyx-export-" + target)
        return {"install": os.path.join(base, "Calyx"), "modules": os.path.join(base, "modules"),
                "bin": os.path.join(base, "Calyx")}
    if target == "windows":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
        roam = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
        return {"install": os.path.join(local, "Calyx"),
                "modules": os.path.join(roam, "Calyx", "modules"),
                "bin": os.path.join(local, "Calyx")}
    return {"install": os.path.join(HOME, ".local", "share", "calyx"),
            "modules": os.path.join(HOME, ".calyx", "modules"),
            "bin": os.path.join(HOME, ".local", "bin")}


# ----------------------------------------------------------------------
#  Installation (utilisée par l'interface graphique ET par --cli)
# ----------------------------------------------------------------------

def add_to_windows_path(folder, log):
    import winreg
    import ctypes
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            cur, typ = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            cur, typ = "", winreg.REG_EXPAND_SZ
        parts = [p for p in cur.split(";") if p]
        if folder.lower().rstrip("\\") not in [p.lower().rstrip("\\") for p in parts]:
            parts.append(folder)
            winreg.SetValueEx(k, "Path", 0, typ, ";".join(parts))
            log("User PATH updated: " + folder)
        else:
            log("Folder already in PATH.")
    try:
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
    except Exception:
        pass


def add_to_unix_path(folder, log):
    if folder in os.environ.get("PATH", "").split(os.pathsep):
        log("Folder already in PATH.")
        return
    line = 'export PATH="%s:$PATH"  # Calyx' % folder.replace(HOME, "$HOME")
    always = [".profile"] + ([".zprofile"] if CURRENT == "macos" else [])
    for rc in (".profile", ".zprofile", ".bashrc", ".zshrc"):
        p = os.path.join(HOME, rc)
        if rc not in always and not os.path.exists(p):
            continue
        if rc == ".zprofile" and CURRENT != "macos" and not os.path.exists(p):
            continue
        try:
            txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
            if "# Calyx" not in txt:
                with open(p, "a", encoding="utf-8") as f:
                    f.write("\n" + line + "\n")
                log("PATH added to ~/" + rc)
        except OSError as e:
            log("Could not edit ~/%s: %s" % (rc, e))
    log("Open a new terminal so the 'calyx' command is recognised.")


def install(target, install_dir, modules_dir, bin_dir, add_path=True,
            with_examples=True, with_test_module=True, log=print, step=lambda n, total: None):
    src = os.path.join(HERE, "calyx.py")
    if not os.path.isfile(src):
        raise RuntimeError("calyx.py was not found next to the installer (%s)" % HERE)
    same_os = target == CURRENT
    total = 6
    defaults = default_paths(target)

    log("Target system: %s%s" % (TARGETS[target], "" if same_os else "  (export mode, system left untouched)"))
    step(1, total)

    for d in (install_dir, modules_dir, bin_dir):
        os.makedirs(d, exist_ok=True)
        log("Folder ready: " + d)
    step(2, total)

    dest = os.path.join(install_dir, "calyx.py")
    shutil.copy2(src, dest)
    log("Copied: " + dest)
    step(3, total)

    # lanceur
    custom_modules = same_os and os.path.normpath(modules_dir) != os.path.normpath(defaults["modules"])
    if target == "windows":
        lines = ["@echo off", "setlocal"]
        if custom_modules:
            lines.append('set "CALYX_MODULES=%s"' % modules_dir)
        lines += ["where py >nul 2>nul", "if not errorlevel 1 (",
                  '  py -3 "%~dp0calyx.py" %*', ") else (",
                  '  python "%~dp0calyx.py" %*', ")", "exit /b %errorlevel%"]
        launcher = os.path.join(bin_dir, "calyx.bat")
        with open(launcher, "w", newline="\r\n", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        lines = ["#!/bin/sh"]
        if custom_modules:
            lines.append('export CALYX_MODULES="%s"' % modules_dir)
        lines.append('exec python3 "%s" "$@"' % dest)
        launcher = os.path.join(bin_dir, "calyx")
        with open(launcher, "w", newline="\n", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log("Launcher created: " + launcher)
    step(4, total)

    # licence, exemples + module de démonstration
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
        if os.path.isfile(os.path.join(HERE, name)):
            shutil.copy2(os.path.join(HERE, name), os.path.join(install_dir, name))
            break
    ex_src = os.path.join(HERE, "examples")
    if with_examples and os.path.isdir(ex_src):
        ex_dst = os.path.join(install_dir, "examples")
        shutil.copytree(ex_src, ex_dst, dirs_exist_ok=True)
        log("Examples copied: " + ex_dst)
    test_src = os.path.join(ex_src, "test.cx")
    if with_test_module and os.path.isfile(test_src):
        shutil.copy2(test_src, os.path.join(modules_dir, "test.cx"))
        log("Sample module installed: 'use test;' now works in every project")
    step(5, total)

    # PATH
    if add_path and same_os:
        try:
            if target == "windows":
                add_to_windows_path(bin_dir, log)
            else:
                add_to_unix_path(bin_dir, log)
        except Exception as e:
            log("PATH not modified (%s). Add %s to your PATH manually." % (e, bin_dir))
    elif add_path:
        log("Export mode: PATH untouched. Copy the folder to the target machine.")
    step(6, total)
    log("")
    log("Program : " + install_dir)
    log("Modules : " + modules_dir)
    log("Command : " + launcher)
    return launcher


# ----------------------------------------------------------------------
#  Interface graphique
# ----------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog
    from tkinter import font as tkfont

    if os.name == "nt":  # texte net sur écrans haute résolution
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    BG, CARD, HOVER, ACCENT = "#f3f4f6", "#ffffff", "#eef2ff", "#6d28d9"
    OK, KO, MUTED = "#15803d", "#b91c1c", "#667085"

    root = tk.Tk()
    root.title("Calyx %s Setup" % VERSION)
    root.configure(bg=BG)
    root.resizable(False, False)
    w, h = 700, 660
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (root.winfo_screenwidth() - w) // 2),
                                   max(0, (root.winfo_screenheight() - h) // 3)))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    for s in ("TFrame", "TLabel", "TLabelframe", "TCheckbutton", "TRadiobutton"):
        style.configure(s, background=BG)
    style.configure("TLabelframe.Label", background=BG, foreground="#111827")
    style.configure("Horizontal.TProgressbar", troughcolor="#e5e7eb", background=ACCENT, thickness=18)
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", padding=(18, 6))
    style.map("Accent.TButton", background=[("active", "#5b21b6"), ("disabled", "#c4b5fd")])
    style.configure("TButton", padding=(14, 6))

    base = tkfont.nametofont("TkDefaultFont")
    f_title, f_head, f_small, f_big = base.copy(), base.copy(), base.copy(), base.copy()
    f_title.configure(size=17, weight="bold")
    f_head.configure(size=12, weight="bold")
    f_small.configure(size=9)
    f_big.configure(size=42, weight="bold")

    images = []  # garder les références (sinon Tk les efface)

    def load_img(name, max_h=None):
        path = asset(name)
        if not os.path.isfile(path):
            return None
        try:
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
        if max_h and img.height() > max_h:
            img = img.subsample(-(-img.height() // max_h))
        images.append(img)
        return img

    # ---------- pages empilées, on affiche celle du dessus
    container = tk.Frame(root, bg=BG)
    container.pack(fill="both", expand=True)
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)
    pages = {}

    def new_page(name):
        p = tk.Frame(container, bg=BG)
        p.grid(row=0, column=0, sticky="nsew")
        pages[name] = p
        return p

    def show(name):
        pages[name].tkraise()

    def title(parent, text):
        tk.Label(parent, text=text, font=f_title, bg=BG, fg="#111827", anchor="w").pack(fill="x", pady=(0, 10))

    def readonly_text(parent, height=10):
        box = tk.Frame(parent, bg=BG)
        sb = ttk.Scrollbar(box, orient="vertical")
        txt = tk.Text(box, height=height, wrap="word", state="disabled", relief="flat", bd=1,
                      highlightthickness=1, highlightbackground="#d0d5dd", yscrollcommand=sb.set,
                      font=f_small, bg="#ffffff")
        sb.config(command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        def set_text(content):
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", content)
            txt.config(state="disabled")

        def append(line):
            txt.config(state="normal")
            txt.insert("end", line + "\n")
            txt.see("end")
            txt.config(state="disabled")
        return box, set_text, append

    def card(parent, heading, sub, icon, command):
        f = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground="#d0d5dd", cursor="hand2")
        f.pack(fill="x", pady=6)
        slot = tk.Frame(f, width=68, height=64, bg=CARD)
        slot.pack_propagate(False)
        slot.pack(side="left", padx=(10, 4), pady=8)
        if icon is not None:
            tk.Label(slot, image=icon, bg=CARD).pack(expand=True)
        text = tk.Frame(f, bg=CARD)
        text.pack(side="left", fill="x", expand=True, pady=8)
        l1 = tk.Label(text, text=heading, font=f_head, bg=CARD, fg="#111827", anchor="w")
        l1.pack(fill="x")
        l2 = tk.Label(text, text=sub, font=f_small, bg=CARD, fg=MUTED, anchor="w", justify="left", wraplength=520)
        l2.pack(fill="x")
        arrow = tk.Label(f, text="\u203a", font=f_title, bg=CARD, fg="#98a2b3")
        arrow.pack(side="right", padx=14)
        parts = [f, slot, text, l1, l2, arrow] + list(slot.winfo_children())

        def paint(color):
            for wdg in parts:
                wdg.configure(bg=color)

        for wdg in parts:
            wdg.bind("<Button-1>", lambda e: command())
            wdg.bind("<Enter>", lambda e: paint(HOVER))
            wdg.bind("<Leave>", lambda e: paint(CARD))
        return f

    # ==================================================================
    #  Page 1 : accueil
    # ==================================================================
    home = new_page("home")
    header = load_img("header.png")
    if header is not None:
        tk.Label(home, image=header, bd=0, bg=BG).pack(fill="x")
    else:
        band = tk.Frame(home, bg=ACCENT, height=100)
        band.pack(fill="x")
        tk.Label(band, text="Calyx", font=f_title, bg=ACCENT, fg="#ffffff").place(relx=0.5, rely=0.5, anchor="center")

    foot = tk.Frame(home, bg=BG)
    foot.pack(fill="x", padx=28, pady=(0, 16), side="bottom")
    ttk.Button(foot, text="Quit", command=root.destroy).pack(side="right")

    body = tk.Frame(home, bg=BG)
    body.pack(fill="both", expand=True, padx=28, pady=(18, 10))
    title(body, "Install Calyx %s (%d-bit)" % (VERSION, BITS))

    def install_now():
        p = default_paths(CURRENT)
        start_install(CURRENT, p["install"], p["modules"], p["bin"], True, True, True)

    card(body, "Install Now",
         "Recommended \u2014 installs for %s with the default settings" % TARGETS[CURRENT],
         load_img(CURRENT + ".png", 56), install_now)
    card(body, "Custom Installation",
         "Choose the operating system, the folders and the options", None, lambda: show("custom"))
    card(body, "License", "Read the license of the project", None, lambda: show("license"))

    # ==================================================================
    #  Page 2 : installation personnalisée
    # ==================================================================
    custom = new_page("custom")
    cfoot = tk.Frame(custom, bg=BG)
    cfoot.pack(fill="x", padx=28, pady=(0, 16), side="bottom")
    cbody = tk.Frame(custom, bg=BG)
    cbody.pack(fill="both", expand=True, padx=28, pady=(22, 10))
    title(cbody, "Custom Installation")

    target = tk.StringVar(value=CURRENT)
    v_install, v_modules, v_bin = tk.StringVar(), tk.StringVar(), tk.StringVar()
    v_path, v_examples, v_test = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)

    osbox = ttk.LabelFrame(cbody, text="Operating system", padding=10)
    osbox.pack(fill="x")
    warn = tk.Label(cbody, text="", fg="#b45309", bg=BG, font=f_small, wraplength=620, justify="left", anchor="w")

    def refresh(*_):
        p = default_paths(target.get())
        v_install.set(p["install"])
        v_modules.set(p["modules"])
        v_bin.set(p["bin"])
        warn.config(text="" if target.get() == CURRENT else
                    "This is not the current system: the installer will prepare a folder to copy to the other machine.")

    for key, label in TARGETS.items():
        ttk.Radiobutton(osbox, text=" " + label, value=key, variable=target, command=refresh,
                        image=load_img(key + ".png", 32), compound="left").pack(side="left", padx=(0, 24))
    warn.pack(fill="x", pady=(4, 0))

    fbox = ttk.LabelFrame(cbody, text="Folders", padding=10)
    fbox.pack(fill="x", pady=8)
    fbox.columnconfigure(1, weight=1)

    def row(r, text, var):
        ttk.Label(fbox, text=text).grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(fbox, textvariable=var).grid(row=r, column=1, sticky="ew", padx=8)

        def browse():
            d = filedialog.askdirectory(initialdir=var.get() if os.path.isdir(var.get()) else HOME)
            if d:
                var.set(os.path.normpath(d))
        ttk.Button(fbox, text="Browse\u2026", command=browse).grid(row=r, column=2)

    row(0, "Program", v_install)
    row(1, "Modules (all projects)", v_modules)
    row(2, "'calyx' command", v_bin)

    obox = ttk.LabelFrame(cbody, text="Options", padding=10)
    obox.pack(fill="x")
    ttk.Checkbutton(obox, text="Add the 'calyx' command to the PATH", variable=v_path).pack(anchor="w")
    ttk.Checkbutton(obox, text="Copy the example programs", variable=v_examples).pack(anchor="w")
    ttk.Checkbutton(obox, text="Install the sample module 'test'  (use test;)", variable=v_test).pack(anchor="w")

    ttk.Button(cfoot, text="Install", style="Accent.TButton",
               command=lambda: start_install(target.get(), v_install.get().strip(), v_modules.get().strip(),
                                             v_bin.get().strip(), v_path.get(), v_examples.get(),
                                             v_test.get())).pack(side="right")
    ttk.Button(cfoot, text="Back", command=lambda: show("home")).pack(side="right", padx=8)
    refresh()

    # ==================================================================
    #  Page 3 : licence
    # ==================================================================
    lic = new_page("license")
    lfoot = tk.Frame(lic, bg=BG)
    lfoot.pack(fill="x", padx=28, pady=(0, 16), side="bottom")
    ttk.Button(lfoot, text="Back", command=lambda: show("home")).pack(side="right")
    lbody = tk.Frame(lic, bg=BG)
    lbody.pack(fill="both", expand=True, padx=28, pady=(22, 10))
    title(lbody, "License")
    lbox, lset, _ = readonly_text(lbody, height=20)
    lbox.pack(fill="both", expand=True)
    lset(read_license())

    # ==================================================================
    #  Page 4 : progression
    # ==================================================================
    prog = new_page("progress")
    pbody = tk.Frame(prog, bg=BG)
    pbody.pack(fill="both", expand=True, padx=28, pady=(40, 10))
    title(pbody, "Installing Calyx %s\u2026" % VERSION)
    v_status = tk.StringVar(value="Preparing\u2026")
    tk.Label(pbody, textvariable=v_status, bg=BG, fg=MUTED, anchor="w", font=f_small).pack(fill="x", pady=(0, 8))
    bar = ttk.Progressbar(pbody, maximum=6, mode="determinate")
    bar.pack(fill="x", pady=(0, 16))
    pbox, pset, pappend = readonly_text(pbody, height=14)
    pbox.pack(fill="both", expand=True)

    # ==================================================================
    #  Page 5 : résultat (validation ou erreur)
    # ==================================================================
    res = new_page("result")
    rfoot = tk.Frame(res, bg=BG)
    rfoot.pack(fill="x", padx=28, pady=(0, 16), side="bottom")
    ttk.Button(rfoot, text="Close", style="Accent.TButton", command=root.destroy).pack(side="right")
    r_back = ttk.Button(rfoot, text="Back", command=lambda: show("home"))
    rbody = tk.Frame(res, bg=BG)
    rbody.pack(fill="both", expand=True, padx=28, pady=(40, 10))
    r_icon = tk.Label(rbody, text="", font=f_big, bg=BG)
    r_icon.pack()
    r_title = tk.Label(rbody, text="", font=f_title, bg=BG)
    r_title.pack(pady=(0, 4))
    r_msg = tk.Label(rbody, text="", bg=BG, fg=MUTED, wraplength=620, justify="center")
    r_msg.pack(pady=(0, 14))
    rbox, rset, _ = readonly_text(rbody, height=12)
    rbox.pack(fill="both", expand=True)

    # ==================================================================
    #  Lancement de l'installation (thread + file de messages)
    # ==================================================================
    events = queue.Queue()
    state = {"log": [], "running": False}

    def start_install(tgt, inst, mods, bin_, add_path, examples, test_mod):
        if not (inst and mods and bin_):
            show_result(False, "Please fill in all the folders.", "")
            return
        state["log"] = []
        state["running"] = True
        bar["value"] = 0
        v_status.set("Preparing\u2026")
        pset("")
        show("progress")

        def work():
            try:
                def log(m):
                    events.put(("log", m))

                def step(n, total):
                    events.put(("step", n))
                    time.sleep(0.25)  # laisse voir la jauge avancer
                launcher = install(tgt, inst, mods, bin_, add_path, examples, test_mod, log, step)
                events.put(("done", launcher))
            except Exception as e:  # noqa: BLE001
                events.put(("error", "%s: %s" % (type(e).__name__, e)))

        threading.Thread(target=work, daemon=True).start()
        root.after(50, poll)

    def poll():
        try:
            while True:
                kind, *data = events.get_nowait()
                if kind == "log":
                    state["log"].append(data[0])
                    pappend(data[0])
                    if data[0].strip():
                        v_status.set(data[0])
                elif kind == "step":
                    bar["value"] = data[0]
                elif kind == "done":
                    state["running"] = False
                    bar["value"] = 6
                    root.after(400, lambda: show_result(
                        True, "Open a new terminal and type:  calyx --version", "\n".join(state["log"])))
                elif kind == "error":
                    state["running"] = False
                    show_result(False, data[0], "\n".join(state["log"]))
        except queue.Empty:
            pass
        if state["running"]:
            root.after(50, poll)

    def show_result(ok, message, details):
        if ok:
            r_icon.config(text="\u2714", fg=OK)
            r_title.config(text="Installation complete", fg=OK)
            r_back.pack_forget()
        else:
            r_icon.config(text="\u2716", fg=KO)
            r_title.config(text="Installation failed", fg=KO)
            r_back.pack(side="right", padx=8)
        r_msg.config(text=message)
        rset(details)
        show("result")

    show("home")
    root.mainloop()


# ----------------------------------------------------------------------
#  Mode texte (secours)
# ----------------------------------------------------------------------

def run_cli(args):
    target = args.target or CURRENT
    p = default_paths(target)
    print("Install Calyx %s (%d-bit)" % (VERSION, BITS))
    install(target, args.dir or p["install"], args.modules or p["modules"], args.bin or p["bin"],
            add_path=not args.no_path)
    print("Installation complete.")


def main():
    ap = argparse.ArgumentParser(description="Calyx installer")
    ap.add_argument("--cli", action="store_true", help="text mode, no graphical interface")
    ap.add_argument("--target", choices=list(TARGETS), help="target system")
    ap.add_argument("--dir", help="installation folder")
    ap.add_argument("--modules", help="universal modules folder")
    ap.add_argument("--bin", help="folder of the 'calyx' launcher")
    ap.add_argument("--no-path", action="store_true", help="do not modify the PATH")
    args = ap.parse_args()
    if args.cli:
        return run_cli(args)
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("tkinter is not available (Linux: install the 'python3-tk' package).")
        print("Falling back to text mode...\n")
        return run_cli(args)
    run_gui()


if __name__ == "__main__":
    main()
