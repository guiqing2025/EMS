"""
ICT 工位扫码闸道（Windows / macOS）

流程：扫码枪输入本窗口 → 问 EMS 是否已过后焊 →
  允许：把条码键盘楔入到 TRI 测试软件当前焦点 →
  拒绝：提示「未过后焊」并可选播 FALL，不喂给 TRI。

依赖（Windows 建议安装）：
  pip install keyboard
或仅用剪贴板+Ctrl+V（无 keyboard 库时的回退）。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import winsound as _winsound
except ImportError:
    _winsound = None

CONFIG_NAME = "ict_gate_config.json"
DEFAULT_CONFIG = {
    "ems_base_url": "http://127.0.0.1:8000",
    "api_key": "ems-ict-gate-2026-dx",
    "machine_id": "ict-pilot",
    "append_enter": True,
    "focus_delay_ms": 80,
    "play_sound": True,
}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config() -> dict:
    path = _app_dir() / CONFIG_NAME
    cfg = dict(DEFAULT_CONFIG)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in data if k in DEFAULT_CONFIG or k in data})
        except Exception:
            pass
    else:
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def save_config(cfg: dict) -> None:
    path = _app_dir() / CONFIG_NAME
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def check_post_solder(ems_base: str, api_key: str, barcode: str) -> dict:
    base = ems_base.rstrip("/")
    q = urllib.parse.urlencode({"barcode": barcode})
    url = f"{base}/api/ict-gate/check?{q}"
    req = urllib.request.Request(
        url,
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def play_ok() -> None:
    if _winsound:
        try:
            _winsound.MessageBeep(_winsound.MB_OK)
        except Exception:
            pass


def play_fail() -> None:
    if _winsound:
        try:
            _winsound.MessageBeep(_winsound.MB_ICONHAND)
        except Exception:
            pass
    # 尝试播 EMS 静态女声 FALL（若网络可达）
    try:
        cfg = load_config()
        url = cfg["ems_base_url"].rstrip("/") + "/static/sounds/fall.wav"
        # 异步下载播放太重；Windows 用系统蜂鸣即可。可选本地文件：
        local = _app_dir() / "fall.wav"
        if local.is_file() and _winsound:
            _winsound.PlaySound(str(local), _winsound.SND_FILENAME | _winsound.SND_ASYNC)
            return
        # 拉一次缓存
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            local.write_bytes(resp.read())
        if _winsound:
            _winsound.PlaySound(str(local), _winsound.SND_FILENAME | _winsound.SND_ASYNC)
    except Exception:
        pass


def play_pass_voice() -> None:
    try:
        cfg = load_config()
        local = _app_dir() / "pass.wav"
        if not local.is_file():
            url = cfg["ems_base_url"].rstrip("/") + "/static/sounds/pass.wav"
            with urllib.request.urlopen(url, timeout=3) as resp:
                local.write_bytes(resp.read())
        if _winsound:
            _winsound.PlaySound(str(local), _winsound.SND_FILENAME | _winsound.SND_ASYNC)
        else:
            play_ok()
    except Exception:
        play_ok()


def type_to_foreground(text: str, append_enter: bool, delay_ms: int) -> str:
    """把条码打到当前前台窗口。优先 keyboard 库，否则剪贴板+Ctrl+V。"""
    time.sleep(max(0, delay_ms) / 1000.0)
    payload = text + ("\n" if append_enter else "")

    # 1) keyboard（Windows 常用）
    try:
        import keyboard  # type: ignore

        keyboard.write(payload, delay=0.02)
        return "keyboard"
    except Exception:
        pass

    # 2) pyautogui
    try:
        import pyautogui  # type: ignore

        pyautogui.typewrite(text, interval=0.02)
        if append_enter:
            pyautogui.press("enter")
        return "pyautogui"
    except Exception:
        pass

    # 3) 剪贴板 + Ctrl+V（跨平台回退）
    try:
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
    except Exception as e:
        return f"clipboard_fail:{e}"

    if sys.platform == "darwin":
        try:
            import subprocess

            # Cmd+V
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
                check=False,
            )
            if append_enter:
                subprocess.run(
                    ["osascript", "-e", 'tell application "System Events" to keystroke return'],
                    check=False,
                )
            return "clipboard_osascript"
        except Exception as e:
            return f"osascript_fail:{e}"

    # Windows SendInput Ctrl+V via powershell
    try:
        import ctypes

        # VK_CONTROL=0x11, V=0x56, RETURN=0x0D
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]

        def key_down(vk: int) -> None:
            user32.keybd_event(vk, 0, 0, 0)

        def key_up(vk: int) -> None:
            user32.keybd_event(vk, 0, 2, 0)

        key_down(0x11)
        key_down(0x56)
        key_up(0x56)
        key_up(0x11)
        if append_enter:
            time.sleep(0.05)
            key_down(0x0D)
            key_up(0x0D)
        return "clipboard_sendinput"
    except Exception as e:
        return f"sendinput_fail:{e}"


class GateApp:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title(f"ICT 扫码闸道 · {self.cfg.get('machine_id', '')}")
        self.root.geometry("520x320")
        self.root.attributes("-topmost", True)

        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="EMS 地址").grid(row=0, column=0, sticky=tk.W)
        self.var_url = tk.StringVar(value=self.cfg.get("ems_base_url", ""))
        ttk.Entry(frm, textvariable=self.var_url, width=48).grid(row=0, column=1, sticky=tk.EW, pady=2)

        ttk.Label(frm, text="API Key").grid(row=1, column=0, sticky=tk.W)
        self.var_key = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(frm, textvariable=self.var_key, width=48, show="*").grid(row=1, column=1, sticky=tk.EW, pady=2)

        ttk.Label(frm, text="机台 ID").grid(row=2, column=0, sticky=tk.W)
        self.var_mid = tk.StringVar(value=self.cfg.get("machine_id", "ict-pilot"))
        ttk.Entry(frm, textvariable=self.var_mid, width=48).grid(row=2, column=1, sticky=tk.EW, pady=2)

        ttk.Button(frm, text="保存配置", command=self.on_save).grid(row=3, column=1, sticky=tk.E, pady=4)

        ttk.Separator(frm).grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=8)

        ttk.Label(
            frm,
            text="请把扫码枪对准本窗口扫码。通过后会自动切换并输入到 TRI。",
            wraplength=460,
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(frm, text="条码").grid(row=6, column=0, sticky=tk.W)
        self.var_code = tk.StringVar()
        self.entry = ttk.Entry(frm, textvariable=self.var_code, font=("Consolas", 16))
        self.entry.grid(row=6, column=1, sticky=tk.EW, pady=6)
        self.entry.bind("<Return>", self.on_scan)
        self.entry.focus_set()

        self.status = tk.StringVar(value="等待扫码…")
        ttk.Label(frm, textvariable=self.status, foreground="#0f766e").grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=8
        )

        frm.columnconfigure(1, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        # 保持输入焦点：定时抢回（避免点到别处后扫不到闸道）
        self.root.after(1500, self._keep_focus)

    def _keep_focus(self) -> None:
        try:
            if self.root.focus_get() is None:
                self.entry.focus_force()
        except Exception:
            pass
        self.root.after(1500, self._keep_focus)

    def on_save(self) -> None:
        self.cfg["ems_base_url"] = self.var_url.get().strip()
        self.cfg["api_key"] = self.var_key.get().strip()
        self.cfg["machine_id"] = self.var_mid.get().strip() or "ict-pilot"
        save_config(self.cfg)
        self.root.title(f"ICT 扫码闸道 · {self.cfg['machine_id']}")
        self.status.set("配置已保存")

    def on_scan(self, _event=None) -> None:
        code = self.var_code.get().strip()
        self.var_code.set("")
        if not code:
            return
        self.status.set(f"校验中：{code}")
        self.root.update_idletasks()
        threading.Thread(target=self._process, args=(code,), daemon=True).start()

    def _process(self, code: str) -> None:
        try:
            self.on_save_silent()
            result = check_post_solder(self.cfg["ems_base_url"], self.cfg["api_key"], code)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            self._ui(lambda: self._fail(f"EMS 拒绝 ({e.code}) {body}"))
            return
        except Exception as e:
            self._ui(lambda: self._fail(f"网络/服务异常：{e}"))
            return

        if result.get("allowed"):
            bc = result.get("barcode") or code

            def ok() -> None:
                self.status.set(f"通过 → 送入 TRI：{bc}")
                if self.cfg.get("play_sound", True):
                    play_pass_voice()
                # 先失焦闸道，给用户 0.1s 把 TRI 置前；若 TRI 已在旁边，延时后打字
                self.root.iconify()
                self.root.after(
                    int(self.cfg.get("focus_delay_ms", 80)) + 200,
                    lambda: self._feed(bc),
                )

            self._ui(ok)
        else:
            msg = result.get("message") or "不允许测试"
            self._ui(lambda: self._fail(msg))

    def on_save_silent(self) -> None:
        self.cfg["ems_base_url"] = self.var_url.get().strip()
        self.cfg["api_key"] = self.var_key.get().strip()
        self.cfg["machine_id"] = self.var_mid.get().strip() or "ict-pilot"

    def _feed(self, barcode: str) -> None:
        how = type_to_foreground(
            barcode,
            append_enter=bool(self.cfg.get("append_enter", True)),
            delay_ms=int(self.cfg.get("focus_delay_ms", 80)),
        )
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.entry.focus_force()
        self.status.set(f"已送出（{how}）：{barcode} — 继续扫下一片")

    def _fail(self, message: str) -> None:
        self.status.set(f"拦截：{message}")
        if self.cfg.get("play_sound", True):
            play_fail()
        messagebox.showerror("ICT 闸道拦截", message)
        self.entry.focus_force()

    def _ui(self, fn) -> None:
        self.root.after(0, fn)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    # 非 Windows 时 winsound 已处理；提醒部署目标
    GateApp().run()


if __name__ == "__main__":
    main()
