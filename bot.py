import os
import re
import io
import time
import json
import random
import logging
import asyncio
import threading
import requests
import phonenumbers
import pycountry
import speech_recognition as sr
from pydub import AudioSegment
from datetime import datetime
from phonenumbers import region_code_for_number
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
    NoSuchElementException,
)
from seleniumbase import Driver
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    MenuButtonCommands,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("calls.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

BOT_TOKEN = "8546146652:AAFd7AweoTzExT03_RCDeEwDFD_Z__z4x2E"
ADMIN_IDS = [5090817443, 6109365101]
ADMIN_CHAT_ID = str(ADMIN_IDS[0])
OTP_GROUP_ID = -1002630763942
OTP_GROUP_USERNAME = "hotslay"

ORANGE_EMAIL = "saeedgoraya982@gmail.com"
ORANGE_PASSWORD = "77913011"

LOGIN_URL = "https://www.orangecarrier.com/login"
CALL_URL = "https://www.orangecarrier.com/live/calls"
BASE_URL = "https://www.orangecarrier.com"

FORCE_JOIN_CHANNELS = [
    {"name": "Redirect", "username": "hotslay", "url": "https://t.me/hotslay"},
]

DOWNLOAD_FOLDER = "/tmp/calls"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

MAX_ERRORS = 15
CHECK_INTERVAL = 5
REFRESH_PATTERN = [1800, 1545, 2110, 1850, 1340]

SCRIPT_PRICE = {"buy": "contact owner", "rent": "contact owner"}

active_calls = {}
processing_calls = set()
refresh_pattern_index = 0
driver_instance = None
driver_lock = threading.Lock()
bot_application = None


def sc(text):
    normal = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    small = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ0123456789"
    result = []
    for ch in text:
        idx = normal.find(ch)
        if idx != -1:
            result.append(small[idx])
        else:
            result.append(ch)
    return "".join(result)


def country_to_flag(code):
    if not code or len(code) != 2:
        return "🏳️"
    return "".join(chr(127397 + ord(c)) for c in code.upper())


def detect_country(number):
    try:
        clean = re.sub(r"\D", "", number)
        if clean:
            parsed = phonenumbers.parse("+" + clean, None)
            region = region_code_for_number(parsed)
            country = pycountry.countries.get(alpha_2=region)
            if country:
                return country.name, country_to_flag(region)
    except Exception:
        pass
    return "Unknown", "🏳️"


def mask_number(number):
    n = re.sub(r"\D", "", number)
    if len(n) >= 8:
        return n[:4] + "****" + n[-3:]
    return n[:4] + "****" + n[4:]


def log_call(entry):
    try:
        with open("calls.log", "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


async def check_force_join(user_id: int, bot) -> list:
    not_joined = []
    for ch in FORCE_JOIN_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=f"@{ch['username']}", user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)
    return not_joined


def build_force_join_keyboard(not_joined: list, joined_usernames: list) -> InlineKeyboardMarkup:
    rows = []
    all_channels = FORCE_JOIN_CHANNELS
    for ch in all_channels:
        joined = ch["username"] not in [c["username"] for c in not_joined]
        label = ("✅  " if joined else "") + ch["name"]
        rows.append([InlineKeyboardButton(label, url=ch["url"])])
    rows.append([InlineKeyboardButton("ᴠᴇʀɪꜰʏ ᴍᴇᴍʙᴇʀsʜɪᴘ", callback_data="verify_join")])
    return InlineKeyboardMarkup(rows)


def build_force_join_text(not_joined: list) -> str:
    joined_count = len(FORCE_JOIN_CHANNELS) - len(not_joined)
    total = len(FORCE_JOIN_CHANNELS)
    bar_filled = "█" * joined_count
    bar_empty = "░" * (total - joined_count)
    bar = bar_filled + bar_empty
    lines = [
        sc("[ access required ]"),
        sc(f"progress: {joined_count}/{total}  [{bar}]"),
        "",
        sc("join all channels to unlock"),
        sc("tap channel → join → tap verify"),
    ]
    return "\n".join(lines)


async def force_join_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    not_joined = await check_force_join(user_id, context.bot)
    if not not_joined:
        return True
    kb = build_force_join_keyboard(not_joined, [])
    text = build_force_join_text(not_joined)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(text, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb)
    return False


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(sc("status"), callback_data="menu_status"),
            InlineKeyboardButton(sc("buy script"), callback_data="menu_buy"),
        ],
        [
            InlineKeyboardButton(sc("otp group"), url=f"https://t.me/{OTP_GROUP_USERNAME}"),
        ],
    ])


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(sc("status"), callback_data="menu_status"),
            InlineKeyboardButton(sc("buy script"), callback_data="menu_buy"),
        ],
        [
            InlineKeyboardButton(sc("otp group"), url=f"https://t.me/{OTP_GROUP_USERNAME}"),
        ],
        [
            InlineKeyboardButton(sc("set buy price"), callback_data="admin_set_buy"),
            InlineKeyboardButton(sc("set rent price"), callback_data="admin_set_rent"),
        ],
    ])


