"""
Bot Cekirdek Modulu
--------------------
Bu modul fare/klavye hareketlerini kaydetme, kaydedilen senaryoyu
tekrar oynatma ve ekranda renk kontrolu (bekleme/onay) islevlerini icerir.

Farkli ekran cozunurluklerinde calismasi icin:
- Koordinatlar, kayit anindaki ekran boyutuna GORE ORANSAL (yuzdelik) olarak saklanir.
  Oynatma sirasinda o bilgisayarin gercek ekran boyutuna göre yeniden hesaplanir.
- "Bekle ve onayla" adimlari icin, kayit aninda kullanicinin gosterdigi noktadaki
  RGB rengi hedef olarak kaydedilir. Oynatma sirasinda o nokta (oransal olarak
  olceklenmis) o renge DONENE kadar beklenir, sonra tiklanir.
"""

import json
import time
import threading
import os
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Callable

import pyautogui
import keyboard
import mouse
from PIL import Image

pyautogui.FAILSAFE = True  # Mouse'u ekranin sol-ust kosesine goturursen botu acil durdurur


# ---------------------------------------------------------------------------
# VERI YAPILARI
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """Senaryodaki tek bir adim."""
    type: str  # "click", "double_click", "right_click", "type_text", "wait_color", "key", "sleep"
    # click / double_click / right_click / wait_color icin oransal koordinat (0.0 - 1.0)
    x_ratio: Optional[float] = None
    y_ratio: Optional[float] = None
    # type_text icin
    text: Optional[str] = None
    # key (tek tus, ornek "enter", "tab") icin
    key: Optional[str] = None
    # sleep icin (saniye)
    seconds: Optional[float] = None
    # wait_color icin: hedef renk (R, G, B) 0-255 araliginda
    target_r: Optional[int] = None
    target_g: Optional[int] = None
    target_b: Optional[int] = None
    # wait_color icin: renk karsilastirma tolerans payi (0-50 arasi onerilir)
    color_tolerance: int = 10
    # wait_color icin: bulunca yapilacak islem ("click" ise tiklar, "none" ise sadece bekler)
    on_found_action: str = "click"
    # wait_color icin: en fazla kac saniye beklenecek (bulunamazsa)
    timeout_seconds: float = 30.0
    # adimin kisa aciklamasi (kullanici icin)
    label: str = ""


@dataclass
class Scenario:
    """Kaydedilen tam senaryo: adim listesi + kayit anindaki ekran cozunurlugu."""
    name: str
    recorded_screen_width: int
    recorded_screen_height: int
    steps: List[Step] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d):
        steps = [Step(**s) for s in d.get("steps", [])]
        return Scenario(
            name=d["name"],
            recorded_screen_width=d["recorded_screen_width"],
            recorded_screen_height=d["recorded_screen_height"],
            steps=steps,
        )


# ---------------------------------------------------------------------------
# KAYIT (RECORDING)
# ---------------------------------------------------------------------------

