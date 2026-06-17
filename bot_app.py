# -*- coding: utf-8 -*-
"""
OTOMASYON BOTU - Arayuz (v2)
------------------------------
Sade, kucuk pencereli surum. Adim listesi ve log gizli.
Global kisayollar (uygulama arka plandayken de calisir):
    F1 = Calistir
    F2 = Durdur
    F3 = Kayit Baslat / Bitir (toggle)
    F4 = Bekleme/Onay Adimi Ekle (fareyi hedefe goturup beklenir)
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import os
import time
import sys

import pyautogui
import keyboard

from bot_core import (
    Recorder, Player, Scenario, Step,
    save_scenario, load_scenario,
    capture_region_around_point,
)

APP_TITLE = "Tekrarli Islem Botu"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "bot_data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(SCENARIOS_DIR, exist_ok=True)


class BotApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("330x300")
        self.root.minsize(300, 280)
        self.root.resizable(True, True)

        self.recorder = None
        self.current_scenario = None
        self.player = None
        self.player_thread = None
        self.image_counter = 0
        self.is_recording = False

        self._build_ui()
        self._register_global_hotkeys()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # ARAYUZ
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text=APP_TITLE, font=("Segoe UI", 13, "bold")).pack(anchor="w")

        # Her zaman ustte kal
        self.always_on_top_var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(main, text="Her zaman ustte kal",
                               variable=self.always_on_top_var,
                               command=self._toggle_always_on_top)
        chk.pack(anchor="w", pady=(4, 8))
        self.root.attributes("-topmost", True)

        # Durum etiketi
        self.status_var = tk.StringVar(value="Hazir")
        ttk.Label(main, textvariable=self.status_var, foreground="#0a5",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 8))

        # Kisayol bilgisi
        info = ("F1 = Calistir      F2 = Durdur\n"
                "F3 = Kayit Baslat/Bitir\n"
                "F4 = Bekleme/Onay Adimi Ekle\n"
                "(Bu kisayollar uygulama arka plandayken de calisir)")
        ttk.Label(main, text=info, foreground="#555", justify="left",
                  font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 10))

        # Tekrar sayisi
        row = ttk.Frame(main)
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="Tekrar sayisi:").pack(side="left")
        self.repeat_var = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self.repeat_var, width=6).pack(side="left", padx=5)

        row2 = ttk.Frame(main)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="Tekrarlar arasi bekleme (sn):").pack(side="left")
        self.delay_var = tk.StringVar(value="1.0")
        ttk.Entry(row2, textvariable=self.delay_var, width=5).pack(side="left", padx=5)

        # Dosya butonlari
        file_row = ttk.Frame(main)
        file_row.pack(fill="x", pady=(0, 8))
        ttk.Button(file_row, text="Senaryo Kaydet", command=self.save_scenario_to_file).pack(side="left", padx=(0, 4))
        ttk.Button(file_row, text="Senaryo Ac", command=self.load_scenario_from_file).pack(side="left")

        # Emniyet notu
        ttk.Label(main, text="Acil durdurma: F2, veya fareyi sol-ust koseye goturmek.",
                  foreground="#a00", font=("Segoe UI", 8), wraplength=300, justify="left").pack(anchor="w")

        # Sag alt kose imza
        sig = ttk.Label(self.root, text="Deniz IZGI - 242334",
                         foreground="#aaaaaa", font=("Segoe UI", 7))
        sig.place(relx=1.0, rely=1.0, x=-4, y=-2, anchor="se")

    def _toggle_always_on_top(self):
        self.root.attributes("-topmost", self.always_on_top_var.get())

    def set_status(self, text, color="#0a5"):
        self.status_var.set(text)
        # renk degisimi icin label'i bulup guncellemek yerine basit tutuyoruz

    # ------------------------------------------------------------------
    # GLOBAL KISAYOLLAR
    # ------------------------------------------------------------------
    def _register_global_hotkeys(self):
        keyboard.add_hotkey("F1", self._hotkey_run)
        keyboard.add_hotkey("F2", self._hotkey_stop)
        keyboard.add_hotkey("F3", self._hotkey_toggle_recording)
        keyboard.add_hotkey("F4", self._hotkey_add_wait_step)

    def _hotkey_run(self):
        self.root.after(0, self.run_scenario)

    def _hotkey_stop(self):
        self.root.after(0, self.stop_run)

    def _hotkey_toggle_recording(self):
        self.root.after(0, self._toggle_recording)

    def _hotkey_add_wait_step(self):
        self.root.after(0, self.add_wait_image_step)

    # ------------------------------------------------------------------
    # KAYIT
    # ------------------------------------------------------------------
    def _toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.current_scenario = None
        self.recorder = Recorder(on_step_added=None)
        self.recorder.start()
        self.is_recording = True
        self.set_status("KAYIT YAPILIYOR... (F3 ile bitir)")

    def stop_recording(self):
        if not self.recorder:
            return
        self.recorder.stop()
        self.is_recording = False

        # Pencereyi gecici olarak one getirip isim sormak icin
        self.root.deiconify()
        self.root.lift()
        name = simpledialog.askstring("Senaryo Adi", "Bu senaryoya bir ad ver:",
                                       initialvalue="Senaryom", parent=self.root)
        if not name:
            name = "Senaryom"
        self.current_scenario = self.recorder.build_scenario(name)
        self.set_status(f"Kayit bitti: {len(self.current_scenario.steps)} adim")

    def add_wait_image_step(self):
        """
        F4'e basildiginda calisir. Kullaniciya 'fareni hedefin ustune goturup
        bekle' diye 3 saniyelik bir geri sayim gosterir, sonra fare konumunun
        etrafindan otomatik kucuk bir kare alir. Surukleme/ekran kararmasi yok.
        """
        if not self.recorder or not self.is_recording:
            messagebox.showwarning(APP_TITLE, "Once F3 ile kayda baslamalisin.", parent=self.root)
            return

        countdown_win = CountdownOverlay(self.root, seconds=3,
                                          message="Fareni hedefin ustune goetuer...")
        self.root.after(3100, lambda: self._capture_at_mouse_position(countdown_win))

    def _capture_at_mouse_position(self, countdown_win):
        countdown_win.close()
        x, y = pyautogui.position()
        crop = capture_region_around_point(x, y, half_size=35)

        self.image_counter += 1
        img_filename = f"hedef_{int(time.time())}_{self.image_counter}.png"
        img_path = os.path.join(IMAGES_DIR, img_filename)
        crop.save(img_path)

        self.root.deiconify()
        self.root.lift()
        label = simpledialog.askstring("Adim Adi", "Bu adima kisa bir isim ver (ornek: 'Onay butonu'):",
                                        initialvalue="Onay butonu", parent=self.root)
        if not label:
            label = "Onay butonu"

        timeout_str = simpledialog.askstring("Bekleme Suresi",
                                              "En fazla kac saniye beklensin? (ornek: 20)",
                                              initialvalue="20", parent=self.root)
        try:
            timeout_val = float(timeout_str)
        except (TypeError, ValueError):
            timeout_val = 20.0

        step = Step(
            type="wait_image",
            image_file=img_filename,
            on_found_action="click",
            timeout_seconds=timeout_val,
            confidence=0.85,
            label=f"Bekle ve tikla: {label}",
        )
        self.recorder.steps.append(step)
        self.set_status(f"Eklendi: {label}")

    # ------------------------------------------------------------------
    # DOSYA ISLEMLERI
    # ------------------------------------------------------------------
    def save_scenario_to_file(self):
        if not self.current_scenario:
            messagebox.showwarning(APP_TITLE, "Kaydedilecek bir senaryo yok.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            initialdir=SCENARIOS_DIR,
            defaultextension=".json",
            filetypes=[("Senaryo dosyasi", "*.json")],
            initialfile=self.current_scenario.name,
            parent=self.root,
        )
        if not path:
            return
        save_scenario(self.current_scenario, path)
        messagebox.showinfo(APP_TITLE, f"Senaryo kaydedildi:\n{path}\n\n"
                                        f"Bu dosyayi ve 'bot_data/images' klasorunu baska bilgisayara "
                                        f"tasirsan orada da calisir.", parent=self.root)

    def load_scenario_from_file(self):
        path = filedialog.askopenfilename(
            initialdir=SCENARIOS_DIR,
            filetypes=[("Senaryo dosyasi", "*.json")],
            parent=self.root,
        )
        if not path:
            return
        try:
            self.current_scenario = load_scenario(path)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Dosya okunamadi:\n{e}", parent=self.root)
            return
        self.set_status(f"Yuklendi: {len(self.current_scenario.steps)} adim")

    # ------------------------------------------------------------------
    # CALISTIRMA
    # ------------------------------------------------------------------
    def run_scenario(self):
        if self.is_recording:
            messagebox.showwarning(APP_TITLE, "Kayit devam ediyor, once F3 ile bitir.", parent=self.root)
            return
        if not self.current_scenario or not self.current_scenario.steps:
            messagebox.showwarning(APP_TITLE, "Once bir senaryo kaydet veya ac.", parent=self.root)
            return
        if self.player_thread and self.player_thread.is_alive():
            return  # zaten calisiyor

        try:
            repeat_count = int(self.repeat_var.get())
            if repeat_count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE, "Tekrar sayisi gecerli bir pozitif sayi olmali.", parent=self.root)
            return
        try:
            delay = float(self.delay_var.get())
        except ValueError:
            delay = 1.0

        self.player = Player(
            self.current_scenario,
            images_dir=IMAGES_DIR,
            log_callback=lambda msg: self.root.after(0, self.set_status, msg),
            step_callback=lambda rep, idx, total: self.root.after(
                0, self.set_status, f"Tekrar {rep}/{repeat_count} - Adim {idx}/{total}"),
        )

        def worker():
            self.player.run(repeat_count, delay_between_runs=delay)
            self.root.after(0, lambda: self.set_status("Tamamlandi."))

        self.player_thread = threading.Thread(target=worker, daemon=True)
        self.player_thread.start()
        self.set_status(f"Baslatildi: {repeat_count} tekrar")

    def stop_run(self):
        if self.player:
            self.player.stop()
            self.set_status("Durduruldu")

    def _on_close(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()


class CountdownOverlay:
    """
    F4'e basinca cikan, ekranin ortasinda kucuk, her zaman ustte kalan
    bir geri sayim penceresi. Kullaniciya fareyi hedefe goturmesi icin
    3 saniyelik bir uyari verir.
    """
    def __init__(self, parent, seconds=3, message="Hazirlaniyor..."):
        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="#222222")

        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        w, h = 280, 90
        self.top.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

        self.label_msg = tk.Label(self.top, text=message, fg="white", bg="#222222",
                                   font=("Segoe UI", 10))
        self.label_msg.pack(pady=(10, 2))

        self.label_count = tk.Label(self.top, text=str(seconds), fg="#3ddc84", bg="#222222",
                                     font=("Segoe UI", 22, "bold"))
        self.label_count.pack()

        self._seconds_left = seconds
        self._tick()

    def _tick(self):
        if self._seconds_left <= 0:
            return
        self.label_count.config(text=str(self._seconds_left))
        self._seconds_left -= 1
        self.top.after(1000, self._tick)

    def close(self):
        try:
            self.top.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    app = BotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