def buy_script_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(sc("contact owner"), url="https://t.me/mr_afrix")],
        [InlineKeyboardButton(sc("back"), callback_data="menu_back")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await force_join_gate(update, context):
        return
    user = update.effective_user
    is_admin = user.id in ADMIN_IDS
    kb = admin_menu_keyboard() if is_admin else main_menu_keyboard()
    welcome = (
        sc("welcome") + "\n\n"
        + sc("orange carrier live call monitor") + "\n"
        + sc("real-time otp interception system") + "\n\n"
        + sc("use the menu below")
    )
    await update.message.reply_text(welcome, reply_markup=kb)


async def cb_verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    not_joined = await check_force_join(user_id, context.bot)
    if not not_joined:
        await query.answer(sc("verified!"), show_alert=False)
        is_admin = user_id in ADMIN_IDS
        kb = admin_menu_keyboard() if is_admin else main_menu_keyboard()
        welcome = (
            sc("welcome") + "\n\n"
            + sc("orange carrier live call monitor") + "\n"
            + sc("real-time otp interception system") + "\n\n"
            + sc("use the menu below")
        )
        await query.message.edit_text(welcome, reply_markup=kb)
    else:
        kb = build_force_join_keyboard(not_joined, [])
        text = build_force_join_text(not_joined)
        await query.answer(sc("still incomplete — join remaining channels"), show_alert=True)
        await query.message.edit_text(text, reply_markup=kb)


async def cb_menu_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await force_join_gate(update, context):
        return
    await query.answer()
    global driver_instance, active_calls
    driver_alive = driver_instance is not None
    total_active = len(active_calls)
    lines = [
        sc("system status") + "\n",
        sc(f"scraper  :  {'running' if driver_alive else 'offline'}"),
        sc(f"active calls  :  {total_active}"),
        sc(f"monitoring  :  {CALL_URL}"),
    ]
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(sc("back"), callback_data="menu_back")]])
    await query.message.edit_text("\n".join(lines), reply_markup=back_kb)


async def cb_menu_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await force_join_gate(update, context):
        return
    await query.answer()
    buy_p = SCRIPT_PRICE["buy"]
    rent_p = SCRIPT_PRICE["rent"]
    lines = [
        sc("script pricing") + "\n",
        sc(f"purchase price  :  {buy_p}"),
        sc(f"rent price  :  {rent_p}") + "\n",
        sc("tap contact owner to dm the admin"),
    ]
    await query.message.edit_text("\n".join(lines), reply_markup=buy_script_keyboard())


async def cb_menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    is_admin = query.from_user.id in ADMIN_IDS
    kb = admin_menu_keyboard() if is_admin else main_menu_keyboard()
    welcome = (
        sc("welcome") + "\n\n"
        + sc("orange carrier live call monitor") + "\n"
        + sc("real-time otp interception system") + "\n\n"
        + sc("use the menu below")
    )
    await query.message.edit_text(welcome, reply_markup=kb)