class Recorder:
    """
    Kullanicinin fare tiklamalarini ve klavye girislerini dinleyip
    bir Step listesine donusturur.

    Kullanim:
        rec = Recorder(on_step_added=callback)
        rec.start()
        ... kullanici islem yapar ...
        rec.stop()
        scenario = rec.build_scenario("Senaryo adi")
    """

    def __init__(self, on_step_added: Optional[Callable[[Step], None]] = None):
        self.steps: List[Step] = []
        self.on_step_added = on_step_added
        self._running = False
        self._last_event_time = None
        self._text_buffer = ""
        self._lock = threading.Lock()
        self.screen_w, self.screen_h = pyautogui.size()

    def _add_step(self, step: Step):
        with self._lock:
            # Klavye yazisi arka arkaya geliyorsa, harf harf degil tek "type_text" adimi olarak biriktir
            if step.type == "char" :
                self._text_buffer += step.text
                return
            self._flush_text_buffer()
            self.steps.append(step)
        if self.on_step_added:
            self.on_step_added(step)

    def _flush_text_buffer(self):
        if self._text_buffer:
            s = Step(type="type_text", text=self._text_buffer,
                     label=f"Yaz: {self._text_buffer[:30]}")
            self.steps.append(s)
            if self.on_step_added:
                self.on_step_added(s)
            self._text_buffer = ""

    def _on_click(self, x, y, button, pressed):
        if not self._running or not pressed:
            return
        xr = x / self.screen_w
        yr = y / self.screen_h
        btn_map = {"left": "click", "right": "right_click", "middle": "click"}
        step_type = btn_map.get(str(button).split(".")[-1], "click")
        label = f"Tikla ({button}) @ {x},{y}"
        self._add_step(Step(type=step_type, x_ratio=xr, y_ratio=yr, label=label))

    def _on_key(self, event):
        if not self._running:
            return
        if event.event_type != "down":
            return
        name = event.name
        # Ozel tuslar
        special = {"enter", "tab", "esc", "space", "backspace", "delete",
                   "up", "down", "left", "right", "home", "end"}
        if name in special:
            self._flush_text_buffer()
            self.steps.append(Step(type="key", key=name, label=f"Tus: {name}"))
            if self.on_step_added:
                self.on_step_added(self.steps[-1])
        elif len(name) == 1:
            self._add_step(Step(type="char", text=name))
        # diger kontrol tuslarini (ctrl, shift, alt, capslock vb.) atliyoruz - sadece yazi olarak etkilerini yakalamak yeterli

    def start(self):
        self._running = True
        self.steps = []
        self._text_buffer = ""
        self.screen_w, self.screen_h = pyautogui.size()
        mouse.on_click(lambda: self._on_click(*mouse.get_position(), "left", True))
        mouse.on_right_click(lambda: self._on_click(*mouse.get_position(), "right", True))
        keyboard.hook(self._on_key)

    def stop(self):
        self._running = False
        self._flush_text_buffer()
        try:
            mouse.unhook_all()
        except Exception:
            pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    def build_scenario(self, name: str) -> Scenario:
        return Scenario(
            name=name,
            recorded_screen_width=self.screen_w,
            recorded_screen_height=self.screen_h,
            steps=list(self.steps),
        )


# ---------------------------------------------------------------------------
# RENK KONTROLU (COLOR CHECK) - farkli cozunurluklerde calismasi icin
# ---------------------------------------------------------------------------

def get_pixel_color(x: int, y: int):
    """
    Verilen EKRAN koordinatindaki tek pikselin (R, G, B) rengini dondurur.
    """
    screenshot = pyautogui.screenshot()
    sw, sh = screenshot.size
    x = max(0, min(sw - 1, x))
    y = max(0, min(sh - 1, y))
    return screenshot.getpixel((x, y))[:3]


def colors_match(c1, c2, tolerance: int = 10) -> bool:
    """
    Iki RGB rengin verilen tolerans payi icinde ayni sayilip sayilmayacagini
    kontrol eder. Her kanal (R, G, B) icin fark <= tolerance olmali.
    """
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(c1, c2))


def wait_for_color(x: int, y: int, target_color, tolerance: int = 10,
                    timeout_seconds: float = 30.0, poll_interval: float = 0.3,
                    stop_flag: Optional[Callable[[], bool]] = None):
    """
    Belirtilen (x,y) ekran noktasinin rengi, hedef renge (tolerans payi
    icinde) DONENE kadar bekler. Bulursa True doner, sure dolarsa False doner.
    stop_flag: kullanici botu manuel durdurursa True donen fonksiyon (opsiyonel).
    """
    start = time.time()
    while time.time() - start < timeout_seconds:
        if stop_flag and stop_flag():
            return False
        current = get_pixel_color(x, y)
        if colors_match(current, target_color, tolerance):
            return True
        time.sleep(poll_interval)
    return False


def capture_region_around_point(x: int, y: int, half_size: int = 35):
    """
    Verilen (x,y) ekran noktasinin etrafindan kare bir bolge kirpip dondurur.
    half_size: merkezden her yone kac piksel alinacagi (varsayilan 35 -> 70x70 kare).
    Donus: PIL Image nesnesi.
    """
    screenshot = pyautogui.screenshot()
    sw, sh = screenshot.size
    left = max(0, x - half_size)
    top = max(0, y - half_size)
    right = min(sw, x + half_size)
    bottom = min(sh, y + half_size)
    return screenshot.crop((left, top, right, bottom))


# ---------------------------------------------------------------------------
# OYNATMA (PLAYBACK)
# ---------------------------------------------------------------------------

