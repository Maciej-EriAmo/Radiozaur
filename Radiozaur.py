import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import tkinter.messagebox as messagebox
import subprocess
import urllib.request
import urllib.parse
import json
import shutil
from tkinter import filedialog
import os
import sys
import logging
import threading
import random
import time
import socket
import tempfile

APP_NAME = "Radiozaur"
APP_VERSION = "1.4.2"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (https://github.com/Maciej-EriAmo/Radiozaur)"

# --- Katalog bazowy aplikacji ---
# Nuitka --onefile rozpakowuje __file__ do katalogu tymczasowego,
# dlatego dla wersji skompilowanej bierzemy katalog pliku .exe.
if "__compiled__" in globals() or getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "error.log")
ICON_PATH = os.path.join(BASE_DIR, "radiozaur2.ico")

logging.basicConfig(filename=LOG_PATH, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")

# Lista awaryjna – używana tylko, gdy nie uda się pobrać aktualnej listy luster
# z /json/servers (patrz discover_servers()). Nazwy serwerów Radio-Browser
# zmieniają się w czasie, więc hardcode nie może być jedynym źródłem.
FALLBACK_RADIO_BROWSER_SERVERS = [
    "de1.api.radio-browser.info",
    "nl1.api.radio-browser.info",
    "at1.api.radio-browser.info",
    "de2.api.radio-browser.info",
]
SERVER_DISCOVERY_HOST = "all.api.radio-browser.info"
SEARCH_TIMEOUT = 10  # sekundy
DISCOVERY_TIMEOUT = 5  # sekundy
SERVER_CACHE_TTL_SECONDS = 12 * 3600  # lustra bywają wymieniane w ciągu godzin/dni
# /json/servers oddaje osobny wiersz na każdy adres IP (IPv4 + IPv6) tego
# samego hosta – MAX_SERVERS_TO_TRY tnie liczbę prób niezależnie od TTL.
MAX_SERVERS_TO_TRY = 4
IPC_TIMEOUT = 1  # sekundy – komendy głośności mają być szybkie albo wcale
# Krótko po Popen mpv mogło jeszcze nie zdążyć utworzyć named pipe'a na
# Windows (typowy wyścig) – zamiast czekać na jedno "zawieszenie" open(),
# próbujemy kilka razy z krótką przerwą. open() na nieistniejącym pipie
# kończy się błędem od razu (nie wisi), więc retry jest tani.
WINDOWS_PIPE_RETRIES = 3
WINDOWS_PIPE_RETRY_DELAY = 0.1  # sekundy

# --- Tłumaczenia ---
translations = {
    "pl": {
        "title": "🎵 Radiozaur",
        "search": "🔍 Szukaj stacji",
        "searching": "⏳ Szukam...",
        "play": "▶️ Odtwórz wybraną stację",
        "stop": "⏹ Stop",
        "resume": "⏯ Wznów",
        "stream_label": "🎧 Adres strumienia: ",
        "stopped": "⏸ Odtwarzanie zatrzymane",
        "stream_ended": "⚠ Strumień przerwany lub niedostępny",
        "no_station": "Nie ma stacji do wznowienia.",
        "no_selection": "Najpierw wybierz stację z listy.",
        "no_results": "Nie znaleziono stacji.",
        "search_failed": "Wyszukiwanie nie powiodło się",
        "mpv_error": "Nie można uruchomić odtwarzacza",
        "select_mpv": "Nie wybrano poprawnej ścieżki do mpv. Aplikacja zostanie zamknięta.",
        "select_mpv_title": "Wskaż plik odtwarzacza mpv",
        "col_station": "📻 Stacja",
        "col_country": "🌍 Kraj",
        "error_title": "Błąd",
        "info_title": "Informacja",
        "exe_files": "Pliki wykonywalne",
        "all_files": "Wszystkie pliki",
        "favorite_add": "⭐ Dodaj do ulubionych",
        "favorite_remove": "★ Usuń z ulubionych",
        "favorites_btn": "📁 Ulubione",
        "defaults_btn": "🏠 Domyślne stacje",
        "no_favorites": "Brak ulubionych stacji.",
    },
    "en": {
        "title": "🎵 Radiozaur",
        "search": "🔍 Search station",
        "searching": "⏳ Searching...",
        "play": "▶️ Play selected station",
        "stop": "⏹ Stop",
        "resume": "⏯ Resume",
        "stream_label": "🎧 Stream URL: ",
        "stopped": "⏸ Playback stopped",
        "stream_ended": "⚠ Stream ended or unavailable",
        "no_station": "No station to resume.",
        "no_selection": "Select a station from the list first.",
        "no_results": "No stations found.",
        "search_failed": "Station search failed",
        "mpv_error": "Cannot run MPV player",
        "select_mpv": "No valid path to mpv selected. App will close.",
        "select_mpv_title": "Select mpv player executable",
        "col_station": "📻 Station",
        "col_country": "🌍 Country",
        "error_title": "Error",
        "info_title": "Info",
        "exe_files": "Executable files",
        "all_files": "All files",
        "favorite_add": "⭐ Add to favorites",
        "favorite_remove": "★ Remove from favorites",
        "favorites_btn": "📁 Favorites",
        "defaults_btn": "🏠 Default stations",
        "no_favorites": "No favorite stations yet.",
    }
}

current_lang = "pl"  # domyślny język (nadpisywany z config.json)


def t(key):
    """Skrót do tłumaczenia w aktualnym języku."""
    return translations[current_lang][key]


# --- Radiozaur App ---
class RadiozaurApp:
    # (nazwa, url, kraj, stationuuid) – wbudowane stacje nie mają uuid
    # w katalogu Radio-Browser, więc nie rejestrujemy dla nich "kliknięcia".
    DEFAULT_STATIONS = [
        ("RMF FM", "http://195.150.20.242:8000/rmf_fm", "PL", None),
        ("Nowy Świat", "http://stream.rcs.revma.com/ypqt40u0x1zuv", "PL", None),
        ("Polskie Radio 24", "http://stream3.polskieradio.pl:8902/", "PL", None),
    ]

    def __init__(self, root):
        global current_lang
        self.root = root

        self.config = self.load_config()
        if self.config.get("lang") in translations:
            current_lang = self.config["lang"]

        self.root.title(t("title"))
        self.root.geometry("460x620")
        self.root.minsize(400, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.stations_list = list(self.DEFAULT_STATIONS)
        self.favorites = self._load_favorites()
        self.showing_favorites = False

        self.current_process = None
        self.paused_station_url = None
        self.paused_station_uuid = None
        self.player_path = None
        self.search_in_progress = False

        self._servers_cache = None
        self._servers_cache_time = None
        self._servers_lock = threading.Lock()

        # Głośność 0-100, zapamiętywana w config.json i wysyłana do mpv
        # zarówno przy starcie (--volume=), jak i na żywo przez IPC.
        try:
            self.volume = max(0, min(100, int(self.config.get("volume", 100))))
        except (TypeError, ValueError):
            self.volume = 100
        self._volume_debounce_job = None  # uchwyt root.after() do ewentualnego anulowania

        # Bazowa ścieżka IPC: pid identyfikuje ten proces Radiozaura (dwie
        # uruchomione kopie się nie zdepczą), a numer sesji (patrz
        # _next_ipc_path) dokleja się przy KAŻDYM odtworzeniu – nawet gdyby
        # stop_process() nie zdążyło w pełni ubić poprzedniego mpv, nowy
        # proces i tak dostanie inną nazwę socketu/pipe'a.
        if sys.platform.startswith("win"):
            self._ipc_base_path = rf"\\.\pipe\radiozaur-mpv-{os.getpid()}"
        else:
            self._ipc_base_path = os.path.join(tempfile.gettempdir(), f"radiozaur-mpv-{os.getpid()}")
        self._ipc_session = 0
        self._ipc_path = None  # przypisywane na nowo w play_stream() przy każdym odtworzeniu

        self.setup_gui()
        self.root.after(500, self.init_player)
        self.root.after(1000, self.check_process)

    # ------------------------------------------------------------------
    # Konfiguracja
    # ------------------------------------------------------------------
    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                logging.error("Error reading config.json", exc_info=True)
        return {}

    def save_config(self, **changes):
        """Zapisuje zmiany do config.json, zachowując pozostałe klucze."""
        self.config.update(changes)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            logging.error("Error writing config.json", exc_info=True)

    def save_path_to_config(self, file_path):
        self.save_config(mpv_path=file_path)

    def load_path_from_config(self):
        return self.config.get("mpv_path")

    # ------------------------------------------------------------------
    # Ulubione
    # ------------------------------------------------------------------
    def _load_favorites(self):
        """Wczytuje ulubione z config.json. Dopuszcza zarówno stare wpisy
        bez uuid, jak i uszkodzone/nieoczekiwane dane – wtedy po prostu
        pomija wiersz zamiast wywalać całą aplikację."""
        raw = self.config.get("favorites", [])
        favorites = []
        if isinstance(raw, list):
            for entry in raw:
                try:
                    name, url, country = entry[0], entry[1], entry[2]
                    uuid = entry[3] if len(entry) >= 4 else None
                except (TypeError, IndexError, KeyError):
                    continue
                if url:
                    favorites.append((name, url, country, uuid or None))
        return favorites

    def _persist_favorites(self):
        self.save_config(favorites=[list(f) for f in self.favorites])

    def is_favorite(self, url):
        return any(fav_url == url for _, fav_url, _, _ in self.favorites)

    def toggle_favorite(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(t("info_title"), t("no_selection"))
            return
        values = self.tree.item(selected[0], "values")
        if len(values) < 3 or not values[2]:
            return
        name, country, url = values[0], values[1], values[2]
        uuid = values[3] if len(values) >= 4 and values[3] else None

        if self.is_favorite(url):
            self.favorites = [f for f in self.favorites if f[1] != url]
        else:
            self.favorites.append((name, url, country, uuid))
        self._persist_favorites()
        self.update_favorite_button()

        if self.showing_favorites:
            self.fill_tree(self.favorites)

    def update_favorite_button(self, event=None):
        selected = self.tree.selection()
        if selected:
            values = self.tree.item(selected[0], "values")
            url = values[2] if len(values) >= 3 else None
            if url and self.is_favorite(url):
                self.btn_favorite.config(text=t("favorite_remove"))
                return
        self.btn_favorite.config(text=t("favorite_add"))

    def show_favorites(self):
        self.showing_favorites = True
        self.stations_list = list(self.favorites)
        self.fill_tree(self.stations_list)
        if not self.favorites:
            messagebox.showinfo(t("info_title"), t("no_favorites"))

    def show_defaults(self):
        self.showing_favorites = False
        self.stations_list = list(self.DEFAULT_STATIONS)
        self.fill_tree(self.stations_list)

    # ------------------------------------------------------------------
    # Odtwarzacz mpv
    # ------------------------------------------------------------------
    def get_mpv_path(self):
        # 1. ścieżka z konfiguracji
        config_path = self.load_path_from_config()
        if config_path and os.path.isfile(config_path):
            return config_path

        # 2. mpv obok aplikacji (tak jak obiecuje README)
        exe_name = "mpv.exe" if sys.platform.startswith("win") else "mpv"
        local_path = os.path.join(BASE_DIR, exe_name)
        if os.path.isfile(local_path):
            self.save_path_to_config(local_path)
            return local_path

        # 3. mpv w PATH
        auto_path = shutil.which("mpv")
        if auto_path:
            self.save_path_to_config(auto_path)
            return auto_path

        # 4. wybór ręczny – na Linux/macOS mpv nie ma rozszerzenia .exe
        if sys.platform.startswith("win"):
            filetypes = [(t("exe_files"), "*.exe"), (t("all_files"), "*.*")]
        else:
            filetypes = [(t("all_files"), "*")]

        manual_path = filedialog.askopenfilename(
            title=t("select_mpv_title"),
            filetypes=filetypes
        )
        if manual_path and self._looks_like_mpv(manual_path):
            self.save_path_to_config(manual_path)
            return manual_path
        return None

    @staticmethod
    def _looks_like_mpv(path):
        """Sprawdza nazwę pliku dokładnie, żeby np. 'notmpv.exe' nie przeszło."""
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        return stem in ("mpv", "mpv.com")

    def init_player(self):
        self.player_path = self.get_mpv_path()
        if not self.player_path:
            messagebox.showerror(t("error_title"), t("select_mpv"))
            self.root.after(100, self.root.destroy)

    def stop_process(self):
        """Bezpiecznie kończy proces mpv (terminate -> wait -> kill)."""
        proc = self.current_process
        self.current_process = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception:
            logging.error("Error stopping mpv", exc_info=True)
        finally:
            # mpv zwykle sam sprząta swój socket IPC przy wyjściu; to tylko
            # zabezpieczenie na wypadek, gdyby zostawił plik po sobie.
            if not sys.platform.startswith("win"):
                try:
                    os.unlink(self._ipc_path)
                except OSError:
                    pass

    def check_process(self):
        """Cykliczne sprawdzanie, czy mpv nadal żyje (np. padł strumień)."""
        proc = self.current_process
        if proc is not None and proc.poll() is not None:
            # Zwykłe zakończenie strumienia (np. rozłączenie przez serwer radia)
            # to normalna sytuacja, nie awaria aplikacji – logujemy z niższym
            # priorytetem. Nietypowy kod wyjścia zostaje jako warning, żeby
            # było widać w error.log, jeśli mpv faktycznie się wywalił.
            if proc.returncode not in (0, None):
                logging.warning("mpv exited with code %s", proc.returncode)
            self.current_process = None
            # mpv, który padł sam, nie przechodzi przez stop_process() – bez
            # tego jego plik socketu IPC zostawałby w /tmp aż do restartu
            # systemu (kolizji nie ma, bo każda sesja ma inny numer, ale to
            # zwykłe śmieci). Na Windows nazwane potoki nie zostawiają pliku.
            if not sys.platform.startswith("win"):
                try:
                    os.unlink(self._ipc_path)
                except OSError:
                    pass
            self.label_url.config(text=t("stream_ended"))
            self.btn_toggle.config(text=t("resume"), state="normal" if self.paused_station_url else "disabled")
        self.root.after(1000, self.check_process)

    @staticmethod
    def _is_playable_url(url):
        """Radio-Browser to katalog społecznościowy — wpisy potrafią zawierać
        złe albo niebezpieczne schematy (file:, coś z parametrami dla mpv itp.).
        Przepuszczamy tylko zwykłe strumienie http/https.
        """
        try:
            scheme = urllib.parse.urlparse(url).scheme.lower()
        except Exception:
            return False
        return scheme in ("http", "https")

    def _next_ipc_path(self):
        """Zwraca nową ścieżkę IPC na potrzeby kolejnego uruchomienia mpv,
        zwiększając licznik sesji (patrz komentarz w __init__)."""
        self._ipc_session += 1
        suffix = f"-{self._ipc_session}"
        if sys.platform.startswith("win"):
            return self._ipc_base_path + suffix
        return self._ipc_base_path + suffix + ".sock"

    def _send_ipc_command(self, command):
        """Wysyła jedną komendę JSON do działającego mpv przez jego IPC.

        Best-effort: jeśli mpv nie żyje, socket/pipe nie istnieje, albo coś
        pójdzie nie tak, po prostu logujemy i wracamy False – głośność wtedy
        po prostu zadziała dopiero przy następnym odtwarzaniu (--volume=).
        Wołane z osobnego wątku, bo połączenie może się na chwilę zawiesić.
        """
        if self.current_process is None or self.current_process.poll() is not None:
            return False
        payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
        try:
            if sys.platform.startswith("win"):
                # Nazwane potoki Windows da się otworzyć jak zwykły plik do
                # zapisu bez pywin32 – niesprawdzone na 100% na każdej wersji
                # Windows, dlatego całość jest w try/except. Kilka szybkich
                # prób łapie przypadek, gdy mpv jeszcze nie zdążyło utworzyć
                # pipe'a tuż po starcie; open() na nieistniejącym pipe'ie
                # kończy się od razu błędem (nie wisi), więc retry jest tani.
                last_error = None
                for attempt in range(WINDOWS_PIPE_RETRIES):
                    try:
                        with open(self._ipc_path, "r+b", buffering=0) as pipe:
                            pipe.write(payload)
                        return True
                    except OSError as e:
                        last_error = e
                        if attempt < WINDOWS_PIPE_RETRIES - 1:
                            time.sleep(WINDOWS_PIPE_RETRY_DELAY)
                if last_error:
                    raise last_error
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(IPC_TIMEOUT)
                    sock.connect(self._ipc_path)
                    sock.sendall(payload)
            return True
        except Exception:
            logging.warning("mpv IPC command failed: %r", command, exc_info=True)
            return False

    def _volume_label_text(self, vol=None):
        return f"🔊 {self.volume if vol is None else vol}%"

    def _on_volume_drag(self, value):
        """Wywoływane przy KAŻDEJ zmianie wartości suwaka — myszą i klawiaturą
        (strzałki / PageUp-Down po najechaniu focusem na Scale). Etykieta
        odświeża się od razu; zapis do config i komenda IPC idą z niewielkim
        opóźnieniem (debounce), żeby seria szybkich kliknięć klawiatury nie
        wysłała komendy do mpv przy każdym kroku.
        """
        try:
            vol = int(round(float(value)))
        except (TypeError, ValueError):
            return
        self.label_volume.config(text=self._volume_label_text(vol))

        if self._volume_debounce_job is not None:
            self.root.after_cancel(self._volume_debounce_job)
            self._volume_debounce_job = None

        if vol == self.volume:
            # Brak realnej zmiany względem tego, co już zapisane – w tym
            # także ewentualne "syntetyczne" wywołanie command=, które
            # niektóre wersje Tk/ttk odpalają raz przy tworzeniu Scale
            # powiązanego z IntVar. Nic nie planujemy do zapisu.
            return
        self._volume_debounce_job = self.root.after(300, self._commit_volume)

    def _on_volume_release(self, event=None):
        """Puszczenie przycisku myszy na suwaku – commitujemy od razu,
        zamiast czekać na debounce z _on_volume_drag."""
        if self._volume_debounce_job is not None:
            self.root.after_cancel(self._volume_debounce_job)
            self._volume_debounce_job = None
        self._commit_volume()

    def _commit_volume(self):
        """Zapisuje aktualną wartość suwaka do config.json i, jeśli coś gra,
        wysyła ją do mpv przez IPC. Wspólne dla ścieżki myszy i klawiatury."""
        self._volume_debounce_job = None
        vol = int(round(self.volume_var.get()))
        self.volume = vol
        self.save_config(volume=vol)
        self.label_volume.config(text=self._volume_label_text(vol))
        if self.current_process is not None:
            threading.Thread(
                target=self._send_ipc_command,
                args=(["set_property", "volume", vol],),
                daemon=True,
            ).start()

    def play_stream(self, url, uuid=None):
        if not self.player_path:
            messagebox.showerror(t("error_title"), t("mpv_error"))
            return

        if not self._is_playable_url(url):
            logging.warning("Rejected non-http(s) stream URL: %r", url)
            messagebox.showerror(t("error_title"), f"{t('mpv_error')}:\n{url}")
            return

        self.stop_process()

        try:
            self.label_url.config(text=f"{t('stream_label')}{url}")
            self._ipc_path = self._next_ipc_path()
            command = [
                self.player_path,
                "--no-video",
                "--really-quiet",
                "--force-window=no",
                f"--volume={self.volume}",
                f"--input-ipc-server={self._ipc_path}",
                url,
            ]

            popen_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "stdin": subprocess.DEVNULL,
            }
            # Bez tego na Windows przy .exe bez konsoli mpv otwiera własne okno cmd
            if sys.platform.startswith("win"):
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            self.current_process = subprocess.Popen(command, **popen_kwargs)
            self.paused_station_url = url
            self.paused_station_uuid = uuid
            self.btn_toggle.config(text=t("stop"), state="normal")

            # Liczymy "kliknięcie" dopiero, gdy proces faktycznie wystartował –
            # inaczej stacja, która się nie uruchomiła, i tak trafiłaby do
            # statystyk katalogu Radio-Browser.
            self.register_click(uuid)

        except Exception as e:
            logging.error("MPV error", exc_info=True)
            self.current_process = None
            # paused_station_url/uuid celowo zostają nietknięte: stop_process()
            # już zatrzymał poprzednią stację, więc to wciąż najlepszy kandydat
            # do "Wznów". Bez tego wywołania przycisk i etykieta zostają w
            # stanie sprzed nieudanej próby (np. "Stop" mimo że nic nie gra).
            self.update_texts()
            messagebox.showerror(t("error_title"), f"{t('mpv_error')}:\n{e}")

    def toggle_playback(self):
        if self.current_process:
            self.stop_process()
            self.label_url.config(text=t("stopped"))
            self.btn_toggle.config(text=t("resume"))
        elif self.paused_station_url:
            self.play_stream(self.paused_station_url, self.paused_station_uuid)
        else:
            messagebox.showinfo(t("info_title"), t("no_station"))

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------
    def setup_gui(self):
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        # --- język ---
        self.btn_lang = ttk.Button(self.root, text=current_lang.upper(), width=4, command=self.switch_language)
        self.btn_lang.place(relx=1.0, x=-10, y=15, anchor="ne")

        self.entry_search = ttk.Entry(frame, width=30)
        self.entry_search.pack(pady=5)
        self.entry_search.bind("<Return>", lambda e: self.on_search())
        self.entry_search.focus_set()

        self.btn_search = ttk.Button(frame, text=t("search"), bootstyle=PRIMARY, command=self.on_search)
        self.btn_search.pack(pady=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(pady=5, fill="both", expand=True)

        # Ukryte kolumny "url" i "uuid" – dane są przypięte do wiersza,
        # więc nie zależymy od zgodności indeksów drzewa i stations_list.
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("name", "country", "url", "uuid"),
            displaycolumns=("name", "country"),
            show="headings",
            height=10,
            bootstyle=INFO,
        )
        self.tree.heading("name", text=t("col_station"))
        self.tree.heading("country", text=t("col_country"))
        self.tree.column("name", anchor="w", width=280)
        self.tree.column("country", anchor="center", width=80)
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.fill_tree(self.stations_list)

        self.tree.bind("<Double-Button-1>", self.on_tree_select)
        self.tree.bind("<Return>", self.on_tree_select)
        self.tree.bind("<<TreeviewSelect>>", self.update_favorite_button)

        list_buttons = ttk.Frame(frame)
        list_buttons.pack(pady=2, fill="x")
        self.btn_defaults = ttk.Button(list_buttons, text=t("defaults_btn"), bootstyle=SECONDARY, command=self.show_defaults)
        self.btn_defaults.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_favorites_view = ttk.Button(list_buttons, text=t("favorites_btn"), bootstyle=SECONDARY, command=self.show_favorites)
        self.btn_favorites_view.pack(side="left", expand=True, fill="x", padx=2)

        self.btn_favorite = ttk.Button(frame, text=t("favorite_add"), bootstyle=INFO, command=self.toggle_favorite)
        self.btn_favorite.pack(pady=2, fill="x")

        self.btn_play = ttk.Button(frame, text=t("play"), bootstyle=SUCCESS, command=self.on_tree_select)
        self.btn_play.pack(pady=5)

        # Tekst na razie dowolny – update_texts() poniżej ustawi go zgodnie
        # z rzeczywistym stanem (nic jeszcze nie gra na starcie aplikacji).
        self.btn_toggle = ttk.Button(frame, text=t("stop"), bootstyle=WARNING, command=self.toggle_playback)
        self.btn_toggle.pack(pady=5)

        # --- głośność ---
        volume_frame = ttk.Frame(frame)
        volume_frame.pack(pady=(0, 5), fill="x")
        self.label_volume = ttk.Label(volume_frame, text=self._volume_label_text(), width=6, anchor="w")
        self.label_volume.pack(side="left")
        self.volume_var = ttk.IntVar(value=self.volume)
        self.scale_volume = ttk.Scale(
            volume_frame, from_=0, to=100, orient="horizontal",
            variable=self.volume_var, command=self._on_volume_drag,
        )
        self.scale_volume.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.scale_volume.bind("<ButtonRelease-1>", self._on_volume_release)

        self.label_url = ttk.Label(frame, text=t("stream_label"), bootstyle=INFO, anchor="center", wraplength=420)
        self.label_url.pack(pady=10)

        # Na starcie nic nie gra ani nie czeka na wznowienie – dociągamy
        # przycisk Stop/Resume do rzeczywistego stanu zamiast zostawiać
        # mylące "Stop", gdy kliknięcie i tak pokaże tylko komunikat błędu.
        self.update_texts()

    def fill_tree(self, stations):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for name, url, country, uuid in stations:
            self.tree.insert("", "end", values=(name, country, url, uuid or ""))

    def switch_language(self):
        global current_lang
        current_lang = "en" if current_lang == "pl" else "pl"
        self.btn_lang.config(text=current_lang.upper())
        self.save_config(lang=current_lang)
        self.update_texts()

    def update_texts(self):
        self.root.title(t("title"))
        self.btn_search.config(text=t("searching") if self.search_in_progress else t("search"))
        self.btn_play.config(text=t("play"))
        self.btn_defaults.config(text=t("defaults_btn"))
        self.btn_favorites_view.config(text=t("favorites_btn"))
        self.tree.heading("name", text=t("col_station"))
        self.tree.heading("country", text=t("col_country"))
        self.update_favorite_button()
        if self.current_process:
            self.btn_toggle.config(text=t("stop"), state="normal")
            # zachowujemy adres bieżącego strumienia zamiast go kasować
            self.label_url.config(text=f"{t('stream_label')}{self.paused_station_url or ''}")
        else:
            # Resume ma sens tylko, jeśli jest co wznawiać – inaczej przycisk
            # tylko wyskakuje z komunikatem "Nie ma stacji do wznowienia."
            self.btn_toggle.config(
                text=t("resume"),
                state="normal" if self.paused_station_url else "disabled",
            )
            self.label_url.config(text=t("stopped") if self.paused_station_url else t("stream_label"))

    # ------------------------------------------------------------------
    # Wyszukiwanie (Radio-Browser)
    # ------------------------------------------------------------------
    def get_servers(self):
        """Zwraca listę luster Radio-Browser, z leniwym odkrywaniem, cache
        i TTL (lustra bywają wymieniane/padają w skali godzin, nie tylko
        w skali jednej sesji aplikacji).

        Bezpieczne do wołania z wielu wątków naraz (wyszukiwanie i
        rejestracja kliknięcia mogą trafić tu równocześnie) — ale samo
        zapytanie HTTP do /json/servers celowo leci POZA lockiem, żeby jeden
        wątek robiący discovery nie blokował drugiego na czas trwania
        zapytania sieciowego. Cache i timestamp są chronione osobno.
        """
        with self._servers_lock:
            fresh = (
                self._servers_cache is not None
                and self._servers_cache_time is not None
                and (time.monotonic() - self._servers_cache_time) < SERVER_CACHE_TTL_SECONDS
            )
            if fresh:
                return self._servers_cache

        # Discovery bez trzymania locka. Jeśli dwa wątki trafią tu naraz przy
        # zimnym cache, oba odpytają /json/servers równolegle — to niepotrzebne,
        # ale nieszkodliwe (jedno zapytanie HTTP raz na TTL, nie w pętli).
        servers = self._discover_servers()

        with self._servers_lock:
            # Double-check: jeśli w międzyczasie inny wątek już zapisał świeższy
            # wynik, nie nadpisujmy go starszym timestampem bez potrzeby.
            if (
                self._servers_cache_time is None
                or time.monotonic() - self._servers_cache_time >= SERVER_CACHE_TTL_SECONDS
            ):
                self._servers_cache = servers
                self._servers_cache_time = time.monotonic()
            return self._servers_cache

    def _invalidate_servers_cache(self):
        with self._servers_lock:
            self._servers_cache = None
            self._servers_cache_time = None

    @staticmethod
    def _discover_servers():
        """Pobiera aktualną listę serwerów z /json/servers (rozwiązywane przez
        DNS z all.api.radio-browser.info, zgodnie z dokumentacją API).
        W razie awarii wraca do listy awaryjnej wpisanej w kodzie.
        """
        try:
            url = f"https://{SERVER_DISCOVERY_HOST}/json/servers"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=DISCOVERY_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))

            # Bez dict.fromkeys ta sama nazwa trafiłaby na listę kilka razy i
            # przy porażce próbowalibyśmy tego samego serwera wielokrotnie
            # zamiast przejść do kolejnego.
            if not isinstance(data, list):
                raise ValueError(f"expected a JSON list, got {type(data).__name__}")

            names = list(dict.fromkeys(
                item["name"] for item in data
                if isinstance(item, dict) and item.get("name")
            ))
            if names:
                random.shuffle(names)
                return names[:MAX_SERVERS_TO_TRY]
        except Exception:
            logging.warning("Radio-Browser server discovery failed, using fallback list", exc_info=True)
        servers = list(FALLBACK_RADIO_BROWSER_SERVERS)
        random.shuffle(servers)
        return servers[:MAX_SERVERS_TO_TRY]

    def search_stations_by_name(self, query, limit=20):
        """Wywoływane w wątku roboczym – NIE dotyka GUI. Zwraca listę lub rzuca wyjątek."""
        query_encoded = urllib.parse.quote(query)
        last_error = None
        for server in self.get_servers():
            # /stations/search (zamiast /stations/byname) pozwala sortować po
            # liczbie głosów – trafniejsza kolejność wyników niż surowe
            # dopasowanie nazwy.
            url = (
                f"https://{server}/json/stations/search"
                f"?name={query_encoded}&limit={limit}&hidebroken=true"
                f"&order=votes&reverse=true"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as response:
                    data = json.loads(response.read().decode("utf-8"))
                results = []
                for item in data[:limit]:
                    name = (item.get("name") or "").strip() or "?"
                    # url_resolved bywa pustym stringiem, więc .get(..., default) nie wystarczy
                    stream = item.get("url_resolved") or item.get("url")
                    if not stream or not self._is_playable_url(stream):
                        continue
                    country = item.get("countrycode") or "??"
                    uuid = item.get("stationuuid")
                    results.append((name, stream, country, uuid))
                return results
            except Exception as e:
                last_error = e
                logging.error("Station search error on %s", server, exc_info=True)
        # Serwer z odkrycia mógł być tymczasowo martwy – następnym razem spróbujmy
        # odkryć listę na nowo zamiast trzymać się tej samej złej odpowiedzi.
        self._invalidate_servers_cache()
        raise RuntimeError(str(last_error) if last_error else "no server available")

    def register_click(self, uuid):
        """Zgłasza do katalogu Radio-Browser, że stacja została odtworzona,
        i przy okazji zapamiętuje url zwrócony przez /json/url/{uuid} jako
        cel na przyszłe Wznów (Radio-Browser czasem zwraca tam świeższy
        adres niż ten z wyszukiwarki).

        Nie przełącza granego w tej chwili strumienia w locie – to celowe
        uproszczenie, żeby nie rwać aktualnego audio przy odpowiedzi, która
        przychodzi z opóźnieniem. Błędy tylko logujemy, nigdy nie pokazujemy
        w GUI. Wołane w osobnym wątku, żeby nie opóźniać startu odtwarzania.
        """
        if not uuid:
            return

        def worker():
            for server in self.get_servers():
                url = f"https://{server}/json/url/{urllib.parse.quote(uuid)}"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as response:
                        data = json.loads(response.read().decode("utf-8"))
                    resolved = data.get("url") if isinstance(data, dict) else None
                    if resolved and self._is_playable_url(resolved):
                        self.root.after(0, lambda u=uuid, r=resolved: self._on_click_registered(u, r))
                    return
                except Exception:
                    logging.warning("Click registration failed on %s", server, exc_info=True)
            self._invalidate_servers_cache()

        threading.Thread(target=worker, daemon=True).start()

    def _on_click_registered(self, uuid, resolved_url):
        """Wołane w wątku GUI. Podmienia cel Wznów tylko, jeśli to wciąż ta
        sama stacja – użytkownik mógł już przełączyć się na inną, zanim
        odpowiedź z API wróciła."""
        if self.paused_station_uuid == uuid:
            self.paused_station_url = resolved_url

    def on_search(self):
        if self.search_in_progress:
            return
        query = self.entry_search.get().strip()
        if not query:
            # puste pole = powrót do wbudowanej listy
            self.show_defaults()
            return

        self.search_in_progress = True
        self.btn_search.config(text=t("searching"), state="disabled")

        def worker():
            try:
                results = self.search_stations_by_name(query)
                self.root.after(0, lambda res=results: self.on_search_done(res, None))
            except Exception as e:
                # "e" znika po wyjściu z bloku except, więc przypinamy je jako argument domyślny
                self.root.after(0, lambda err=e: self.on_search_done(None, err))

        threading.Thread(target=worker, daemon=True).start()

    def on_search_done(self, results, error):
        """Wywoływane w wątku GUI po zakończeniu wyszukiwania."""
        self.search_in_progress = False
        self.btn_search.config(text=t("search"), state="normal")

        if error is not None:
            messagebox.showerror(t("error_title"), f"{t('search_failed')}:\n{error}")
            return
        if results:
            self.showing_favorites = False
            self.stations_list = results
            self.fill_tree(self.stations_list)
        else:
            messagebox.showinfo(t("info_title"), t("no_results"))

    def on_tree_select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            if event is None:  # kliknięto przycisk, nie dwuklik w pustym miejscu
                messagebox.showinfo(t("info_title"), t("no_selection"))
            return
        values = self.tree.item(selected[0], "values")
        if len(values) >= 3 and values[2]:
            uuid = values[3] if len(values) >= 4 and values[3] else None
            self.play_stream(values[2], uuid)

    # ------------------------------------------------------------------
    def on_close(self):
        if self._volume_debounce_job is not None:
            self.root.after_cancel(self._volume_debounce_job)
            self._volume_debounce_job = None
        self.stop_process()
        self.root.destroy()


if __name__ == "__main__":
    root = ttk.Window(themename="darkly")
    app = RadiozaurApp(root)
    # .ico działa tylko na Windows; brak pliku lub inny system nie może wywalić aplikacji
    try:
        if sys.platform.startswith("win") and os.path.isfile(ICON_PATH):
            root.iconbitmap(ICON_PATH)
    except Exception:
        logging.error("Cannot set window icon", exc_info=True)
    root.mainloop()