async def cb_admin_set_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer(sc("unauthorized"), show_alert=True)
        return
    await query.answer()
    context.user_data["awaiting"] = "set_buy"
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(sc("cancel"), callback_data="menu_back")]])
    await query.message.edit_text(sc("send the new buy price as a message"), reply_markup=back_kb)


async def cb_admin_set_rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer(sc("unauthorized"), show_alert=True)
        return
    await query.answer()
    context.user_data["awaiting"] = "set_rent"
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(sc("cancel"), callback_data="menu_back")]])
    await query.message.edit_text(sc("send the new rent price as a message"), reply_markup=back_kb)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    awaiting = context.user_data.get("awaiting")
    if awaiting == "set_buy":
        SCRIPT_PRICE["buy"] = update.message.text.strip()
        context.user_data.pop("awaiting", None)
        is_admin = update.effective_user.id in ADMIN_IDS
        kb = admin_menu_keyboard() if is_admin else main_menu_keyboard()
        await update.message.reply_text(sc(f"buy price set to: {SCRIPT_PRICE['buy']}"), reply_markup=kb)
    elif awaiting == "set_rent":
        SCRIPT_PRICE["rent"] = update.message.text.strip()
        context.user_data.pop("awaiting", None)
        is_admin = update.effective_user.id in ADMIN_IDS
        kb = admin_menu_keyboard() if is_admin else main_menu_keyboard()
        await update.message.reply_text(sc(f"rent price set to: {SCRIPT_PRICE['rent']}"), reply_markup=kb)


def send_telegram_sync(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        res = requests.post(url, json=payload, timeout=15)
        if res.ok:
            return res.json().get("result", {}).get("message_id")
    except Exception as e:
        log.error(f"send_telegram_sync error: {e}")
    return None


def delete_telegram_message_sync(chat_id, msg_id):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        requests.post(url, json={"chat_id": chat_id, "message_id": msg_id}, timeout=10)
    except Exception:
        pass


def send_voice_sync(chat_id, file_path, caption):
    try:
        if os.path.getsize(file_path) < 10000:
            return False
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVoice"
        with open(file_path, "rb") as vf:
            res = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"voice": vf},
                timeout=90,
            )
        return res.status_code == 200
    except Exception as e:
        log.error(f"send_voice_sync error: {e}")
    return False


def extract_otp_from_audio(audio_path):
    try:
        audio = AudioSegment.from_file(audio_path)
        audio = audio.normalize()
        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        wav_buf.seek(0)
        r = sr.Recognizer()
        with sr.AudioFile(wav_buf) as src:
            r.adjust_for_ambient_noise(src, duration=0.5)
            adata = r.record(src)
        text = None
        for lang in ["en-US", "es-ES", "fr-FR"]:
            try:
                text = r.recognize_google(adata, language=lang)
                break
            except sr.UnknownValueError:
                continue
        if not text:
            return None
        patterns = [
            r"\b(\d{4,6})\b",
            r"code[\s:\-]*(\d{4,6})",
            r"verification[\s:\-]*(\d{4,6})",
            r"password[\s:\-]*(\d{4,6})",
            r"OTP[\s:\-]*(\d{4,6})",
            r"pin[\s:\-]*(\d{4,6})",
            r"(\d{4,6})[\s]*is[\s]*your",
            r"your[\s]*code[\s]*is[\s]*(\d{4,6})",
            r"c[oó]digo[\s:\-]*(\d{4,6})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                otp = m.group(1)
                if otp and otp.isdigit():
                    return otp
        return None
    except Exception as e:
        log.error(f"extract_otp error: {e}")
    return None


def find_chrome_binary():
    candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium",
        "/app/.apt/usr/bin/google-chrome",
        "/opt/google/chrome/chrome",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            log.info(f"chrome binary found: {path}")
            return path
    import shutil
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            log.info(f"chrome binary found via which: {found}")
            return found
    log.warning("no chrome binary found, letting seleniumbase auto-detect")
    return None


def setup_driver():
    chrome_bin = find_chrome_binary()
    kwargs = dict(
        browser="chrome",
        headless=True,
        undetectable=True,
        no_sandbox=True,
        disable_gpu=True,
        incognito=False,
        agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        page_load_strategy="eager",
    )
    if chrome_bin:
        kwargs["binary_location"] = chrome_bin
    driver = Driver(**kwargs)
    driver.set_page_load_timeout(60)
    return driver


def human_delay(mn=0.8, mx=2.2):
    time.sleep(random.uniform(mn, mx))


def human_type(element, text):
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(0.04, 0.13))


