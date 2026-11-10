# -*- coding: utf-8 -*-
import sys
import os
import json
import time
import threading
import subprocess
import ctypes
import traceback
import base64
import tempfile
import hashlib
import requests
from cryptography.fernet import Fernet
from supabase import create_client

try:
    import webview
except ImportError:
    try: ctypes.windll.user32.MessageBoxW(0, "Не найдена библиотека pywebview. Выполните: pip install pywebview", "NimiClean", 0x10)
    except: pass
    sys.exit(1)

# --- НАСТРОЙКИ СУПАБЕЙС ---
SUPABASE_URL = "https://mhiurriviqsnssopwxvz.supabase.co"
SUPABASE_KEY = "sb_publishable_8L2bwIG8hTLtvm0cb78Bwg_4XUrv5eK"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SECRET = b'Z3VhcmRlZF9ieV9uaW1pY2xlYW5fc2VjcmV0X2tleV8xMjM0NTY='
cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET).digest()))

def app_dir():
    if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = app_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ERROR_LOG = os.path.join(BASE_DIR, "nimi_error.log")
LOGO_FILE = os.path.join(BASE_DIR, "logo.png")
LICENSE_FILE = os.path.join(BASE_DIR, "license.dat")
HTML_TEMP = os.path.join(tempfile.gettempdir(), "nimiclean_ui.html")

# --- НАСТРОЙКИ АВТООБНОВЛЕНИЯ ---
CURRENT_VERSION = "1.0.0"
# Ссылка на файл версии в интернете (GitHub Gist, Pastebin или твой сайт)
UPDATE_JSON_URL = "https://raw.githubusercontent.com/твой_профиль/твой_репо/main/version.json"
# -------------------------------------------------------------------

def log_error(stage):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- {stage} ---\n")
            f.write(traceback.format_exc())
    except: pass

def is_admin():
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except: return False

if not is_admin() and "--no-uac" not in sys.argv:
    try:
        args = sys.argv[1:] if getattr(sys, "frozen", False) else [os.path.abspath(sys.argv[0])] + sys.argv[1:]
        params = subprocess.list2cmdline(args)
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, BASE_DIR, 1)
        if ret > 32: sys.exit(0)
    except: log_error("ELEVATE")

def anti_debug():
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent(): os._exit(0)
    except: pass

