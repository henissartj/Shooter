import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

APP_TITLE = "Shooter"
APP_AUTHOR = "L'EMPRISE"
APP_YEAR = "2026"
APP_COPYRIGHT = f"© {APP_AUTHOR} {APP_YEAR}"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BULLET_SVG_PATH = BASE_DIR / "bullet_2.svg"
SPLASH_BULLET_TARGET_H = 14

THEME_BG = "#0b0f14"
THEME_PANEL = "#121923"
THEME_LINE = "#203040"
THEME_TEXT = "#e6edf3"
THEME_MUTED = "#9fb1c1"
THEME_ACCENT = "#ffb000"
THEME_WARN = "#ffcc66"
THEME_ERR = "#ff4d5e"
THEME_TRACER = "#ffb000"
THEME_TRACER_DIM = "#6b4a0b"
THEME_SPARK = "#ffd27a"


@dataclass(frozen=True)
class BuildConfig:
    source_py: Path
    exe_name: str
    icon_ico: Optional[Path]
    work_dir: Path
    output_dir: Path
    onefile: bool
    windowed: bool
    hidden_imports: list[str]
    extra_pyinstaller_args: list[str]
    add_data: list[tuple[Path, str]]


def _sanitize_exe_name(name: str) -> str:
    cleaned = name.strip().strip('"').strip("'")
    cleaned = cleaned.replace(".exe", "").strip()
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in invalid else ch for ch in cleaned)
    return cleaned or "app"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_hidden_imports(text: str) -> list[str]:
    raw = re.split(r"[,\n\r\t ]+", (text or "").strip())
    seen: set[str] = set()
    items: list[str] = []
    for part in raw:
        part = part.strip()
        if not part or part in seen:
            continue
        seen.add(part)
        items.append(part)
    return items


def _parse_extra_pyinstaller_args(text: str) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    try:
        return shlex.split(s, posix=(os.name != "nt"))
    except Exception:
        return s.split()


def _load_png_photo_from_svg(svg_path: Path) -> Optional[tk.PhotoImage]:
    try:
        svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    matches = re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)", svg_text)
    if not matches:
        return None

    best = max(matches, key=len)
    try:
        return tk.PhotoImage(data=best)
    except Exception:
        return None


def _scale_photo(img: tk.PhotoImage, target_h: int) -> tk.PhotoImage:
    h = img.height()
    if h <= 0 or target_h <= 0:
        return img
    if h > target_h:
        factor = max(1, round(h / target_h))
        return img.subsample(factor, factor)
    factor = max(1, round(target_h / h))
    factor = min(factor, 3)
    return img.zoom(factor, factor)