def solve_recaptcha_audio(driver):
    try:
        wait = WebDriverWait(driver, 10)
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha']")
        if not frames:
            return True
        driver.switch_to.frame(frames[0])
        try:
            checkbox = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor")))
            human_delay(0.5, 1.2)
            checkbox.click()
            time.sleep(2)
        except Exception:
            pass
        driver.switch_to.default_content()
        time.sleep(1.5)
        challenge_frames = driver.find_elements(By.CSS_SELECTOR, "iframe[title*='recaptcha challenge']")
        if not challenge_frames:
            return True
        driver.switch_to.frame(challenge_frames[0])
        try:
            audio_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "recaptcha-audio-button"))
            )
            human_delay(0.5, 1.0)
            audio_btn.click()
            time.sleep(2)
        except Exception:
            driver.switch_to.default_content()
            return False
        try:
            audio_src = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".rc-audiochallenge-tdownload-link, audio source"))
            )
            audio_url = audio_src.get_attribute("href") or audio_src.get_attribute("src")
        except Exception:
            driver.switch_to.default_content()
            return False
        driver.switch_to.default_content()
        if not audio_url:
            return False
        resp = requests.get(audio_url, timeout=20)
        audio_path = os.path.join(DOWNLOAD_FOLDER, "captcha_audio.mp3")
        with open(audio_path, "wb") as f:
            f.write(resp.content)
        otp = extract_otp_from_audio(audio_path)
        if not otp:
            return False
        driver.switch_to.frame(challenge_frames[0])
        try:
            inp = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "audio-response"))
            )
            human_type(inp, otp)
            human_delay(0.5, 1.0)
            verify_btn = driver.find_element(By.ID, "recaptcha-verify-button")
            verify_btn.click()
            time.sleep(2)
        except Exception:
            driver.switch_to.default_content()
            return False
        driver.switch_to.default_content()
        return True
    except Exception as e:
        log.error(f"solve_recaptcha_audio error: {e}")
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def do_login(driver):
    try:
        log.info("navigating to login page")
        driver.get(LOGIN_URL)
        time.sleep(4)
        wait = WebDriverWait(driver, 20)
        email_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']")))
        human_delay(0.5, 1.2)
        email_field.clear()
        human_type(email_field, ORANGE_EMAIL)
        human_delay(0.4, 1.0)
        pw_field = driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
        pw_field.clear()
        human_type(pw_field, ORANGE_PASSWORD)
        human_delay(0.5, 1.5)
        solved = solve_recaptcha_audio(driver)
        if not solved:
            log.warning("recaptcha solve failed, attempting submit anyway")
        submit_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .btn-login, button.btn"))
        )
        human_delay(0.3, 0.8)
        submit_btn.click()
        time.sleep(6)
        current = driver.current_url
        if "login" not in current:
            log.info(f"login successful — redirected to {current}")
            return True
        page = driver.page_source
        if "dashboard" in page.lower() or "live" in page.lower() or "calls" in page.lower():
            log.info("login successful — detected dashboard content")
            return True
        log.error(f"login failed — still on: {current}")
        return False
    except Exception as e:
        log.error(f"do_login error: {e}")
        return False


def ensure_logged_in(driver):
    try:
        current = driver.current_url
        if "login" in current:
            return do_login(driver)
        src = driver.page_source
        if "logout" in src.lower() or "dashboard" in src.lower() or "live" in src.lower():
            return True
        driver.get(CALL_URL)
        time.sleep(4)
        if "login" in driver.current_url:
            return do_login(driver)
        return True
    except Exception as e:
        log.error(f"ensure_logged_in error: {e}")
        return False


