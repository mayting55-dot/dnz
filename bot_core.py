"""
Bot Cekirdek Modulu
--------------------
Bu modul fare/klavye hareketlerini kaydetme, kaydedilen senaryoyu
tekrar oynatma ve ekranda gorsel arama (template matching) islevlerini icerir.

Farkli ekran cozunurluklerinde calismasi icin:
- Koordinatlar, kayit anindaki ekran boyutuna GORE ORANSAL (yuzdelik) olarak saklanir.
  Oynatma sirasinda o bilgisayarin gercek ekran boyutuna göre yeniden hesaplanir.
- "Bekle ve onayla" adimlari icin gorsel sablon (template image) kullanilir ve
  OpenCV ile birden fazla olcekte (scale) aranir, boylece farkli cozunurluklerde
  goruntu boyutu degisse de bulunabilir.
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
import cv2
import numpy as np

pyautogui.FAILSAFE = True  # Mouse'u ekranin sol-ust kosesine goturursen botu acil durdurur


# ---------------------------------------------------------------------------
# VERI YAPILARI
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """Senaryodaki tek bir adim."""
    type: str  # "click", "double_click", "right_click", "type_text", "wait_image", "key", "sleep"
    # click / double_click / right_click icin oransal koordinat (0.0 - 1.0)
    x_ratio: Optional[float] = None
    y_ratio: Optional[float] = None
    # type_text icin
    text: Optional[str] = None
    # key (tek tus, ornek "enter", "tab") icin
    key: Optional[str] = None
    # sleep icin (saniye)
    seconds: Optional[float] = None
    # wait_image icin: kaydedilen sablon gorselin dosya adi
    image_file: Optional[str] = None
    # wait_image icin: bulunca yapilacak islem ("click" ise tiklar, "none" ise sadece bekler)
    on_found_action: str = "click"
    # wait_image icin: en fazla kac saniye beklenecek (bulunamazsa)
    timeout_seconds: float = 30.0
    # wait_image icin: eslesme hassasiyeti (0.70 - 0.95 arasi onerilir)
    confidence: float = 0.85
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
# GORSEL ARAMA (TEMPLATE MATCHING) - farkli cozunurluklerde calismasi icin
# ---------------------------------------------------------------------------

def find_image_on_screen(template_path: str, confidence: float = 0.85,
                          scales=(1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3)):
    """
    Verilen sablon gorseli ekranda arar. Farkli olceklerde dener,
    cunku baska bir bilgisayarda ekran cozunurlugu/DPI farkli olabilir.

    Donus: (x, y, genislik, yukseklik) eslesen bolgenin EKRAN koordinatlarinda
    merkezi, ya da None (bulunamadiysa).
    """
    screenshot = pyautogui.screenshot()
    screen_np = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_BGR2GRAY)

    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    if template is None:
        return None

    best_val = -1
    best_loc = None
    best_size = None

    th, tw = template.shape[:2]

    for scale in scales:
        new_w = int(tw * scale)
        new_h = int(th * scale)
        if new_w < 8 or new_h < 8:
            continue
        if new_w > screen_gray.shape[1] or new_h > screen_gray.shape[0]:
            continue
        resized = cv2.resize(template, (new_w, new_h))
        result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc
            best_size = (new_w, new_h)

    if best_val >= confidence and best_loc is not None:
        x, y = best_loc
        w, h = best_size
        center_x = x + w // 2
        center_y = y + h // 2
        return (center_x, center_y, w, h)

    return None


def wait_for_image(template_path: str, timeout_seconds: float = 30.0,
                    confidence: float = 0.85, poll_interval: float = 0.5,
                    stop_flag: Optional[Callable[[], bool]] = None):
    """
    Belirtilen sureye kadar gorseli ekranda aramaya devam eder.
    Bulursa konumu dondurur, suresi dolarsa None doner.
    stop_flag: kullanici botu manuel durdurursa True donen fonksiyon (opsiyonel).
    """
    start = time.time()
    while time.time() - start < timeout_seconds:
        if stop_flag and stop_flag():
            return None
        loc = find_image_on_screen(template_path, confidence=confidence)
        if loc:
            return loc
        time.sleep(poll_interval)
    return None


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

            elif step.type == "wait_image":
                img_path = os.path.join(self.images_dir, step.image_file)
                self._log(f"Bekleniyor: '{step.label or step.image_file}' (en fazla {step.timeout_seconds}sn)")
                loc = wait_for_image(
                    img_path,
                    timeout_seconds=step.timeout_seconds,
                    confidence=step.confidence,
                    stop_flag=self._should_stop,
                )
                if loc:
                    x, y, w, h = loc
                    self._log(f"Bulundu @ ({x},{y})")
                    if step.on_found_action == "click":
                        pyautogui.click(x, y)
                        self._log(f"Tiklandi (otomatik onay): ({x},{y})")
                else:
                    self._log(f"UYARI: '{step.label or step.image_file}' bulunamadi, "
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