# ==========================================
# СИСТЕМА АВТООБНОВЛЕНИЯ
# ==========================================
def check_updates():
    """Проверяет наличие новой версии на сервере"""
    try:
        # Пытаемся скачать JSON с информацией о версии
        response = requests.get(UPDATE_JSON_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            latest_version = data.get("latest_version")
            download_url = data.get("download_url")
            
            # Если на сервере версия больше текущей
            if latest_version > CURRENT_VERSION:
                return {"status": "update", "url": download_url, "version": latest_version}
        return {"status": "ok"}
    except Exception as e:
        # Если нет интернета или ссылка битая - просто запускаем программу
        return {"status": "error", "message": str(e)}

def download_and_update(url):
    """Скачивает новый EXE и создает bat-скрипт для замены"""
    try:
        if not getattr(sys, "frozen", False):
            return False # Автообновление работает только в собранном EXE
            
        exe_path = sys.executable
        new_exe_path = exe_path + ".new"
        
        # Скачиваем новый файл
        response = requests.get(url, stream=True)
        with open(new_exe_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # Создаем bat-скрипт, который заменит файл после закрытия текущего процесса
        bat_path = os.path.join(tempfile.gettempdir(), "update_nimi.bat")
        with open(bat_path, "w") as bat:
            bat.write(f'@echo off\n')
            bat.write(f'timeout /t 2 /nobreak > nul\n')
            bat.write(f'del "{exe_path}"\n')
            bat.write(f'move "{new_exe_path}" "{exe_path}"\n')
            bat.write(f'start "" "{exe_path}"\n')
            bat.write(f'del "%~f0"\n')
            
        # Запускаем bat и закрываем текущую программу
        subprocess.Popen([bat_path], shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        sys.exit(0)
    except Exception as e:
        log_error("UPDATE_PROCESS")
        return False

# ==========================================
# СИСТЕМА ЛИЦЕНЗИЙ
# ==========================================
def get_hwid():
    try:
        cmd = 'wmic baseboard get serialnumber'
        output = subprocess.check_output(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW).decode()
        serial = output.split('\n')[1].strip()
        return hashlib.sha256(serial.encode()).hexdigest()[:16]
    except:
        return "UNKNOWN_HWID"

def check_license():
    if not os.path.exists(LICENSE_FILE):
        return None
    try:
        with open(LICENSE_FILE, "rb") as f:
            encrypted = f.read()
        decrypted = cipher.decrypt(encrypted).decode()
        data = json.loads(decrypted)
        key = data.get('key')
        hwid = get_hwid()
        
        if data.get('hwid') != hwid:
            return None
            
        response = supabase.table("keys").select("*").eq("key", key).execute()
        if not response.data:
            return None
            
        key_data = response.data[0]
        if key_data.get('hwid') != hwid:
            return None
            
        return key_data.get('version')
    except Exception as e:
        log_error("CHECK_LICENSE")
        return None

def save_license(key, version, hwid):
    data = json.dumps({"key": key, "version": version, "hwid": hwid})
    encrypted = cipher.encrypt(data.encode())
    with open(LICENSE_FILE, "wb") as f:
        f.write(encrypted)

# ==========================================
# ОСНОВНОЙ КОД УТИЛИТЫ (CLEANER)
# ==========================================
DEFAULT_CONFIG = {"color1": "#8a2be2", "color2": "#00ffff", "is_gradient": True, "snow_enabled": True, "wallpaper_style": "gradient"}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: data = json.load(f)
            cfg = DEFAULT_CONFIG.copy(); cfg.update(data); return cfg
        except: pass
    return DEFAULT_CONFIG.copy()

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
    except: pass

def get_logo_base64():
    try:
        if os.path.exists(LOGO_FILE):
            with open(LOGO_FILE, "rb") as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
                return f"data:image/png;base64,{b64}"
    except: pass
    return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

class CleanerAPI:
    def __init__(self, version="none"):
        self.config = load_config()
        self.is_cleaning = False
        self.version = version

    def get_config(self): return dict(self.config)
    def get_version(self): return self.version
    def minimize(self): 
        try: webview.windows[0].minimize()
        except: pass
        
    def close(self):
        try:
            webview.windows[0].evaluate_js("playOutro();")
        except: 
            pass
            
    def force_close(self):
        try: 
            webview.windows[0].destroy()
        except: 
            pass

    def save_settings(self, color1, color2, is_gradient, snow_enabled, wallpaper_style):
        self.config["color1"] = color1
        self.config["color2"] = color2
        self.config["is_gradient"] = bool(is_gradient)
        self.config["snow_enabled"] = bool(snow_enabled)
        self.config["wallpaper_style"] = wallpaper_style
        save_config(self.config)
        return True

    def activate_key(self, key):
        hwid = get_hwid()
        try:
            response = supabase.table("keys").select("*").eq("key", key).execute()
            if not response.data:
                return {"status": "error", "message": "Ключ не найден"}
            
            key_data = response.data[0]
            saved_hwid = key_data.get('hwid')
            version = key_data.get('version')

            if not saved_hwid:
                supabase.table("keys").update({"hwid": hwid, "activated_at": "now()"}).eq("key", key).execute()
                save_license(key, version, hwid)
                self.version = version
                return {"status": "success", "version": version}
            elif saved_hwid == hwid:
                save_license(key, version, hwid)
                self.version = version
                return {"status": "success", "version": version}
            else:
                return {"status": "error", "message": "Ключ уже привязан к другому ПК"}
        except Exception as e:
            return {"status": "error", "message": "Ошибка сети"}

    def start_cleaning(self):
        if self.is_cleaning: return False
        self.is_cleaning = True
        threading.Thread(target=self._clean_process, daemon=True).start()
        return True

    def log(self, text, color=None):
        try:
            win = webview.windows[0]
            safe = str(text).replace("\\", "\\\\").replace("'", "\\'").replace("\r", " ").replace("\n", " ")
            arg = f"'{color}'" if color else "null"
            win.evaluate_js(f"window.addLog('{safe}', {arg});")
        except: pass

    def notify_done(self):
        try:
            webview.windows[0].evaluate_js("window.onCleaningDone && window.onCleaningDone();")
        except: pass

    def silent_cmd(self, cmd):
        try: subprocess.run(cmd, shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass

    def _clean_process(self):
        try:
            traces_deleted = 0
            self.log("[+] Старт глубокой очистки системы...", "#00ffff")

            self.log("[1/8] Уничтожение USN-журнала файловой системы...")
            res = subprocess.run("fsutil usn deletejournal /d c:", shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                self.log("  |-- USN-журнал успешно удален.")
                traces_deleted += 1
            else:
                self.log("  |-- USN-журнал очищен или недоступен.", "#ffaa00")

            self.log("[2/8] Очистка кэша запущенных файлов (Prefetch)...")
            pf = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Prefetch")
            if os.path.isdir(pf):
                for item in os.listdir(pf):
                    if not item.lower().endswith(".pf") or ".minecraft" in item.lower(): continue
                    try:
                        os.remove(os.path.join(pf, item))
                        traces_deleted += 1
                    except: pass
                self.log("  |-- Кэш Prefetch очищен.")

            self.log("[3/8] Очистка списков последних открытых файлов...")
            recent_paths = [
                os.path.expanduser("~\\AppData\\Roaming\\Microsoft\\Windows\\Recent"),
                os.path.expanduser("~\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\AutomaticDestinations"),
                os.path.expanduser("~\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\CustomDestinations")
            ]
            for rp in recent_paths:
                if os.path.isdir(rp):
                    for item in os.listdir(rp):
                        try:
                            fp = os.path.join(rp, item)
                            if os.path.isfile(fp):
                                os.remove(fp)
                                traces_deleted += 1
                        except: pass
            self.log("  |-- Списки Recent / JumpLists очищены.")

            self.log("[4/8] Сброс записей активности приложений (BAM)...")
            self.silent_cmd(r'reg delete "HKLM\SYSTEM\CurrentControlSet\Services\bam\State\UserSettings" /f')
            traces_deleted += 5
            self.log("  |-- Ветка реестра BAM обнулена.")

            self.log("[5/8] Очистка следов запущенных программ (UserAssist / MuiCache)...")
            self.silent_cmd(r'reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist" /f')
            self.silent_cmd(r'reg delete "HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache" /f')
            traces_deleted += 10
            self.log("  |-- Кэш UserAssist и MuiCache очищен.")

            self.log("[6/8] Удаление временных файлов и логов ошибок...")
            targets = [
                os.path.expanduser("~\\AppData\\Local\\CrashDumps"),
                os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp"),
                os.environ.get("TEMP")
            ]
            for folder in targets:
                if not folder or not os.path.isdir(folder): continue
                for root, dirs, files in os.walk(folder, topdown=False):
                    rl = root.lower()
                    if ".minecraft" in rl or "$recycle.bin" in rl: continue
                    for name in files:
                        try:
                            os.remove(os.path.join(root, name))
                            traces_deleted += 1
                        except: pass
            self.log("  |-- Временные директории и дампы очищены.")

            self.log("[7/8] Очистка следов подключенных накопителей...")
            try:
                setupapi_log = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "inf", "setupapi.dev.log")
                if os.path.exists(setupapi_log):
                    os.remove(setupapi_log)
                    traces_deleted += 1
            except: pass
            self.silent_cmd(r'reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2" /f')
            self.silent_cmd('wevtutil cl "Microsoft-Windows-DriverFrameworks-UserMode/Operational"')
            self.log("  |-- Логи монтирования USB-устройств очищены.")

            self.log("[8/8] Сброс сетевого кэша (DNS)...")
            self.silent_cmd("ipconfig /flushdns")
            traces_deleted += 1
            self.log("  |-- Кэш DNS успешно сброшен.")

            self.log("--------------------------------------------------", "#3a3a3a")
            self.log("[+] ОЧИСТКА СИСТЕМЫ УСПЕШНО ЗАВЕРШЕНА!", "#00ff88")
            self.log(f"[+] Удалено следов и временных объектов: {traces_deleted}", "#00ffff")
            self.log("--------------------------------------------------", "#3a3a3a")

        except Exception:
            log_error("CLEAN_PROCESS")
            self.log("[!] Ошибка модуля очистки. См. nimi_error.log", "#ff6666")
        finally:
            self.is_cleaning = False
            self.notify_done()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@400;500;600;700&family=Caveat:wght@700&family=The+Nautigal:wght@700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
body { background: #000; color: #fff; font-family: 'Inter', -apple-system, sans-serif; height: 100vh; overflow: hidden; display: flex; flex-direction: column; }

#bg-layer { position: fixed; inset: 0; z-index: 0; background: #000; overflow: hidden; opacity: 0; transition: opacity 1.5s ease; }
#bg-layer.show { opacity: 1; }
#bg-layer .mesh { position: absolute; inset: -50%; background: radial-gradient(circle at 30% 30%, var(--c1) 0%, transparent 50%), radial-gradient(circle at 70% 70%, var(--c2) 0%, transparent 50%), radial-gradient(circle at 50% 10%, var(--c1) 0%, transparent 40%); filter: blur(120px); opacity: 0.6; animation: meshFloat 20s ease-in-out infinite alternate; }
#bg-layer .grid-overlay { position: absolute; inset: 0; background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px); background-size: 40px 40px; opacity: 0; transition: opacity 0.8s ease; }
#bg-layer.style-gradient .grid-overlay { opacity: 0; }
#bg-layer.style-minimal { opacity: 0; }
#bg-layer.style-grid .mesh { opacity: 0.3; filter: blur(140px); }
#bg-layer.style-grid .grid-overlay { opacity: 1; }
@keyframes meshFloat { 0% { transform: scale(1) translate(0, 0); } 100% { transform: scale(1.1) translate(2%, 2%); } }

#snow-canvas { position: fixed; inset: 0; pointer-events: none; z-index: 1; opacity: 0.75; display: none; }

#titlebar { height: 42px; flex: 0 0 auto; background: rgba(8,8,8,0.45); backdrop-filter: blur(20px) saturate(140%); display: flex; justify-content: space-between; align-items: center; padding: 0 16px; border-bottom: 1px solid rgba(255,255,255,0.04); -webkit-app-region: drag; z-index: 100; position: relative; opacity: 0; transition: opacity 0.5s ease; pointer-events: none; }
#titlebar.show { opacity: 1; pointer-events: auto; }
.title-left { display: flex; align-items: center; gap: 10px; }
.title-avatar { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; border: 1px solid rgba(255,255,255,0.15); box-shadow: 0 0 10px var(--c1); transition: box-shadow 0.5s ease; -webkit-app-region: no-drag; }
.title-brand { font-family: 'Outfit', sans-serif; font-size: 15px; font-weight: 600; letter-spacing: 0.5px; color: #e0e0e0; }
.title-premium { font-family: 'Outfit', sans-serif; font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; color: #d4b875; background: rgba(212, 184, 117, 0.1); border: 1px solid rgba(212, 184, 117, 0.25); padding: 2px 8px; border-radius: 6px; backdrop-filter: blur(8px); -webkit-app-region: no-drag; box-shadow: inset 0 1px 0 rgba(255,255,255,0.05); margin-left: 2px; }
.window-controls { display: flex; gap: 8px; -webkit-app-region: no-drag; }
.win-btn { width: 12px; height: 12px; border-radius: 50%; cursor: pointer; opacity: 0.85; transition: 0.2s; }
.win-btn:hover { opacity: 1; transform: scale(1.15); }
.btn-min { background: #ffbd2e; }
.btn-close { background: #ff5f56; }

#intro-overlay { position: fixed; inset: 0; background: #000; z-index: 1000; display: flex; justify-content: center; align-items: center; transition: opacity 1.2s ease, filter 1.2s ease; }
#intro-particles { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.saber-container { width: 800px; max-width: 95vw; height: 250px; z-index: 1; opacity: 0; transform: scale(1.05); transition: opacity 1.2s ease, transform 1.2s cubic-bezier(0.22, 1, 0.36, 1); }
.saber-container.show { opacity: 1; transform: scale(1); }
.saber-svg { width: 100%; height: 100%; overflow: visible; }
.saber-ghost { font-family: 'Artisan Signature', 'The Nautigal', 'Caveat', cursive; font-weight: 700; font-size: 110px; letter-spacing: 2px; fill: none; stroke: rgba(255,255,255,0.02); stroke-width: 1.5; opacity: 0; transition: opacity 1s ease; }
.saber-glow { font-family: 'Artisan Signature', 'The Nautigal', 'Caveat', cursive; font-weight: 700; font-size: 110px; letter-spacing: 2px; fill: none; stroke: url(#introGrad); stroke-width: 2.5px; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1200; stroke-dashoffset: 1200; transition: filter 0.5s ease; }
.draw-anim { animation: drawSaber 1.4s cubic-bezier(0.33, 0.01, 0.22, 1) forwards; }
.erase-anim { animation: eraseSaber 1.1s cubic-bezier(0.5, 0, 0.6, 1) forwards; }
@keyframes drawSaber { 0% { stroke-dashoffset: 1200; } 100% { stroke-dashoffset: 0; } }
@keyframes eraseSaber { 0% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: 1200; } }

#app-container { flex: 1; display: flex; opacity: 0; z-index: 2; min-height: 0; position: relative; transition: opacity 1s ease, filter 1s ease, transform 1s ease; }
#app-container.outro-fade { opacity: 0; filter: blur(20px); transform: scale(1.05); pointer-events: none; }

.sidebar { width: 220px; background: rgba(10,10,10,0.25); backdrop-filter: blur(24px) saturate(140%); border-right: 1px solid rgba(255,255,255,0.05); padding: 22px 16px; display: flex; flex-direction: column; gap: 12px; }
.nav-btn { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); padding: 13px 18px; border-radius: 12px; color: #888; font-weight: 600; font-size: 12px; letter-spacing: 1px; cursor: pointer; transition: all 0.25s; text-align: left; font-family: 'Outfit', sans-serif; }
.nav-btn:hover { color: #fff; background: rgba(255,255,255,0.07); transform: translateY(-1px); }

.content-area { flex: 1; padding: 22px; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.page { display: none; height: 100%; flex-direction: column; min-height: 0; }
.page.active { display: flex; }
.section-title { font-family: 'Outfit', sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 1.6px; color: #666; margin-bottom: 14px; text-transform: uppercase; }

#cleaner-stage { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.terminal-container { flex: 1; min-height: 0; background: rgba(15,15,15,0.2); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.05); border-radius: 14px; padding: 18px; font-family: Consolas, 'Courier New', monospace; font-size: 11.5px; line-height: 1.55; overflow-y: auto; display: flex; flex-direction: column; gap: 5px; box-shadow: inset 0 0 24px rgba(0,0,0,0.6); transition: opacity 0.4s ease, transform 0.4s ease; }
.terminal-container.hidden { opacity: 0; transform: scale(0.98); pointer-events: none; }
.terminal-container::-webkit-scrollbar { width: 4px; }
.terminal-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 2px; }
.log-entry { word-break: break-all; white-space: pre-wrap; opacity: 0.9; }
.log-welcome { font-family: 'Outfit', sans-serif; font-size: 16px; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 6px; }

.run-btn-wrap { margin-top: 16px; display: flex; justify-content: center; opacity: 0; transform: translateY(6px); pointer-events: none; transition: opacity 0.3s ease, transform 0.3s ease; }
.run-btn-wrap.show { opacity: 1; transform: translateY(0); pointer-events: auto; }

.glass-btn { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); backdrop-filter: blur(14px) saturate(140%); color: #fff; padding: 12px 30px; border-radius: 12px; font-weight: 600; font-size: 12px; letter-spacing: 1px; cursor: pointer; transition: all 0.25s; font-family: 'Outfit', sans-serif; box-shadow: 0 4px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.06); }
.glass-btn:hover { background: rgba(255,255,255,0.1); box-shadow: 0 6px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.1); }
.glass-btn:active { transform: scale(0.97); }
.glass-btn.primary { border-color: rgba(138,43,226,0.5); }

#progress-stage { position: absolute; inset: 0; display: flex; flex-direction: column; border-radius: 14px; background: rgba(12,12,14,0.3); backdrop-filter: blur(24px) saturate(150%); border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 12px 48px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05); padding: 18px; opacity: 0; transform: scaleY(0.4); transform-origin: top center; pointer-events: none; transition: opacity 0.5s ease, transform 0.9s cubic-bezier(0.22, 1, 0.36, 1); overflow: hidden; }
#progress-stage.open { opacity: 1; transform: scaleY(1); pointer-events: auto; }
#progress-stage.closing { opacity: 0; transform: scaleY(0.4); transition: opacity 0.45s ease, transform 0.6s cubic-bezier(0.5, 0, 0.6, 1); }
#progress-log { flex: 1; min-height: 0; overflow-y: auto; font-family: Consolas, monospace; font-size: 11.5px; line-height: 1.55; display: flex; flex-direction: column; gap: 5px; }
#progress-log::-webkit-scrollbar { width: 4px; }
#progress-log::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 2px; }

#back-btn-wrap { margin-top: 12px; display: flex; justify-content: center; opacity: 0; pointer-events: none; transition: opacity 0.3s ease; }
#back-btn-wrap.show { opacity: 1; pointer-events: auto; }

#activation-overlay { position: absolute; inset: 0; z-index: 500; display: flex; justify-content: center; align-items: center; background: rgba(0,0,0,0.4); backdrop-filter: blur(20px) saturate(120%); opacity: 1; transition: opacity 0.8s ease; }
#activation-overlay.hidden { opacity: 0; pointer-events: none; }
.activation-box { background: rgba(20,20,24,0.6); backdrop-filter: blur(30px) saturate(170%); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 40px; text-align: center; width: 360px; box-shadow: 0 24px 80px rgba(0,0,0,0.8), inset 0 1px 0 rgba(255,255,255,0.1); transform: translateY(20px); opacity: 0; transition: all 0.6s cubic-bezier(0.22, 1, 0.36, 1); }
#activation-overlay:not(.hidden) .activation-box { transform: translateY(0); opacity: 1; }
.activation-box h2 { font-family: 'Outfit', sans-serif; font-size: 22px; margin-bottom: 10px; }
.activation-box p { font-size: 13px; color: #aaa; margin-bottom: 24px; }
.activation-box input { width: 100%; padding: 14px; margin-bottom: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; color: #fff; outline: none; text-align: center; font-size: 18px; letter-spacing: 3px; font-family: monospace; transition: 0.3s; }
.activation-box input:focus { border-color: var(--c1); background: rgba(138,43,226,0.1); }
.activation-box button { width: 100%; padding: 14px; border: none; border-radius: 10px; background: linear-gradient(135deg, var(--c1), var(--c2)); color: #fff; font-weight: 700; font-size: 14px; cursor: pointer; transition: 0.3s; letter-spacing: 1px; font-family: 'Outfit', sans-serif; }
.activation-box button:hover { opacity: 0.9; transform: scale(0.98); }
.activation-box button:disabled { opacity: 0.5; cursor: not-allowed; }
.activation-err { color: #ff5555; font-size: 12px; margin-top: 15px; min-height: 16px; font-weight: 500; }

.settings-grid { display: flex; flex-direction: column; gap: 10px; max-width: 380px; }
.setting-card { background: rgba(15,15,15,0.3); backdrop-filter: blur(16px) saturate(140%); border: 1px solid rgba(255,255,255,0.06); padding: 12px 16px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: inset 0 1px 0 rgba(255,255,255,0.03); position: relative; overflow: visible; }
.setting-label { font-family: 'Inter', sans-serif; font-size: 13px; font-weight: 500; color: #ddd; letter-spacing: 0.2px; }
.color-inputs { display: flex; gap: 10px; }
.custom-picker-btn { width: 26px; height: 26px; border-radius: 50%; cursor: pointer; border: 2px solid rgba(255,255,255,0.2); transition: 0.2s; }
.custom-picker-btn:hover { transform: scale(1.1); border-color: #fff; }

.custom-dropdown { position: relative; width: 130px; }
.dd-trigger { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: #fff; padding: 6px 12px; border-radius: 8px; font-family: 'Inter', sans-serif; font-size: 12px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; transition: 0.2s; }
.dd-trigger:hover { background: rgba(255,255,255,0.1); }
.dd-trigger svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 2; transition: transform 0.3s; }
.custom-dropdown.open .dd-trigger svg { transform: rotate(180deg); }
.dd-menu { position: absolute; top: 60px; right: 16px; width: 130px; background: rgba(15, 15, 20, 0.98); backdrop-filter: blur(24px) saturate(160%); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; opacity: 0; transform: translateY(-6px) scale(0.98); pointer-events: none; transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1); box-shadow: 0 10px 30px rgba(0,0,0,0.9); z-index: 9999; }
.custom-dropdown.open + .dd-menu { opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }
.dd-item { padding: 8px 12px; font-family: 'Inter', sans-serif; font-size: 12px; color: #ccc; cursor: pointer; transition: 0.15s; }
.dd-item:hover { background: rgba(255,255,255,0.15); color: #fff; }
.dd-item.active { color: var(--c1); font-weight: 600; background: rgba(255,255,255,0.05); }

.switch { position: relative; width: 40px; height: 22px; flex: 0 0 auto; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; inset: 0; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.1); border-radius: 22px; transition: 0.3s; }
.slider::before { content: ""; position: absolute; height: 16px; width: 16px; left: 2px; top: 2px; background: #fff; border-radius: 50%; transition: 0.3s; box-shadow: 0 2px 6px rgba(0,0,0,0.5); }
.switch input:checked + .slider { background: rgba(138,43,226,0.5); border-color: rgba(138,43,226,0.6); }
.switch input:checked + .slider::before { transform: translateX(18px); }

#custom-color-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(10px); z-index: 2000; display: none; justify-content: center; align-items: center; opacity: 0; transition: opacity 0.25s; }
#custom-color-modal.show { opacity: 1; }
.color-modal-box { background: rgba(15,15,15,0.85); backdrop-filter: blur(20px) saturate(150%); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 22px; box-shadow: 0 20px 60px rgba(0,0,0,0.85), inset 0 1px 0 rgba(255,255,255,0.06); width: 280px; }
.color-modal-title { font-family: 'Outfit', sans-serif; font-size: 11px; font-weight: 700; color: #888; letter-spacing: 1.2px; margin-bottom: 16px; text-align: center; }
.swatch-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; }
.swatch { width: 100%; aspect-ratio: 1; border-radius: 8px; cursor: pointer; border: 1px solid rgba(255,255,255,0.1); transition: 0.2s; }
.swatch:hover { transform: scale(1.15); box-shadow: 0 0 12px currentColor; }
.hex-input-box { display: flex; gap: 8px; }
.hex-input { flex: 1; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); color: #fff; text-align: center; border-radius: 8px; outline: none; font-family: monospace; letter-spacing: 1px; padding: 8px; }
.hex-btn { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 11px; font-family: 'Outfit', sans-serif; }
.hex-btn:hover { background: rgba(255,255,255,0.18); }

#confirm-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.45); backdrop-filter: blur(14px) saturate(120%); -webkit-backdrop-filter: blur(14px) saturate(120%); z-index: 500; display: none; justify-content: center; align-items: center; opacity: 0; transition: opacity 0.3s ease; }
#confirm-modal.show { opacity: 1; }
.modal-card { background: rgba(20,20,24,0.55); backdrop-filter: blur(24px) saturate(170%); -webkit-backdrop-filter: blur(24px) saturate(170%); border: 1px solid rgba(255,255,255,0.12); border-radius: 18px; padding: 26px 34px; text-align: center; box-shadow: 0 24px 70px rgba(0,0,0,0.75), inset 0 1px 0 rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 22px; transform: scale(0.94); transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1); min-width: 320px; }
#confirm-modal.show .modal-card { transform: scale(1); }
.modal-title { font-family: 'Outfit', sans-serif; font-size: 15px; font-weight: 600; letter-spacing: 0.2px; }
.modal-sub { font-size: 12px; color: #999; margin-top: 6px; }
.modal-btns { display: flex; gap: 12px; justify-content: center; }
.modal-btns .glass-btn { padding: 10px 26px; }
</style>
</head>
<body>

<div id="bg-layer"><div class="mesh"></div><div class="grid-overlay"></div></div>
<canvas id="snow-canvas"></canvas>

<div id="titlebar">
  <div class="title-left">
    <img src="__LOGO_SRC__" class="title-avatar" alt="logo">
    <span class="title-brand">NimiClean</span>
    <span class="title-premium" id="premium-badge" style="display:none;">Premium</span>
  </div>
  <div class="window-controls">
    <div class="win-btn btn-min" onclick="pywebview.api.minimize()"></div>
    <div class="win-btn btn-close" onclick="pywebview.api.close()"></div>
  </div>
</div>

<div id="intro-overlay">
  <canvas id="intro-particles"></canvas>
  <div class="saber-container" id="saber-box">
    <svg class="saber-svg" viewBox="0 0 800 250">
      <defs><linearGradient id="introGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" id="introGradStop1" stop-color="#8a2be2"/><stop offset="1" id="introGradStop2" stop-color="#00ffff"/></linearGradient></defs>
      <text id="ghostText" class="saber-ghost" x="50%" y="160" text-anchor="middle">NimiClean</text>
      <text id="saberText" class="saber-glow" x="50%" y="160" text-anchor="middle">NimiClean</text>
    </svg>
  </div>
</div>

<div id="app-container">
  <div id="activation-overlay" style="display: none;">
    <div class="activation-box">
      <h2>Активация</h2>
      <p>Введите ключ, полученный при покупке.</p>
      <input type="text" id="act-key" placeholder="NIMI-XXXX-XXXX" maxlength="25" autocomplete="off">
      <button onclick="activateKey()" id="act-btn">АКТИВИРОВАТЬ</button>
      <div class="activation-err" id="act-error"></div>
    </div>
  </div>

  <div id="main-ui" style="display: none; flex: 1; min-height: 0; display: flex;">
    <div class="sidebar">
      <button class="nav-btn active" id="btn-cleaner" onclick="switchTab('cleaner')">CLEANER</button>
      <button class="nav-btn" id="btn-settings" onclick="switchTab('settings')">НАСТРОЙКИ</button>
    </div>
    <div class="content-area">
      <div id="page-cleaner" class="page active">
        <div class="section-title">ТЕРМИНАЛ ВЫПОЛНЕНИЯ</div>
        <div id="cleaner-stage">
          <div class="terminal-container" id="terminal-body">
            <div class="log-welcome dynamic-theme-text">SS Bypass Ready</div>
            <div class="log-entry" style="color:#aaa;">[+] Подсистема готова. Нажмите «Запустить очистку» для скрытия следов.</div>
          </div>
          <div class="run-btn-wrap show" id="run-wrap">
            <button class="glass-btn primary dynamic-theme-btn" onclick="requestCleaning()">ЗАПУСТИТЬ ОЧИСТКУ</button>
          </div>
          <div id="progress-stage">
            <div class="section-title" style="margin-bottom:12px; color:#8a8a8a;">ВЫПОЛНЕНИЕ...</div>
            <div id="progress-log"></div>
            <div id="back-btn-wrap"><button class="glass-btn" onclick="closeProgress()">ВЕРНУТЬСЯ В МЕНЮ</button></div>
          </div>
        </div>
      </div>
      
      <div id="page-settings" class="page">
        <div class="section-title">НАСТРОЙКИ ИНТЕРФЕЙСА</div>
        <div class="settings-grid">
          <div class="setting-card"><span class="setting-label">Цветовой акцент</span><div class="color-inputs"><div class="custom-picker-btn" id="btn-picker1" onclick="openColorPicker(1)"></div><div class="custom-picker-btn" id="btn-picker2" onclick="openColorPicker(2)"></div></div></div>
          
          <div class="setting-card" style="z-index: 50;">
            <span class="setting-label">Стиль обоев</span>
            <div class="custom-dropdown" id="wp-dropdown">
              <div class="dd-trigger" onclick="toggleDropdown(event)">
                <span id="wp-selected-text">Градиент</span>
                <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"></polyline></svg>
              </div>
            </div>
            <div class="dd-menu" id="wp-dropdown-menu">
              <div class="dd-item active" data-val="gradient" onclick="selectWallpaper('gradient', 'Градиент')">Градиент</div>
              <div class="dd-item" data-val="minimal" onclick="selectWallpaper('minimal', 'Минимализм')">Минимализм</div>
              <div class="dd-item" data-val="grid" onclick="selectWallpaper('grid', 'Сетка')">Сетка</div>
            </div>
          </div>

          <div class="setting-card"><span class="setting-label">Включить градиент</span><label class="switch"><input type="checkbox" id="toggle-gradient" checked onchange="updateTheme()"><span class="slider"></span></label></div>
          <div class="setting-card"><span class="setting-label">Эффект снега</span><label class="switch"><input type="checkbox" id="toggle-snow" checked onchange="applySnowFromToggle()"><span class="slider"></span></label></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="custom-color-modal" onclick="closeColorPicker(event)"><div class="color-modal-box" onclick="event.stopPropagation()"><div class="color-modal-title">ВЫБЕРИТЕ ЦВЕТ</div><div class="swatch-grid" id="swatch-container"></div><div class="hex-input-box"><input type="text" id="manual-hex" class="hex-input" placeholder="#FFFFFF" maxlength="7"><button class="hex-btn" onclick="applyManualHex()">ОК</button></div></div></div>

<div id="confirm-modal"><div class="modal-card"><div><div class="modal-title">Удалить следы перед проверкой?</div><div class="modal-sub">Все временные файлы и журналы будут очищены.</div></div><div class="modal-btns"><button class="glass-btn" onclick="confirmClean(false)">ОТМЕНА</button><button class="glass-btn primary" onclick="confirmClean(true)">ОЧИСТИТЬ</button></div></div></div>

<script>
var snowOn = false; var snowStarted = false; var activeColor1 = "#8a2be2", activeColor2 = "#00ffff", activePickerIndex = 1; var currentWallpaper = 'gradient';
const NEON_COLORS = ["#ff0055", "#ff00ff", "#8a2be2", "#4a00e0", "#0000ff", "#0088ff", "#00ffff", "#00ff88", "#00ff00", "#aaff00", "#ffff00", "#ffaa00", "#ff5500", "#ff0000", "#ffffff"];
function $(id){ return document.getElementById(id); }
function hexToRgb(hex) { var result = /^#?([a-f\\d]{2})([a-f\\d]{2})([a-f\\d]{2})$/i.exec(hex); return result ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) } : {r: 255, g: 255, b: 255}; }

async function activateKey() {
    const key = $('act-key').value.trim();
    if (!key) return;
    const btn = $('act-btn');
    btn.disabled = true; btn.innerText = 'ПРОВЕРКА...';
    const res = await pywebview.api.activate_key(key);
    if (res.status === 'success') {
        $('activation-overlay').classList.add('hidden');
        $('main-ui').style.display = 'flex';
        if (res.version === 'premium') { $('premium-badge').style.display = 'inline-block'; }
        setTimeout(() => { $('activation-overlay').style.display = 'none'; }, 800);
    } else {
        btn.disabled = false; btn.innerText = 'АКТИВИРОВАТЬ';
        $('act-error').innerText = res.message;
    }
}

function toggleDropdown(e) { e.stopPropagation(); $('wp-dropdown').classList.toggle('open'); }
function selectWallpaper(val, text) { currentWallpaper = val; $('wp-selected-text').textContent = text; document.querySelectorAll('.dd-item').forEach(el => { el.classList.toggle('active', el.getAttribute('data-val') === val); }); $('wp-dropdown').classList.remove('open'); updateWallpaper(); }
document.addEventListener('click', function(e) { if (!e.target.closest('#wp-dropdown')) $('wp-dropdown').classList.remove('open'); });

function updateWallpaper(save) {
    var bg = $('bg-layer'); bg.className = 'style-' + currentWallpaper;
    bg.style.setProperty('--c1', activeColor1); bg.style.setProperty('--c2', activeColor2);
    document.documentElement.style.setProperty('--c1', activeColor1); document.documentElement.style.setProperty('--c2', activeColor2);
    if (save !== false && window.pywebview) pywebview.api.save_settings(activeColor1, activeColor2, $('toggle-gradient').checked, $('toggle-snow').checked, currentWallpaper);
}

let introAnimFrame;
function startIntroParticles() {
    var canvas = $('intro-particles'), ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth; canvas.height = window.innerHeight;
    let rgb1 = hexToRgb(activeColor1), rgb2 = hexToRgb(activeColor2); let pArray = [];
    for(let i=0; i<120; i++) {
        let isGrad = $('toggle-gradient').checked; let c = rgb1;
        if (isGrad) { let r = Math.random(); c = { r: Math.round(rgb1.r*r + rgb2.r*(1-r)), g: Math.round(rgb1.g*r + rgb2.g*(1-r)), b: Math.round(rgb1.b*r + rgb2.b*(1-r)) }; }
        pArray.push({ x: canvas.width/2 + (Math.random() - 0.5) * 600, y: canvas.height/2 + (Math.random() - 0.5) * 300, vx: (Math.random() - 0.5) * 0.6, vy: (Math.random() - 0.5) * 0.6 - 0.4, s: Math.random() * 1.6 + 0.4, col: `rgba(${c.r}, ${c.g}, ${c.b}, 1)`, glow: `rgba(${c.r}, ${c.g}, ${c.b}, 0.8)`, life: 0 });
    }
    function render() {
        ctx.clearRect(0,0, canvas.width, canvas.height);
        pArray.forEach(p => { p.x += p.vx; p.y += p.vy; if (p.life < 0.9) p.life += 0.01; else p.life -= 0.005; if(p.life > 0) { ctx.beginPath(); ctx.arc(p.x, p.y, p.s, 0, Math.PI*2); ctx.fillStyle = p.col; ctx.shadowBlur = 12; ctx.shadowColor = p.glow; ctx.globalAlpha = Math.max(0, Math.min(1, p.life)); ctx.fill(); } });
        ctx.globalAlpha = 1; ctx.shadowBlur = 0; introAnimFrame = requestAnimationFrame(render);
    }
    render();
}

function initIntro(){
  var ready = document.fonts && document.fonts.load ? Promise.race([document.fonts.load("96px 'Artisan Signature'"), new Promise(r => setTimeout(r, 1000))]) : Promise.resolve();
  ready.then(function(){
    setTimeout(function(){
      $('bg-layer').classList.add('show');
      
      setTimeout(function() {
          $('saber-box').classList.add('show'); 
          startIntroParticles();
          setTimeout(function(){
            $('ghostText').style.opacity = '1'; 
            var st = $('saberText');
            setTimeout(function(){
              st.classList.add('draw-anim');
              setTimeout(function(){
                st.classList.remove('draw-anim'); void st.offsetWidth; st.classList.add('erase-anim');
                setTimeout(function(){ 
                    var overlay = $('intro-overlay'); 
                    overlay.style.opacity = '0'; 
                    overlay.style.filter = 'blur(20px)';
                    setTimeout(function(){ 
                        overlay.style.display = 'none'; 
                        
                        $('app-container').style.opacity = '1'; 
                        $('titlebar').classList.add('show');
                        cancelAnimationFrame(introAnimFrame); 
                        checkActivationState(); 
                    }, 800); 
                }, 800); 
              }, 1000); 
            }, 100); 
          }, 200);
      }, 600);
    }, 50);
  });
}

function playOutro() {
    var overlay = $('intro-overlay');
    var st = $('saberText');
    var gt = $('ghostText');
    var app = $('app-container');
    
    $('titlebar').classList.remove('show');
    app.classList.add('outro-fade');
    
    setTimeout(function() {
        overlay.style.display = 'flex';
        overlay.style.transition = 'opacity 1.2s ease, filter 1.2s ease';
        
        requestAnimationFrame(function() {
            overlay.style.opacity = '1';
            overlay.style.filter = 'blur(0px)';
        });
        
        setTimeout(function() {
            st.classList.remove('erase-anim', 'draw-anim');
            st.style.strokeDasharray = '1200';
            st.style.strokeDashoffset = '1200';
            gt.style.opacity = '1';
            
            st.classList.add('draw-anim');
            
            setTimeout(function() {
                overlay.style.opacity = '0';
                overlay.style.filter = 'blur(20px)';
                $('bg-layer').classList.remove('show');
                
                setTimeout(function() {
                    pywebview.api.force_close();
                }, 1000);
                
            }, 1400);
        }, 200);
    }, 300);
}

async function checkActivationState() {
    const v = await pywebview.api.get_version();
    if (v === 'none') {
        $('activation-overlay').style.display = 'flex';
        $('main-ui').style.display = 'none';
    } else {
        $('activation-overlay').style.display = 'none';
        $('main-ui').style.display = 'flex';
        if (v === 'premium') { $('premium-badge').style.display = 'inline-block'; }
    }
}

function buildSwatches() { var cont = $('swatch-container'); NEON_COLORS.forEach(c => { var d = document.createElement('div'); d.className = 'swatch'; d.style.backgroundColor = c; d.style.color = c; d.onclick = function() { selectCustomColor(c); }; cont.appendChild(d); }); }
buildSwatches();
function openColorPicker(index) { activePickerIndex = index; $('manual-hex').value = index === 1 ? activeColor1 : activeColor2; var m = $('custom-color-modal'); m.style.display = 'flex'; requestAnimationFrame(() => m.classList.add('show')); }
function closeColorPicker(e) { if(e && e.target !== $('custom-color-modal')) return; var m = $('custom-color-modal'); m.classList.remove('show'); setTimeout(() => m.style.display = 'none', 220); }
function selectCustomColor(hex) { if (activePickerIndex === 1) activeColor1 = hex; else activeColor2 = hex; closeColorPicker(); updateTheme(); }
function applyManualHex() { var val = $('manual-hex').value.trim(); if (/^#[0-9A-F]{6}$/i.test(val)) selectCustomColor(val); else alert("Неверный формат HEX"); }

function updateTheme(save){
  var c1 = activeColor1, c2 = activeColor2, isGrad = $('toggle-gradient').checked;
  $('btn-picker1').style.backgroundColor = c1; $('btn-picker2').style.backgroundColor = c2;
  var s1 = $('introGradStop1'), s2 = $('introGradStop2'); if (s1 && s2) { s1.setAttribute('stop-color', c1); s2.setAttribute('stop-color', isGrad ? c2 : c1); }
  var st = $('saberText'); if (st) st.style.filter = 'drop-shadow(0 0 5px ' + c1 + ') drop-shadow(0 0 14px ' + (isGrad ? c2 : c1) + ')';
  document.querySelectorAll('.dynamic-theme-text').forEach(el => { if (isGrad) { el.style.background = 'linear-gradient(90deg, ' + c1 + ', ' + c2 + ')'; el.style.webkitBackgroundClip = 'text'; el.style.webkitTextFillColor = 'transparent'; el.style.color = ''; } else { el.style.background = 'none'; el.style.webkitTextFillColor = c1; el.style.color = c1; } });
  document.querySelectorAll('.nav-btn.active').forEach(el => { el.style.background = isGrad ? 'linear-gradient(135deg,' + c1 + '33,' + c2 + '33)' : c1 + '33'; el.style.borderColor = c1; });
  document.querySelectorAll('.dynamic-theme-btn').forEach(el => { if (isGrad) { el.style.borderColor = c1 + '88'; el.style.background = 'linear-gradient(135deg,' + c1 + '22,' + c2 + '22)'; } else { el.style.borderColor = c1 + '88'; el.style.background = c1 + '22'; } });
  updateWallpaper(false);
  if (save !== false && window.pywebview) pywebview.api.save_settings(c1, c2, isGrad, $('toggle-snow').checked, currentWallpaper);
}

function switchTab(tab){
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active')); document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  if (tab === 'cleaner') { $('page-cleaner').classList.add('active'); $('btn-cleaner').classList.add('active'); } else { $('page-settings').classList.add('active'); $('btn-settings').classList.add('active'); }
  updateTheme();
}

function requestCleaning(){ var m = $('confirm-modal'); m.style.display = 'flex'; requestAnimationFrame(() => m.classList.add('show')); }
function confirmClean(ok){
  var m = $('confirm-modal'); m.classList.remove('show'); setTimeout(() => { m.style.display = 'none'; }, 300); if (!ok) return;
  $('terminal-body').classList.add('hidden'); $('run-wrap').classList.remove('show'); $('back-btn-wrap').classList.remove('show'); $('progress-log').innerHTML = '';
  var ps = $('progress-stage'); ps.classList.remove('closing'); requestAnimationFrame(() => ps.classList.add('open'));
  if (window.pywebview) pywebview.api.start_cleaning();
}
function addLog(text, color){ var d = document.createElement('div'); d.className = 'log-entry'; d.textContent = '[' + new Date().toLocaleTimeString('ru-RU') + '] ' + text; if (color) d.style.color = color; var target = $('progress-stage').classList.contains('open') ? $('progress-log') : $('terminal-body'); target.appendChild(d); target.scrollTop = target.scrollHeight; }
window.onCleaningDone = function(){ $('back-btn-wrap').classList.add('show'); };
function closeProgress() { var ps = $('progress-stage'); ps.classList.remove('open'); ps.classList.add('closing'); setTimeout(function(){ ps.classList.remove('closing'); $('terminal-body').classList.remove('hidden'); $('run-wrap').classList.add('show'); $('back-btn-wrap').classList.remove('show'); }, 650); }

function applySnowFromToggle(){ snowOn = $('toggle-snow').checked; $('snow-canvas').style.display = snowOn ? 'block' : 'none'; if (snowOn && !snowStarted) { snowStarted = true; startSnow(); } updateTheme(); }
function startSnow(){
  var canvas = $('snow-canvas'), ctx = canvas.getContext('2d'); function resize(){ canvas.width = window.innerWidth; canvas.height = window.innerHeight; } resize(); window.addEventListener('resize', resize);
  var flakes = Array.from({length: 45}, () => ({ x: Math.random() * canvas.width, y: Math.random() * canvas.height, r: Math.random() * 1.8 + 0.5, s: Math.random() * 0.7 + 0.2, w: Math.random() * 0.4 - 0.2 }));
  (function render(){ if (snowOn) { ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.fillStyle = 'rgba(255,255,255,0.22)'; ctx.beginPath(); flakes.forEach(f => { ctx.moveTo(f.x, f.y); ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2); f.y += f.s; f.x += f.w; if (f.y > canvas.height + 4) { f.y = -4; f.x = Math.random() * canvas.width; } if (f.x > canvas.width + 4) f.x = -4; if (f.x < -4) f.x = canvas.width + 4; }); ctx.fill(); } requestAnimationFrame(render); })();
}

window.addEventListener('pywebviewready', function(){
  pywebview.api.get_config().then(function(cfg){
    if (cfg) { activeColor1 = cfg.color1 || '#8a2be2'; activeColor2 = cfg.color2 || '#00ffff'; $('toggle-gradient').checked = !!cfg.is_gradient; $('toggle-snow').checked = !!cfg.snow_enabled; if (cfg.wallpaper_style) selectWallpaper(cfg.wallpaper_style, cfg.wallpaper_style === 'gradient' ? 'Градиент' : (cfg.wallpaper_style === 'minimal' ? 'Минимализм' : 'Сетка')); }
    updateTheme(false); applySnowFromToggle(); initIntro();
  }).catch(function(){ initIntro(); });
});
</script>
</body>
</html>
"""

def prepare_html():
    logo_src = get_logo_base64()
    html_content = HTML_TEMPLATE.replace("__LOGO_SRC__", logo_src)
    try:
        with open(HTML_TEMP, "w", encoding="utf-8") as f:
            f.write(html_content)
        return HTML_TEMP
    except Exception:
        log_error("HTML_WRITE")
        return html_content

def main():
    anti_debug()
    
    # --- ПРОВЕРКА ОБНОВЛЕНИЙ ---
    update_info = check_updates()
    if update_info.get("status") == "update":
        # В идеале тут можно показать красивое окно, но для простоты используем MsgBox
        ret = ctypes.windll.user32.MessageBoxW(0, f"Доступна новая версия {update_info['version']}!\nОбновить сейчас?", "Обновление NimiClean", 0x04 | 0x40)
        if ret == 6: # Если нажали "Да"
            download_and_update(update_info["url"])
            return
    # ---------------------------

    version = check_license()
    if not version:
        version = "none"
        
    api = CleanerAPI(version=version) 
    
    html_or_path = prepare_html()

    if isinstance(html_or_path, str) and os.path.exists(html_or_path):
        webview.create_window(title="NimiClean", url=html_or_path, js_api=api, width=820, height=510, frameless=True, easy_drag=False, background_color="#000000")
    else:
        webview.create_window(title="NimiClean", html=html_or_path, js_api=api, width=820, height=510, frameless=True, easy_drag=False, background_color="#000000")

    try:
        webview.start(gui="edgechromium", debug=False)
    except:
        webview.start(debug=False)

    try:
        if os.path.exists(HTML_TEMP): os.remove(HTML_TEMP)
    except: pass

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("MAIN_START")