def download_voice_recording(driver, call_info, call_uuid):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(DOWNLOAD_FOLDER, f"call_{call_info['did_number']}_{timestamp}.mp3")
    try:
        with driver_lock:
            play_script = f'if(typeof window.Play === "function"){{ window.Play("{call_info["did_number"]}", "{call_uuid}"); }}'
            driver.execute_script(play_script)
            time.sleep(3)
            cookies = driver.get_cookies()
            ua = driver.execute_script("return navigator.userAgent;")
        session = requests.Session()
        for ck in cookies:
            session.cookies.set(ck["name"], ck["value"])
        headers = {
            "User-Agent": ua,
            "Accept": "audio/mpeg, audio/*, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": CALL_URL,
            "Origin": BASE_URL,
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
        }
        recording_url = f"{BASE_URL}/live/calls/sound?did={call_info['did_number']}&uuid={call_uuid}"
        resp = session.get(recording_url, headers=headers, timeout=45, stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            if "audio" in content_type or "octet-stream" in content_type:
                with open(file_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                if os.path.getsize(file_path) > 10000:
                    log.info(f"voice download ok: {os.path.getsize(file_path)} bytes")
                    return file_path
        log.warning(f"voice download failed: {resp.status_code}")
        return None
    except Exception as e:
        log.error(f"download_voice_recording error: {e}")
        return None


def process_completed_call(call_info, call_uuid):
    try:
        log.info(f"processing completed call: {call_info['did_number']}")
        file_path = download_voice_recording(driver_instance, call_info, call_uuid)
        call_time = call_info["detected_at"].strftime("%Y-%m-%d %I:%M:%S %p")
        masked = mask_number(call_info["did_number"])
        log_entry = f"[{call_time}] CALL | {call_info['did_number']} | {call_info['country']} | {'voice_ok' if file_path else 'voice_fail'}"
        log_call(log_entry)
        caption = (
            f"<b>{sc('new call captured')}</b>\n\n"
            f"{sc('time')}  :  {sc(call_time)}\n"
            f"{call_info['flag']}  {sc(call_info['country'])}\n"
            f"{sc('number')}  :  {sc(masked)}\n"
        )
        if file_path:
            sent = send_voice_sync(OTP_GROUP_ID, file_path, caption)
            if not sent:
                send_telegram_sync(OTP_GROUP_ID, caption, parse_mode="HTML")
            try:
                os.remove(file_path)
            except Exception:
                pass
        else:
            failure_caption = (
                f"<b>{sc('new call captured')}</b>\n\n"
                f"{sc('time')}  :  {sc(call_time)}\n"
                f"{call_info['flag']}  {sc(call_info['country'])}\n"
                f"{sc('number')}  :  {sc(masked)}\n"
                f"{sc('voice')}  :  {sc('download failed')}\n"
            )
            send_telegram_sync(OTP_GROUP_ID, failure_caption, parse_mode="HTML")
    except Exception as e:
        log.error(f"process_completed_call error: {e}")
    finally:
        processing_calls.discard(call_uuid)


def extract_calls(driver):
    global active_calls, processing_calls
    try:
        calls_table = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "LiveCalls"))
        )
        rows = calls_table.find_elements(By.TAG_NAME, "tr")
        current_ids = set()
        for row in rows:
            try:
                row_id = row.get_attribute("id")
                if not row_id:
                    continue
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 5:
                    continue
                did_text = cells[1].text.strip()
                did_number = re.sub(r"\D", "", did_text)
                if not did_number:
                    continue
                current_ids.add(row_id)
                if row_id not in active_calls:
                    log.info(f"new call: {did_number}")
                    country_name, flag = detect_country(did_number)
                    full_url = f"{BASE_URL}/live/calls/sound?did={did_number}&uuid={row_id}"
                    admin_text = f"📞 {did_number}\n🔗 {full_url}"
                    msg_id = send_telegram_sync(ADMIN_CHAT_ID, admin_text)
                    active_calls[row_id] = {
                        "admin_msg_id": msg_id,
                        "flag": flag,
                        "country": country_name,
                        "did_number": did_number,
                        "call_uuid": row_id,
                        "detected_at": datetime.now(),
                        "last_seen": datetime.now(),
                        "full_url": full_url,
                    }
                else:
                    active_calls[row_id]["last_seen"] = datetime.now()
            except StaleElementReferenceException:
                continue
            except Exception as e:
                log.warning(f"row error: {e}")
        completed = [cid for cid in list(active_calls) if cid not in current_ids and cid not in processing_calls]
        for call_id in completed:
            info = active_calls.pop(call_id)
            processing_calls.add(call_id)
            if info.get("admin_msg_id"):
                delete_telegram_message_sync(ADMIN_CHAT_ID, info["admin_msg_id"])
            t = threading.Thread(target=process_completed_call, args=(info, call_id), daemon=True)
            t.start()
    except TimeoutException:
        log.info("no active calls table — page empty")
    except Exception as e:
        log.error(f"extract_calls error: {e}")