def _cmd_works(cmd: list[str]) -> bool:
    try:
        completed = subprocess.run(
            cmd + ["--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _find_pyinstaller_cmd() -> list[str]:
    try:
        import importlib.util

        if not getattr(sys, "frozen", False) and importlib.util.find_spec("PyInstaller") is not None:
            cmd = [sys.executable, "-m", "PyInstaller"]
            if _cmd_works(cmd):
                return cmd
    except Exception:
        pass

    cmd = ["pyinstaller"]
    if _cmd_works(cmd):
        return cmd

    direct_exe = shutil.which("pyinstaller")
    if direct_exe and _cmd_works([direct_exe]):
        return [direct_exe]

    exe_candidates: list[Path] = []
    exe_name = "pyinstaller.exe" if os.name == "nt" else "pyinstaller"

    py_dir = Path(sys.executable).resolve().parent
    exe_candidates.append(py_dir / "Scripts" / exe_name)

    appdata = os.environ.get("APPDATA")
    if appdata:
        exe_candidates += list(Path(appdata).glob(f"Python/Python*/Scripts/{exe_name}"))
        exe_candidates += list(Path(appdata).glob(f"Python/Python3*/Scripts/{exe_name}"))

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        exe_candidates += list(
            Path(localappdata).glob(f"Programs/Python/Python*/Scripts/{exe_name}")
        )
        exe_candidates += list(
            Path(localappdata).glob(f"Programs/Python/Python3*/Scripts/{exe_name}")
        )

    exe_candidates = [p for p in exe_candidates if p.exists()]
    exe_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in exe_candidates:
        if _cmd_works([str(p)]):
            return [str(p)]

    return []


def _ensure_pyinstaller_cmd(log: callable) -> list[str]:
    _ = log
    return _find_pyinstaller_cmd()


def _find_python_cmd_for_pip() -> list[str]:
    if not getattr(sys, "frozen", False):
        return [sys.executable]

    candidates = [["py", "-3"], ["python"]]
    for cmd in candidates:
        try:
            completed = subprocess.run(
                cmd + ["--version"], capture_output=True, text=True, check=False
            )
            if completed.returncode == 0:
                return cmd
        except Exception:
            continue
    return []


def _install_pyinstaller(log: callable) -> bool:
    python_cmd = _find_python_cmd_for_pip()
    if not python_cmd:
        log("Python introuvable. Installez Python puis réessayez.")
        return False

    attempts = [
        python_cmd + ["-m", "pip", "install", "--upgrade", "pyinstaller"],
        python_cmd + ["-m", "pip", "install", "--user", "--upgrade", "pyinstaller"],
    ]
    for pip_args in attempts:
        log("Installation des dépendances…")
        log(_format_cmd(pip_args))
        log("")
        try:
            process = subprocess.Popen(
                pip_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            log(f"Impossible de lancer pip: {e}")
            return False

        try:
            assert process.stdout is not None
            for line in process.stdout:
                log(line.rstrip("\n"))
        finally:
            process.wait()

        if process.returncode == 0:
            return True

    return False


def _format_cmd(args: list[str]) -> str:
    return " ".join(f'"{a}"' if " " in a else a for a in args)


def _write_windows_version_file(cfg: BuildConfig) -> Optional[Path]:
    if os.name != "nt":
        return None

    _ensure_dir(cfg.work_dir)
    version_file = cfg.work_dir / "version_info.txt"
    company = APP_AUTHOR
    product = APP_TITLE
    file_desc = cfg.exe_name
    internal = cfg.exe_name
    copyright_text = f"{APP_COPYRIGHT}"

    content = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers=(2026, 1, 0, 0),\n"
        "    prodvers=(2026, 1, 0, 0),\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x4,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        "        '040904B0',\n"
        "        [\n"
        f"          StringStruct('CompanyName', {company!r}),\n"
        f"          StringStruct('FileDescription', {file_desc!r}),\n"
        f"          StringStruct('InternalName', {internal!r}),\n"
        f"          StringStruct('LegalCopyright', {copyright_text!r}),\n"
        f"          StringStruct('OriginalFilename', {(internal + '.exe')!r}),\n"
        f"          StringStruct('ProductName', {product!r}),\n"
        "          StringStruct('ProductVersion', '2026.1.0.0'),\n"
        "          StringStruct('FileVersion', '2026.1.0.0')\n"
        "        ]\n"
        "      )\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )
    version_file.write_text(content, encoding="utf-8")
    return version_file


def _build_exe_stream(cfg: BuildConfig, log: callable) -> Path:
    pyinstaller_cmd = _ensure_pyinstaller_cmd(log)
    if not pyinstaller_cmd:
        install_hint = (
            "py -3 -m pip install --upgrade pyinstaller"
            if getattr(sys, "frozen", False)
            else f"{sys.executable} -m pip install --upgrade pyinstaller"
        )
        raise RuntimeError(
            "PyInstaller n'est pas disponible dans ce Python.\n\n"
            f"Python: {sys.executable}\n\n"
            "Installez-le avec:\n"
            f"  {install_hint}"
        )

    args: list[str] = [
        *pyinstaller_cmd,
        "--noconfirm",
        "--clean",
    ]
    args.append("--onefile" if cfg.onefile else "--onedir")
    args.append("--noconsole" if cfg.windowed else "--console")
    args += ["--name", cfg.exe_name]
    version_file = _write_windows_version_file(cfg)
    if version_file:
        args += ["--version-file", str(version_file)]
    if cfg.icon_ico:
        args += ["--icon", str(cfg.icon_ico)]

    for hidden in cfg.hidden_imports:
        hidden = hidden.strip()
        if hidden:
            args += ["--hidden-import", hidden]

    data_sep = ";" if os.name == "nt" else ":"
    for src, dest in cfg.add_data:
        try:
            src_path = Path(src)
        except Exception:
            continue
        if not src_path.exists():
            log(f"Attention: data introuvable (ignoré): {src_path}")
            continue
        args += ["--add-data", f"{src_path}{data_sep}{dest}"]

    blocked_flags = {
        "--onefile",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--noconsole",
        "--console",
        "-w",
        "-c",
    }
    blocked_with_value = {
        "--name",
        "-n",
        "--icon",
        "-i",
        "--version-file",
        "--distpath",
        "--workpath",
        "--specpath",
        "--add-data",
        "--hidden-import",
        "--paths",
        "-p",
    }
    extra_kept: list[str] = []
    extra_ignored: list[str] = []
    i = 0
    while i < len(cfg.extra_pyinstaller_args):
        tok = cfg.extra_pyinstaller_args[i]
        if tok in blocked_flags:
            extra_ignored.append(tok)
            i += 1
            continue
        matched = False
        for opt in blocked_with_value:
            if tok == opt:
                extra_ignored.append(tok)
                if i + 1 < len(cfg.extra_pyinstaller_args):
                    extra_ignored.append(cfg.extra_pyinstaller_args[i + 1])
                    i += 2
                else:
                    i += 1
                matched = True
                break
            if tok.startswith(opt + "="):
                extra_ignored.append(tok)
                i += 1
                matched = True
                break
        if matched:
            continue
        extra_kept.append(tok)
        i += 1
    if extra_ignored:
        log("Options PyInstaller ignorées (gérées par Shooter):")
        log("  " + " ".join(extra_ignored))
        log("")
    if extra_kept:
        args += extra_kept
    args.append(str(cfg.source_py))

    _ensure_dir(cfg.work_dir)
    _ensure_dir(cfg.output_dir)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    log("Commande:")
    log(_format_cmd(args))
    log("")

    process = subprocess.Popen(
        args,
        cwd=str(cfg.work_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            log(line.rstrip("\n"))
    finally:
        process.wait()

    if process.returncode != 0:
        raise RuntimeError(f"Build échoué (code {process.returncode}).")

    dist_root = cfg.work_dir / "dist"
    dist_exe = (
        (dist_root / f"{cfg.exe_name}.exe")
        if cfg.onefile
        else (dist_root / cfg.exe_name / f"{cfg.exe_name}.exe")
    )
    if not dist_exe.exists():
        candidates = list(dist_root.rglob("*.exe")) if dist_root.exists() else []
        if candidates:
            dist_exe = max(candidates, key=lambda p: p.stat().st_mtime)
        else:
            raise RuntimeError("Build terminé mais aucun .exe trouvé dans dist/.")

    if cfg.onefile:
        final_exe = cfg.output_dir / dist_exe.name
        shutil.copy2(dist_exe, final_exe)
        return final_exe

    src_dir = dist_exe.parent
    dst_dir = cfg.output_dir / src_dir.name
    if dst_dir.exists():
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
    return dst_dir / dist_exe.name


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(980, 720)
        self.configure(bg=THEME_BG)

        local_root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_TITLE
        self.work_dir = local_root / "build_work"

        self.exe_name_var = tk.StringVar(value=APP_TITLE)
        self.icon_path_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="code")
        self.py_path_var = tk.StringVar(value="")
        desktop = Path.home() / "Desktop"
        default_out = desktop if desktop.exists() else Path.home()
        self.output_dir_var = tk.StringVar(value=str((default_out / f"{APP_TITLE}_output").resolve()))
        self.status_var = tk.StringVar(value="Prêt.")

        self.opt_onefile_var = tk.BooleanVar(value=True)
        self.opt_windowed_var = tk.BooleanVar(value=True)
        self.opt_hidden_imports_var = tk.StringVar(value="")
        self.opt_extra_args_var = tk.StringVar(value="")
        self._options_win: Optional[tk.Toplevel] = None

        self._env_ready = False
        self._gate: Optional[tk.Frame] = None
        self._deps_install_btn: Optional[tk.Button] = None
        self._deps_status_var = tk.StringVar(value="")
        self._deps_busy = False

        self._building = False
        self._anim_running = False
        self._tracer_start_x = 0.0
        self._tracer_end_x = 0.0
        self._tracer_x = 0.0
        self._tracer_speed = 22.0
        self._tracer_line_id: Optional[int] = None
        self._tracer_bullet_body_id: Optional[int] = None
        self._tracer_bullet_tip_id: Optional[int] = None
        self._tracer_bullet_highlight_id: Optional[int] = None
        self._tracer_bullet_img_id: Optional[int] = None
        self._flash_id: Optional[int] = None
        self._flash_frames = 0
        self._spark_items: list[tuple[int, float, float, int]] = []
        self._build_dots = 0
        self._splash: Optional[tk.Frame] = None
        self._bullet_img_raw: Optional[tk.PhotoImage] = None
        self._bullet_img_banner: Optional[tk.PhotoImage] = None
        self._bullet_img_splash: Optional[tk.PhotoImage] = None

        self._build_ui()
        self._apply_mode()
        self._show_splash()

    def _build_ui(self) -> None:
        self.main = tk.Frame(self, bg=THEME_BG)
        self.main.pack(fill="both", expand=True)

        self.banner = tk.Canvas(
            self.main,
            height=96,
            bg=THEME_BG,
            highlightthickness=0,
            bd=0,
        )
        self.banner.pack(fill="x")
        self.banner.bind("<Configure>", lambda _e: self._rebuild_banner())

        top = tk.Frame(self.main, bg=THEME_BG)
        top.pack(fill="x", padx=14, pady=12)

        row1 = tk.Frame(top, bg=THEME_BG)
        row1.pack(fill="x")
        tk.Label(row1, text="Nom de l'exe", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Entry(
            row1,
            textvariable=self.exe_name_var,
            width=30,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", padx=10)
        tk.Label(
            row1,
            text=f"Python: {sys.executable}",
            bg=THEME_BG,
            fg=THEME_MUTED,
        ).pack(side="left", padx=12)

        row2 = tk.Frame(top, bg=THEME_BG)
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="Icône (.ico)", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Entry(
            row2,
            textvariable=self.icon_path_var,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=10)
        tk.Button(
            row2,
            text="Choisir…",
            command=self._browse_icon,
            bg=THEME_PANEL,
            fg=THEME_ACCENT,
            activebackground=THEME_LINE,
            activeforeground=THEME_ACCENT,
            relief="flat",
            padx=14,
        ).pack(side="left")
        tk.Button(
            row2,
            text="Effacer",
            command=lambda: self.icon_path_var.set(""),
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            activebackground=THEME_LINE,
            activeforeground=THEME_TEXT,
            relief="flat",
            padx=14,
        ).pack(side="left", padx=(10, 0))

        row3 = tk.Frame(top, bg=THEME_BG)
        row3.pack(fill="x", pady=(12, 0))
        tk.Label(row3, text="Source", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Radiobutton(
            row3,
            text="Code",
            variable=self.mode_var,
            value="code",
            command=self._apply_mode,
            bg=THEME_BG,
            fg=THEME_TEXT,
            selectcolor=THEME_PANEL,
            activebackground=THEME_BG,
            activeforeground=THEME_ACCENT,
        ).pack(side="left", padx=10)
        tk.Radiobutton(
            row3,
            text="Fichier .py",
            variable=self.mode_var,
            value="file",
            command=self._apply_mode,
            bg=THEME_BG,
            fg=THEME_TEXT,
            selectcolor=THEME_PANEL,
            activebackground=THEME_BG,
            activeforeground=THEME_ACCENT,
        ).pack(side="left", padx=10)

        row4 = tk.Frame(top, bg=THEME_BG)
        row4.pack(fill="x", pady=(10, 0))
        tk.Label(row4, text="Fichier .py", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Entry(
            row4,
            textvariable=self.py_path_var,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=10)
        tk.Button(
            row4,
            text="Choisir…",
            command=self._browse_py,
            bg=THEME_PANEL,
            fg=THEME_ACCENT,
            activebackground=THEME_LINE,
            activeforeground=THEME_ACCENT,
            relief="flat",
            padx=14,
        ).pack(side="left")
        self.py_row = row4

        row5 = tk.Frame(top, bg=THEME_BG)
        row5.pack(fill="x", pady=(10, 0))
        tk.Label(row5, text="Dossier de sortie", bg=THEME_BG, fg=THEME_TEXT).pack(
            side="left"
        )
        tk.Entry(
            row5,
            textvariable=self.output_dir_var,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=10)
        tk.Button(
            row5,
            text="Choisir…",
            command=self._browse_output_dir,
            bg=THEME_PANEL,
            fg=THEME_ACCENT,
            activebackground=THEME_LINE,
            activeforeground=THEME_ACCENT,
            relief="flat",
            padx=14,
        ).pack(side="left")

        middle = tk.PanedWindow(self, orient="vertical", sashrelief="raised")
        middle.configure(bg=THEME_BG)
        middle.pack(fill="both", expand=True, padx=14, pady=(0, 12), in_=self.main)

        code_frame = tk.Frame(middle, bg=THEME_BG)
        tk.Label(code_frame, text="Code Python", bg=THEME_BG, fg=THEME_TEXT).pack(
            anchor="w"
        )
        self.code_text = ScrolledText(
            code_frame,
            height=14,
            wrap="none",
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        )
        self.code_text.pack(fill="both", expand=True, pady=(4, 0))
        self.code_text.insert("1.0", "print('Hello depuis Shooter')\n")
        middle.add(code_frame, stretch="always")
        self.code_frame = code_frame

        log_frame = tk.Frame(middle, bg=THEME_BG)
        tk.Label(log_frame, text="Logs", bg=THEME_BG, fg=THEME_TEXT).pack(anchor="w")
        self.log_text = ScrolledText(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        )
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))
        middle.add(log_frame, stretch="always")

        bottom = tk.Frame(self.main, bg=THEME_BG)
        bottom.pack(fill="x", padx=14, pady=(0, 10))

        self.generate_btn = tk.Button(
            bottom,
            text="Générer .exe",
            command=self._on_generate,
            bg=THEME_ACCENT,
            fg=THEME_BG,
            activebackground=THEME_TEXT,
            activeforeground=THEME_BG,
            relief="flat",
            padx=18,
            pady=8,
            state="disabled",
        )
        self.generate_btn.pack(side="left")
        tk.Button(
            bottom,
            text="Options",
            command=self._open_options,
            bg=THEME_PANEL,
            fg=THEME_ACCENT,
            activebackground=THEME_LINE,
            activeforeground=THEME_ACCENT,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="left", padx=10)
        tk.Button(
            bottom,
            text="Effacer logs",
            command=self._clear_logs,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            activebackground=THEME_LINE,
            activeforeground=THEME_TEXT,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="left", padx=10)

        footer = tk.Frame(self.main, bg=THEME_BG)
        footer.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(
            footer,
            textvariable=self.status_var,
            bg=THEME_BG,
            fg=THEME_MUTED,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            footer,
            text=f"Signé par {APP_AUTHOR} — Copyright © {APP_YEAR}",
            bg=THEME_BG,
            fg=THEME_MUTED,
            anchor="e",
        ).pack(side="right")

    def _rebuild_banner(self) -> None:
        w = max(self.banner.winfo_width(), 1)
        h = int(self.banner["height"])
        self.banner.delete("all")
        self.banner.create_rectangle(0, 0, w, h, fill=THEME_BG, outline="")
        for x in range(-h, w, 18):
            self.banner.create_line(x, 0, x + h, h, fill="#0f1620")
        self.banner.create_line(0, h - 1, w, h - 1, fill=THEME_LINE)
        title_id = self.banner.create_text(
            18,
            34,
            text=APP_TITLE.upper(),
            fill=THEME_TEXT,
            anchor="w",
            font=("Segoe UI", 28, "bold"),
        )
        self.banner.create_text(
            20,
            68,
            text="EXE BUILDER • PYINSTALLER",
            fill="#c9d6e2",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.banner.create_text(
            w - 18,
            20,
            text=f"{APP_AUTHOR} • {APP_YEAR}",
            fill=THEME_MUTED,
            anchor="e",
            font=("Segoe UI", 9, "bold"),
        )

        title_bbox = self.banner.bbox(title_id) or (18, 18, 240, 54)
        if self._bullet_img_raw is None:
            self._bullet_img_raw = _load_png_photo_from_svg(BULLET_SVG_PATH)
            if self._bullet_img_raw is not None:
                self._bullet_img_banner = _scale_photo(self._bullet_img_raw, 14)
                self._bullet_img_splash = _scale_photo(self._bullet_img_raw, SPLASH_BULLET_TARGET_H)

        bullet_w = self._bullet_img_banner.width() if self._bullet_img_banner else 22
        self._tracer_start_x = float(min(max(title_bbox[2] + 18, 120), w - 220))
        self._tracer_end_x = float(max(w - 110 - bullet_w, self._tracer_start_x + 240))

        cx = w - 56
        cy = 62
        r = 16
        self.banner.create_oval(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            outline=THEME_LINE,
            width=2,
        )
        self.banner.create_line(cx - r - 8, cy, cx + r + 8, cy, fill=THEME_LINE, width=2)
        self.banner.create_line(cx, cy - r - 8, cx, cy + r + 8, fill=THEME_LINE, width=2)
        self.banner.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, outline="", fill=THEME_ACCENT)

        y = 62
        start_x = int(self._tracer_start_x)
        end_x = int(self._tracer_end_x)
        self.banner.create_line(
            start_x,
            y,
            end_x,
            y,
            fill="#0e141d",
            width=4,
            capstyle="round",
        )
        self._tracer_x = float(start_x)
        self._tracer_line_id = self.banner.create_line(
            start_x,
            y,
            start_x,
            y,
            fill=THEME_TRACER_DIM,
            width=4,
            capstyle="round",
        )
        self._tracer_bullet_body_id = None
        self._tracer_bullet_tip_id = None
        self._tracer_bullet_highlight_id = None
        self._tracer_bullet_img_id = None
        if self._bullet_img_banner:
            img_h = self._bullet_img_banner.height()
            self._tracer_bullet_img_id = self.banner.create_image(
                start_x,
                y - img_h / 2,
                image=self._bullet_img_banner,
                anchor="nw",
            )
        else:
            self._tracer_bullet_body_id = self.banner.create_oval(
                start_x - 6,
                y - 3,
                start_x + 2,
                y + 3,
                fill=THEME_TRACER,
                outline="",
            )
            self._tracer_bullet_tip_id = self.banner.create_polygon(
                start_x + 2,
                y - 3,
                start_x + 8,
                y,
                start_x + 2,
                y + 3,
                fill=THEME_SPARK,
                outline="",
            )
            self._tracer_bullet_highlight_id = self.banner.create_line(
                start_x - 4,
                y - 1,
                start_x + 0,
                y - 1,
                fill="#fff4d6",
                width=1,
            )
        self._flash_id = self.banner.create_polygon(
            start_x + 16,
            y - 6,
            start_x + 34,
            y,
            start_x + 16,
            y + 6,
            start_x + 22,
            y,
            fill=THEME_SPARK,
            outline="",
            state="hidden",
        )
        self._flash_frames = 0
        self._spark_items.clear()

    def _show_splash(self) -> None:
        if self._splash is not None:
            return
        self.main.pack_forget()

        splash = tk.Frame(self, bg=THEME_BG)
        splash.place(x=0, y=0, relwidth=1, relheight=1)
        self._splash = splash

        canvas = tk.Canvas(splash, bg=THEME_BG, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)

        def draw() -> tuple[int, int, tuple[int, int, int, int]]:
            w = max(canvas.winfo_width(), 1)
            h = max(canvas.winfo_height(), 1)
            canvas.delete("all")
            canvas.create_rectangle(0, 0, w, h, fill=THEME_BG, outline="")
            for x in range(-h, w, 26):
                canvas.create_line(x, 0, x + h, h, fill="#0f1620")
            title_id = canvas.create_text(
                w // 2,
                int(h * 0.28),
                text=APP_TITLE.upper(),
                fill=THEME_TEXT,
                font=("Segoe UI", 44, "bold"),
            )
            canvas.create_text(
                w // 2,
                int(h * 0.28) + 48,
                text=f"{APP_AUTHOR} • {APP_YEAR}",
                fill=THEME_MUTED,
                font=("Segoe UI", 12, "bold"),
            )
            title_bbox = canvas.bbox(title_id) or (w // 2 - 220, int(h * 0.28) - 24, w // 2 + 220, int(h * 0.28) + 24)
            return w, h, title_bbox

        canvas.bind("<Configure>", lambda _e: draw())

        state = {"t": 0}

        def tick() -> None:
            if self._splash is None:
                return
            w, h, title_bbox = draw()

            total_frames = 56.0
            progress = min(1.0, float(state["t"]) / total_frames)
            canvas.create_text(
                w // 2,
                int(h * 0.72),
                text="Chargement…",
                fill=THEME_MUTED,
                font=("Segoe UI", 12, "bold"),
            )

            bar_w = int(w * 0.40)
            bar_h = 10
            bar_x0 = w // 2 - bar_w // 2
            bar_y0 = int(h * 0.78)
            canvas.create_rectangle(
                bar_x0,
                bar_y0,
                bar_x0 + bar_w,
                bar_y0 + bar_h,
                outline=THEME_LINE,
                width=1,
            )
            canvas.create_rectangle(
                bar_x0 + 1,
                bar_y0 + 1,
                bar_x0 + int((bar_w - 2) * progress),
                bar_y0 + bar_h - 1,
                outline="",
                fill=THEME_ACCENT,
            )

            state["t"] += 1
            if progress >= 1.0 and state["t"] >= 60:
                self.after(100, self._hide_splash)
                return
            self.after(30, tick)

        self.after(30, tick)

    def _hide_splash(self) -> None:
        if self._splash is None:
            return
        self._splash.destroy()
        self._splash = None
        self.main.pack(fill="both", expand=True)
        self._show_env_gate()

    def _start_animation(self) -> None:
        if self._anim_running:
            return
        self._anim_running = True
        self._rebuild_banner()
        self.after(30, self._tick_animation)

    def _tick_animation(self) -> None:
        if not self._anim_running:
            return
        w = max(self.banner.winfo_width(), 1)
        h = int(self.banner["height"])
        start_x = int(self._tracer_start_x or 18)
        end_x = int(self._tracer_end_x or max(w - 96, start_x + 200))
        y = 62

        if (
            self._tracer_line_id
            and (
                self._tracer_bullet_img_id
                or (
                    self._tracer_bullet_body_id
                    and self._tracer_bullet_tip_id
                    and self._tracer_bullet_highlight_id
                )
            )
        ):
            self._tracer_x += self._tracer_speed
            if self._tracer_x > end_x:
                self._tracer_x = float(start_x)
                self._flash_frames = 5
                for _ in range(10):
                    px = start_x + random.uniform(18, 34)
                    py = y + random.uniform(-8, 8)
                    vx = random.uniform(1.2, 3.6)
                    vy = random.uniform(-1.8, 1.8)
                    life = random.randint(10, 18)
                    item = self.banner.create_oval(
                        px - 1,
                        py - 1,
                        px + 1,
                        py + 1,
                        fill=THEME_SPARK,
                        outline="",
                    )
                    self._spark_items.append((item, vx, vy, life))

            tail_x = max(start_x, self._tracer_x - 56)
            self.banner.coords(self._tracer_line_id, tail_x, y, self._tracer_x, y)
            self.banner.itemconfigure(
                self._tracer_line_id, fill=(THEME_TRACER if self._building else THEME_TRACER_DIM)
            )
            bx = self._tracer_x
            if self._tracer_bullet_img_id and self._bullet_img_banner:
                img_h = self._bullet_img_banner.height()
                self.banner.coords(self._tracer_bullet_img_id, bx, y - img_h / 2)
            else:
                self.banner.coords(self._tracer_bullet_body_id, bx - 6, y - 3, bx + 2, y + 3)
                self.banner.coords(
                    self._tracer_bullet_tip_id, bx + 2, y - 3, bx + 8, y, bx + 2, y + 3
                )
                self.banner.coords(self._tracer_bullet_highlight_id, bx - 4, y - 1, bx + 0, y - 1)

        if self._flash_id:
            if self._flash_frames > 0:
                self.banner.itemconfigure(self._flash_id, state="normal")
                self._flash_frames -= 1
            else:
                self.banner.itemconfigure(self._flash_id, state="hidden")

        new_sparks: list[tuple[int, float, float, int]] = []
        for item, vx, vy, life in self._spark_items:
            x0, y0, x1, y1 = self.banner.coords(item)
            self.banner.coords(item, x0 + vx, y0 + vy, x1 + vx, y1 + vy)
            life -= 1
            if life > 0 and -10 < y0 < h + 10 and x0 < w + 10:
                new_sparks.append((item, vx, vy, life))
            else:
                self.banner.delete(item)
        self._spark_items = new_sparks

        if self._building:
            self._build_dots = (self._build_dots + 1) % 4
            self.status_var.set("Génération en cours" + ("." * self._build_dots))
        self.after(40, self._tick_animation)

    def _apply_mode(self) -> None:
        mode = self.mode_var.get()
        if mode == "file":
            self.code_text.configure(state="disabled")
            self.py_row.pack(fill="x", pady=(8, 0))
        else:
            self.code_text.configure(state="normal")
            self.py_row.pack_forget()

    def _browse_icon(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choisir une icône .ico",
            filetypes=[("Icône", "*.ico")],
        )
        if selected:
            self.icon_path_var.set(str(Path(selected).resolve()))

    def _browse_py(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choisir un fichier Python",
            filetypes=[("Python", "*.py")],
        )
        if selected:
            self.py_path_var.set(str(Path(selected).resolve()))

    def _browse_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choisir un dossier de sortie")
        if selected:
            self.output_dir_var.set(str(Path(selected).resolve()))

    def _set_env_ready(self, ready: bool) -> None:
        self._env_ready = ready
        self.generate_btn.configure(
            state=("disabled" if (self._building or not self._env_ready) else "normal")
        )

    def _show_env_gate(self) -> None:
        if self._gate is not None and self._gate.winfo_exists():
            self._gate.lift()
            return

        gate = tk.Frame(self.main, bg=THEME_BG)
        gate.place(x=0, y=0, relwidth=1, relheight=1)
        self._gate = gate

        panel = tk.Frame(gate, bg=THEME_PANEL, highlightbackground=THEME_LINE, highlightthickness=1)
        panel.place(relx=0.5, rely=0.52, anchor="center", width=720, height=260)

        tk.Label(
            panel,
            text="Vérification de l'environnement",
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 6))

        tk.Label(
            panel,
            textvariable=self._deps_status_var,
            bg=THEME_PANEL,
            fg=THEME_MUTED,
            justify="left",
            wraplength=680,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=16, pady=(0, 10))

        btns = tk.Frame(panel, bg=THEME_PANEL)
        btns.pack(fill="x", padx=16, pady=(6, 16), side="bottom")

        install_btn = tk.Button(
            btns,
            text="Installer les dépendances",
            command=self._on_install_dependencies,
            bg=THEME_ACCENT,
            fg=THEME_BG,
            activebackground=THEME_TEXT,
            activeforeground=THEME_BG,
            relief="flat",
            padx=18,
            pady=8,
        )
        install_btn.pack(side="left")
        self._deps_install_btn = install_btn

        tk.Button(
            btns,
            text="Réessayer",
            command=self._run_env_check,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            activebackground=THEME_LINE,
            activeforeground=THEME_TEXT,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="left", padx=10)

        self._set_env_ready(False)
        self._deps_status_var.set("Analyse en cours…")
        self._deps_install_btn.configure(state="disabled")
        self.after(10, self._run_env_check)

    def _run_env_check(self) -> None:
        if self._deps_busy:
            return
        self._deps_busy = True
        self._deps_status_var.set("Vérification…")
        if self._deps_install_btn is not None:
            self._deps_install_btn.configure(state="disabled")

        def worker() -> None:
            pyinstaller_cmd = _find_pyinstaller_cmd()
            if pyinstaller_cmd:
                msg = "OK: PyInstaller détecté.\nVous pouvez générer des .exe."

                def ui_ok() -> None:
                    self._deps_busy = False
                    self._set_env_ready(True)
                    if self._gate is not None:
                        self._gate.destroy()
                        self._gate = None
                    self._start_animation()

                self.after(0, lambda: self._deps_status_var.set(msg))
                self.after(200, ui_ok)
                return

            frozen = getattr(sys, "frozen", False)
            if frozen:
                msg = (
                    "PyInstaller n'est pas installé.\n"
                    "Installez Python + PyInstaller sur ce PC, puis cliquez Réessayer.\n"
                    "Commande (PowerShell):\n  py -3 -m pip install --upgrade pyinstaller"
                )
            else:
                msg = (
                    "PyInstaller n'est pas installé pour ce Python.\n"
                    "Cliquez sur “Installer les dépendances”."
                )

            def ui_fail() -> None:
                self._deps_busy = False
                self._set_env_ready(False)
                if self._deps_install_btn is not None:
                    self._deps_install_btn.configure(state=("disabled" if frozen else "normal"))

            self.after(0, lambda: self._deps_status_var.set(msg))
            self.after(0, ui_fail)

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_dependencies(self) -> None:
        if self._deps_busy:
            return
        self._deps_busy = True
        self._deps_status_var.set("Installation en cours…")
        if self._deps_install_btn is not None:
            self._deps_install_btn.configure(state="disabled")
        self._clear_logs()
        self._log("Installation des dépendances (PyInstaller)…")
        self._log("")

        def worker() -> None:
            ok = _install_pyinstaller(self._log_threadsafe)
            if not ok:
                self.after(
                    0,
                    lambda: (
                        setattr(self, "_deps_busy", False),
                        self._deps_status_var.set("Échec de l'installation. Voir les logs."),
                        self._deps_install_btn.configure(state="normal")
                        if self._deps_install_btn is not None
                        else None,
                    ),
                )
                return
            self.after(0, lambda: setattr(self, "_deps_busy", False))
            self.after(0, self._run_env_check)

    def _open_options(self) -> None:
        win = getattr(self, "_options_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Options")
        win.configure(bg=THEME_BG)
        win.resizable(False, False)
        self._options_win = win

        def on_close() -> None:
            if self._options_win is not None:
                self._options_win.destroy()
            self._options_win = None

        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tk.Frame(win, bg=THEME_BG)
        frame.pack(fill="both", expand=True, padx=14, pady=14)

        tk.Checkbutton(
            frame,
            text="Onefile (un seul .exe)",
            variable=self.opt_onefile_var,
            bg=THEME_BG,
            fg=THEME_TEXT,
            selectcolor=THEME_PANEL,
            activebackground=THEME_BG,
            activeforeground=THEME_ACCENT,
        ).pack(anchor="w")
        tk.Checkbutton(
            frame,
            text="Sans console (GUI)",
            variable=self.opt_windowed_var,
            bg=THEME_BG,
            fg=THEME_TEXT,
            selectcolor=THEME_PANEL,
            activebackground=THEME_BG,
            activeforeground=THEME_ACCENT,
        ).pack(anchor="w", pady=(6, 12))

        row1 = tk.Frame(frame, bg=THEME_BG)
        row1.pack(fill="x", pady=(0, 10))
        tk.Label(row1, text="Hidden-imports", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Entry(
            row1,
            textvariable=self.opt_hidden_imports_var,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=10)

        row2 = tk.Frame(frame, bg=THEME_BG)
        row2.pack(fill="x")
        tk.Label(row2, text="Args PyInstaller", bg=THEME_BG, fg=THEME_TEXT).pack(side="left")
        tk.Entry(
            row2,
            textvariable=self.opt_extra_args_var,
            bg=THEME_PANEL,
            fg=THEME_TEXT,
            insertbackground=THEME_ACCENT,
            highlightbackground=THEME_LINE,
            highlightcolor=THEME_ACCENT,
            relief="flat",
        ).pack(side="left", fill="x", expand=True, padx=10)

        btns = tk.Frame(frame, bg=THEME_BG)
        btns.pack(fill="x", pady=(14, 0))
        tk.Button(
            btns,
            text="Fermer",
            command=on_close,
            bg=THEME_ACCENT,
            fg=THEME_BG,
            activebackground=THEME_TEXT,
            activeforeground=THEME_BG,
            relief="flat",
            padx=18,
            pady=8,
        ).pack(side="right")

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_building(self, building: bool) -> None:
        self._building = building
        self.generate_btn.configure(
            state=("disabled" if (building or not self._env_ready) else "normal")
        )
        if not building:
            self.status_var.set("Prêt.")

    def _validate_and_make_cfg(self) -> BuildConfig:
        exe_name = _sanitize_exe_name(self.exe_name_var.get())
        if not exe_name:
            raise RuntimeError("Nom d'exe invalide.")

        icon_raw = self.icon_path_var.get().strip()
        icon_path: Optional[Path] = None
        if icon_raw:
            icon_path = Path(icon_raw).expanduser()
            if not icon_path.is_absolute():
                icon_path = (Path.cwd() / icon_path).resolve()
            if not icon_path.exists():
                raise RuntimeError(f"Icône introuvable: {icon_path}")
            if icon_path.suffix.lower() != ".ico":
                raise RuntimeError("L'icône doit être un fichier .ico")

        out_dir = Path(self.output_dir_var.get().strip() or "").expanduser()
        if not out_dir:
            raise RuntimeError("Dossier de sortie invalide.")
        if not out_dir.is_absolute():
            out_dir = (Path.cwd() / out_dir).resolve()

        mode = self.mode_var.get()
        if mode == "file":
            raw = self.py_path_var.get().strip()
            if not raw:
                raise RuntimeError("Choisissez un fichier .py.")
            source_py = Path(raw).expanduser()
            if not source_py.is_absolute():
                source_py = (Path.cwd() / source_py).resolve()
            if not source_py.exists():
                raise RuntimeError(f"Fichier introuvable: {source_py}")
            if source_py.suffix.lower() != ".py":
                raise RuntimeError("Le fichier doit être un .py")
        else:
            code = self.code_text.get("1.0", "end").strip()
            if not code:
                raise RuntimeError("Code vide.")
            source_py = self.work_dir / "inputs" / "main.py"
            _ensure_dir(source_py.parent)
            source_py.write_text(code + "\n", encoding="utf-8")

        hidden_imports = _parse_hidden_imports(self.opt_hidden_imports_var.get())
        extra_args = _parse_extra_pyinstaller_args(self.opt_extra_args_var.get())
        build_dir = self.work_dir / "builds" / exe_name

        return BuildConfig(
            source_py=source_py,
            exe_name=exe_name,
            icon_ico=icon_path,
            work_dir=build_dir,
            output_dir=out_dir,
            onefile=bool(self.opt_onefile_var.get()),
            windowed=bool(self.opt_windowed_var.get()),
            hidden_imports=hidden_imports,
            extra_pyinstaller_args=extra_args,
            add_data=[],
        )

    def _on_generate(self) -> None:
        if self._building:
            return

        self._clear_logs()
        try:
            cfg = self._validate_and_make_cfg()
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return

        self._set_building(True)
        self.status_var.set("Préparation…")
        self._log("Démarrage du build…")
        self._log(f"Produit : {APP_TITLE}")
        self._log(f"Signé   : {APP_AUTHOR} (Copyright © {APP_YEAR})")
        self._log(f"Nom exe : {cfg.exe_name}")
        self._log(f"Source : {cfg.source_py}")
        self._log(f"Icône  : {cfg.icon_ico or '(aucune)'}")
        self._log(f"Sortie : {cfg.output_dir}")
        self._log("")

        def worker() -> None:
            start = time.time()
            try:
                exe_path = _build_exe_stream(cfg, self._log_threadsafe)
            except Exception as e:
                self._after_build_error(str(e))
                return
            elapsed = time.time() - start
            self._after_build_ok(str(exe_path), elapsed)

        threading.Thread(target=worker, daemon=True).start()

    def _log_threadsafe(self, message: str) -> None:
        self.after(0, lambda: self._log(message))

    def _after_build_ok(self, exe_path: str, elapsed: float) -> None:
        def ui() -> None:
            self._log("")
            self._log(f"OK: {exe_path}")
            self._log(f"Temps: {elapsed:.1f}s")
            self._set_building(False)
            self.status_var.set("Terminé.")
            messagebox.showinfo(APP_TITLE, f"Exe généré:\n{exe_path}")

        self.after(0, ui)

    def _after_build_error(self, error: str) -> None:
        def ui() -> None:
            self._log("")
            self._log("ERREUR:")
            self._log(error)
            self._set_building(False)
            self.status_var.set("Erreur.")
            messagebox.showerror(APP_TITLE, error)

        self.after(0, ui)

def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