class Player:
    """
    Kaydedilen senaryoyu calistirir. Tekrar sayisi destekler.
    Farkli ekran cozunurlugune oranlama yapar (x_ratio * gercek_genislik).
    """

    def __init__(self, scenario: Scenario, images_dir: str,
                 log_callback: Optional[Callable[[str], None]] = None,
                 step_callback: Optional[Callable[[int, int, int], None]] = None):
        self.scenario = scenario
        self.images_dir = images_dir
        self.log_callback = log_callback or (lambda msg: None)
        self.step_callback = step_callback or (lambda rep, idx, total: None)
        self._stop_requested = False
        self.screen_w, self.screen_h = pyautogui.size()

    def stop(self):
        self._stop_requested = True

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _log(self, msg: str):
        self.log_callback(msg)

    def run(self, repeat_count: int, delay_between_runs: float = 1.0):
        self._stop_requested = False
        total_steps = len(self.scenario.steps)
        for rep in range(1, repeat_count + 1):
            if self._stop_requested:
                self._log(f"Durduruldu. {rep - 1}/{repeat_count} tekrar tamamlandi.")
                return
            self._log(f"--- Tekrar {rep}/{repeat_count} basliyor ---")
            for idx, step in enumerate(self.scenario.steps):
                if self._stop_requested:
                    self._log("Kullanici tarafindan durduruldu.")
                    return
                self.step_callback(rep, idx + 1, total_steps)
                self._execute_step(step)
            self._log(f"--- Tekrar {rep}/{repeat_count} tamamlandi ---")
            if rep < repeat_count and delay_between_runs > 0:
                time.sleep(delay_between_runs)
        self._log(f"Tum islem bitti. Toplam {repeat_count} tekrar yapildi.")

    def _scale_point(self, x_ratio: float, y_ratio: float):
        return int(x_ratio * self.screen_w), int(y_ratio * self.screen_h)

    def _execute_step(self, step: Step):
        try:
            if step.type == "click":
                x, y = self._scale_point(step.x_ratio, step.y_ratio)
                pyautogui.click(x, y)
                self._log(f"Tiklandi: ({x},{y})")

            elif step.type == "double_click":
                x, y = self._scale_point(step.x_ratio, step.y_ratio)
                pyautogui.doubleClick(x, y)
                self._log(f"Cift tiklandi: ({x},{y})")

            elif step.type == "right_click":
                x, y = self._scale_point(step.x_ratio, step.y_ratio)
                pyautogui.rightClick(x, y)
                self._log(f"Sag tiklandi: ({x},{y})")

            elif step.type == "type_text":
                pyautogui.write(step.text, interval=0.02)
                self._log(f"Yazildi: {step.text[:40]}")

            elif step.type == "key":
                pyautogui.press(step.key)
                self._log(f"Tus basildi: {step.key}")

            elif step.type == "sleep":
                time.sleep(step.seconds or 1.0)

            elif step.type == "wait_color":
                x, y = self._scale_point(step.x_ratio, step.y_ratio)
                target_color = (step.target_r, step.target_g, step.target_b)
                self._log(f"Bekleniyor: '{step.label}' @ ({x},{y}) "
                          f"renk={target_color} (en fazla {step.timeout_seconds}sn)")
                found = wait_for_color(
                    x, y, target_color,
                    tolerance=step.color_tolerance,
                    timeout_seconds=step.timeout_seconds,
                    stop_flag=self._should_stop,
                )
                if found:
                    self._log(f"Renk eslesti @ ({x},{y})")
                    if step.on_found_action == "click":
                        pyautogui.click(x, y)
                        self._log(f"Tiklandi (otomatik onay): ({x},{y})")
                else:
                    self._log(f"UYARI: '{step.label}' icin renk eslesmedi "
                              f"({step.timeout_seconds}sn icinde). Adim atlaniyor.")

        except pyautogui.FailSafeException:
            self._stop_requested = True
            self._log("ACIL DURDURMA tetiklendi (mouse sol-ust kose).")
        except Exception as e:
            self._log(f"HATA ({step.type}): {e}")


# ---------------------------------------------------------------------------
# DOSYA ISLEMLERI
# ---------------------------------------------------------------------------

def save_scenario(scenario: Scenario, filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(scenario.to_dict(), f, ensure_ascii=False, indent=2)


def load_scenario(filepath: str) -> Scenario:
    with open(filepath, "r", encoding="utf-8") as f:
        d = json.load(f)
    return Scenario.from_dict(d)