def scraper_loop():
    global driver_instance, refresh_pattern_index
    error_count = 0
    pattern_idx = 0
    last_refresh = datetime.now()
    next_interval = REFRESH_PATTERN[pattern_idx]
    while True:
        try:
            if driver_instance is None:
                log.info("starting driver")
                driver_instance = setup_driver()
                if not do_login(driver_instance):
                    log.error("login failed, retrying in 30s")
                    try:
                        driver_instance.quit()
                    except Exception:
                        pass
                    driver_instance = None
                    time.sleep(30)
                    continue
                driver_instance.get(CALL_URL)
                time.sleep(8)
                log.info("scraper started and logged in")
            elapsed = (datetime.now() - last_refresh).total_seconds()
            if elapsed > next_interval:
                log.info(f"scheduled refresh after {next_interval}s")
                with driver_lock:
                    driver_instance.refresh()
                time.sleep(6)
                last_refresh = datetime.now()
                pattern_idx = (pattern_idx + 1) % len(REFRESH_PATTERN)
                next_interval = REFRESH_PATTERN[pattern_idx]
            if not ensure_logged_in(driver_instance):
                log.warning("session expired, re-logging in")
                with driver_lock:
                    if not do_login(driver_instance):
                        raise Exception("re-login failed")
                driver_instance.get(CALL_URL)
                time.sleep(8)
            with driver_lock:
                extract_calls(driver_instance)
            error_count = 0
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            log.info("scraper stopped by user")
            break
        except Exception as e:
            error_count += 1
            log.error(f"scraper loop error [{error_count}]: {e}")
            if error_count >= MAX_ERRORS:
                log.critical("max errors reached, restarting driver")
                try:
                    driver_instance.quit()
                except Exception:
                    pass
                driver_instance = None
                error_count = 0
                time.sleep(15)
            else:
                time.sleep(8)


async def post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "open main menu"),
        ])
    except Exception:
        pass
    scraper_thread = threading.Thread(target=scraper_loop, daemon=True)
    scraper_thread.start()
    log.info("scraper thread launched")


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(cb_verify_join, pattern="^verify_join$"))
    application.add_handler(CallbackQueryHandler(cb_menu_status, pattern="^menu_status$"))
    application.add_handler(CallbackQueryHandler(cb_menu_buy, pattern="^menu_buy$"))
    application.add_handler(CallbackQueryHandler(cb_menu_back, pattern="^menu_back$"))
    application.add_handler(CallbackQueryHandler(cb_admin_set_buy, pattern="^admin_set_buy$"))
    application.add_handler(CallbackQueryHandler(cb_admin_set_rent, pattern="^admin_set_rent$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info("bot starting")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
    )



def start_health_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    port = int(os.environ.get("PORT", 10000))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info(f"health server listening on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    main()


