import json
import logging
import subprocess
import re
import asyncio
import time
import os
from datetime import datetime, timedelta, timezone
from functools import wraps
import glob
import shlex

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

import pytesseract
from PIL import Image
import io

# --- Constants ---
BOT_VERSION = "1.3.5" # Incremented version
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")
SERVERS_CONFIG_FILE = os.path.join(BASE_DIR, "servers.json")
LOG_FILE = os.path.join(BASE_DIR, "humanode_bot.log")
LOCALES_DIR = os.path.join(BASE_DIR, "locales")
FULL_CHECK_INTERVAL_HOURS = 168
JOB_QUEUE_INTERVAL_MINUTES = 5
GITHUB_SNAPSHOT_URL = "https://api.github.com/repos/stalkerSumy/humanode-telegram-bot/releases/tags/Snap"

# --- Config Loading ---
def load_config():
    """Loads config from config.json."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            print("Successfully loaded config.json.")
            return config
    except FileNotFoundError:
        print(f"CRITICAL: {CONFIG_FILE} not found. Please create it with your bot token and user ID.")
        return {}
    except json.JSONDecodeError:
        print(f"CRITICAL: Could not decode {CONFIG_FILE}. Please check its format.")
        return {}
    except Exception as e:
        print(f"CRITICAL: An unexpected error occurred while loading config.json: {e}")
        return {}

config = load_config()
TOKEN = config.get("telegram_bot_token")
AUTHORIZED_USER_ID = config.get("authorized_user_id")
if isinstance(AUTHORIZED_USER_ID, str) and AUTHORIZED_USER_ID.isdigit():
    AUTHORIZED_USER_ID = int(AUTHORIZED_USER_ID)
GITHUB_TOKEN = config.get("github_token")


# --- Global Lock ---
IS_CHECK_RUNNING = False

# --- Logging Setup ---
logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("webdriver_manager").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Internationalization (i18n) ---
translations = {}

def load_translations():
    try:
        for lang_file in os.listdir(LOCALES_DIR):
            if lang_file.endswith(".json"):
                lang_code = lang_file.split(".")[0]
                with open(os.path.join(LOCALES_DIR, lang_file), 'r', encoding='utf-8') as f:
                    translations[lang_code] = json.load(f)
        logger.info(f"Successfully loaded translations for: {list(translations.keys())}")
    except Exception as e:
        logger.error(f"Could not load translations: {e}", exc_info=True)


def get_text(key: str, lang: str, **kwargs) -> str:
    text = translations.get(lang, translations.get("en", {})).get(key, f"_{key}_")
    if f"_{key}_" == text:
         logger.warning(f"Translation key not found: '{key}' for lang: '{lang}'")
    try:
        return text.format(**kwargs)
    except KeyError as e:
        logger.error(f"Missing placeholder in translation for key '{key}' and lang '{lang}': {e}")
        return text

# --- Server Configuration ---
def load_servers():
    try:
        with open(SERVERS_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.error(f"Could not load or parse {SERVERS_CONFIG_FILE}. Returning empty dict.")
        return {}

def save_servers(servers_dict):
    try:
        with open(SERVERS_CONFIG_FILE, 'w') as f:
            json.dump(servers_dict, f, indent=4)
        global SERVERS
        SERVERS = servers_dict
        return True
    except Exception as e:
        logger.error(f"Failed to save servers file: {e}")
        return False

SERVERS = load_servers()

# --- State Management ---
def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    state.setdefault("user_settings", {})
    state["user_settings"].setdefault(str(AUTHORIZED_USER_ID), {})
    state["user_settings"][str(AUTHORIZED_USER_ID)].setdefault("language", "uk")

    state.setdefault("notification_settings", {
        "first_warning_minutes": 30,
        "second_warning_minutes": 10,
        "alert_interval_minutes": 5,
    })
    state.setdefault("servers", {})

    active_server_ids = SERVERS.keys()
    for server_id in list(state["servers"].keys()):
        if server_id not in active_server_ids:
            del state["servers"][server_id]

    for server_id in active_server_ids:
        state["servers"].setdefault(server_id, {})
        server_state = state["servers"][server_id]
        server_state.setdefault("last_full_check_utc", None)
        server_state.setdefault("bioauth_deadline_utc", None)
        server_state.setdefault("notified_first", False)
        server_state.setdefault("notified_second", False)
        server_state.setdefault("is_in_alert_mode", False)
        server_state.setdefault("last_alert_utc", None)
        server_state.setdefault("is_in_failure_alert_mode", False)
        server_state.setdefault("last_failure_alert_utc", None)

    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")

# --- Decorators ---
def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    if context.user_data and 'lang' in context.user_data:
        return context.user_data['lang']
    
    state = load_state()
    user_id = str(context._user_id or AUTHORIZED_USER_ID)
    lang = state.get("user_settings", {}).get(user_id, {}).get("language", "uk")
    context.user_data['lang'] = lang
    return lang

def translated_action(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        lang = get_user_language(context)
        return await func(update, context, *args, lang=lang, **kwargs)
    return wrapper

# --- Menus and UI ---
@translated_action
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    if update.effective_user.id == AUTHORIZED_USER_ID:
        await update.message.reply_html(get_text("greeting", lang, user_mention=update.effective_user.mention_html()), reply_markup=await main_menu_keyboard(lang))

@translated_action
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    if query: await query.answer()
    keyboard = await main_menu_keyboard(lang)
    text = get_text("main_menu_title", lang) + f"\n\n<i>Bot Version: {BOT_VERSION}</i>"
    if query: 
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            if "Message is not modified" not in str(e): logger.error(f"Error in menu: {e}")
    else: 
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

async def main_menu_keyboard(lang: str):
    keyboard = [
        [InlineKeyboardButton(get_text("btn_notification_settings", lang), callback_data="notification_settings")],
        [InlineKeyboardButton(get_text("btn_language", lang), callback_data="language_menu")],
        *[
            [InlineKeyboardButton(server_info["name"], callback_data=f"select_server_{server_id}")]
            for server_id, server_info in SERVERS.items()
        ],
        [InlineKeyboardButton(get_text("btn_add_server", lang), callback_data="add_server_start")],
    ]
    return InlineKeyboardMarkup(keyboard)

@translated_action
async def select_server(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    server_id = query.data.replace("select_server_", "")
    server_config = SERVERS.get(server_id)
    if not server_config:
        await query.edit_message_text(get_text("msg_error_unknown_server", lang), reply_markup=await main_menu_keyboard(lang))
        return
        
    keyboard = [
        [InlineKeyboardButton(get_text("btn_get_link", lang), callback_data=f"action_get_link_{server_id}")],
        [InlineKeyboardButton(get_text("btn_bioauth_timer", lang), callback_data=f"action_get_bioauth_timer_{server_id}")],
        [InlineKeyboardButton(get_text("btn_node_management", lang), callback_data=f"action_node_management_{server_id}")],
        [InlineKeyboardButton(get_text("btn_tunnel_management", lang), callback_data=f"action_tunnel_management_{server_id}")],
        [InlineKeyboardButton(get_text("btn_backup", lang), callback_data=f"action_backup_menu_{server_id}")],
        [InlineKeyboardButton(get_text("btn_view_log", lang), callback_data=f"action_view_log_{server_id}")],
        [InlineKeyboardButton(get_text("btn_element_screenshot", lang), callback_data=f"action_element_screenshot_{server_id}")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data="main_menu")],
    ]
    await query.edit_message_text(get_text("lbl_selected_server", lang, server_name=server_config['name']), reply_markup=InlineKeyboardMarkup(keyboard))

async def node_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, server_id: str):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(get_text("btn_start_node", lang), callback_data=f"action_start_node_{server_id}"), InlineKeyboardButton(get_text("btn_stop_node", lang), callback_data=f"action_stop_node_{server_id}")],
        [InlineKeyboardButton(get_text("btn_restart_node", lang), callback_data=f"action_restart_node_{server_id}"), InlineKeyboardButton(get_text("btn_status_node", lang), callback_data=f"action_status_node_{server_id}")],
        [InlineKeyboardButton(get_text("btn_version_node", lang), callback_data=f"action_get_node_version_{server_id}"), InlineKeyboardButton(get_text("btn_update_node", lang), callback_data=f"action_update_node_{server_id}")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data=f"select_server_{server_id}")],
    ]
    await query.edit_message_text(get_text("lbl_node_management_title", lang, server_name=SERVERS[server_id]['name']), reply_markup=InlineKeyboardMarkup(keyboard))

async def tunnel_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, server_id: str):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(get_text("btn_start_tunnel", lang), callback_data=f"action_start_tunnel_{server_id}"), InlineKeyboardButton(get_text("btn_stop_tunnel", lang), callback_data=f"action_stop_tunnel_{server_id}")],
        [InlineKeyboardButton(get_text("btn_restart_tunnel", lang), callback_data=f"action_restart_tunnel_{server_id}"), InlineKeyboardButton(get_text("btn_status_tunnel", lang), callback_data=f"action_status_tunnel_{server_id}")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data=f"select_server_{server_id}")],
    ]
    await query.edit_message_text(get_text("lbl_tunnel_management_title", lang, server_name=SERVERS[server_id]['name']), reply_markup=InlineKeyboardMarkup(keyboard))


async def backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, server_id: str):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(get_text("btn_create_local_backup", lang), callback_data=f"action_create_backup_local_{server_id}")],
        [InlineKeyboardButton(get_text("btn_restore_from_backup", lang), callback_data=f"action_restore_menu_{server_id}")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data=f"select_server_{server_id}")],
    ]
    await query.edit_message_text(get_text("lbl_backup_title", lang, server_name=SERVERS[server_id]['name']), reply_markup=InlineKeyboardMarkup(keyboard))

async def restore_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, server_id: str):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(get_text("btn_restore_from_local", lang), callback_data=f"action_restore_local_confirm_{server_id}")],
        [InlineKeyboardButton(get_text("btn_restore_from_github", lang), callback_data=f"action_restore_github_confirm_{server_id}")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data=f"action_backup_menu_{server_id}")],
    ]
    await query.edit_message_text(get_text("lbl_restore_title", lang, server_name=SERVERS[server_id]['name']), reply_markup=InlineKeyboardMarkup(keyboard))

@translated_action
async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(get_text("btn_english", lang), callback_data="set_lang_en")],
        [InlineKeyboardButton(get_text("btn_ukrainian", lang), callback_data="set_lang_uk")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data="main_menu")],
    ]
    await query.edit_message_text(get_text("lbl_language_selection_title", lang), reply_markup=InlineKeyboardMarkup(keyboard))

# --- Settings Conversation ---
@translated_action
async def notification_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    settings = load_state()["notification_settings"]
    text = (f'{get_text("lbl_notification_settings_title", lang)}\n\n'
            f'{get_text("lbl_first_warning", lang, minutes=settings["first_warning_minutes"])}\n'
            f'{get_text("lbl_second_warning", lang, minutes=settings["second_warning_minutes"])}\n'
            f'{get_text("lbl_alert_interval", lang, minutes=settings["alert_interval_minutes"])}'
)
    keyboard = [
        [InlineKeyboardButton(get_text("btn_edit_first_warning", lang), callback_data="edit_setting_first_warning_minutes")],
        [InlineKeyboardButton(get_text("btn_edit_second_warning", lang), callback_data="edit_setting_second_warning_minutes")],
        [InlineKeyboardButton(get_text("btn_edit_alert_interval", lang), callback_data="edit_setting_alert_interval_minutes")],
        [InlineKeyboardButton(get_text("btn_back", lang), callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# --- Utility Functions ---
def create_selenium_driver():
    """Creates and returns a new Selenium Chrome driver instance."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logger.info("Successfully created a new Selenium driver instance.")
        return driver
    except Exception as e:
        logger.error(f"Failed to create Selenium driver: {e}", exc_info=True)
        return None

def format_seconds_to_hhmmss(seconds: int) -> str:
    if seconds < 0:
        return "N/A"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"

def remove_emoji(text: str) -> str:
    emoji_pattern = re.compile("[\U00010000-\U0010ffff]", flags=re.UNICODE)
    return emoji_pattern.sub(r"", text)

def parse_percentage_to_minutes(percentage_str: str, total_epoch_minutes: int = 240) -> int:
    match = re.search(r'width:\s*(\d+\.?\d*)%', percentage_str)
    if match:
        progress_percentage = float(match.group(1))
        remaining_percentage = 100 - progress_percentage
        return int(total_epoch_minutes * (remaining_percentage / 100))
    return -1

# --- Core Bot Logic ---
async def execute_command(server_config: dict, command: str) -> tuple[int, str, str]:
    if not server_config.get("is_local", False):
        shell_command = f"ssh -i {server_config['key_path']} -o StrictHostKeyChecking=no -o ConnectTimeout=10 {server_config['user']}@{server_config['ip']} \"{command}\""
    else:
        shell_command = command
    
    logger.info(f"Executing for '{server_config.get('name', 'N/A')}': {shell_command}")
    try:
        process = await asyncio.create_subprocess_shell(
            shell_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        logger.info(f"Command for '{server_config.get('name', 'N/A')}' finished with code {process.returncode}")
        if stdout:
            logger.info(f"--> STDOUT: {stdout.decode()}")
        if stderr:
            logger.warning(f"--> STDERR: {stderr.decode()}")
        return process.returncode, stdout.decode(), stderr.decode()
    except Exception as e:
        logger.error(f"Exception in execute_command for '{server_config.get('name', 'N/A')}': {e}", exc_info=True)
        return -1, "", str(e)

async def check_and_restart_tunnel_service(server_config: dict, query, lang: str) -> bool:
    server_name = server_config["name"]
    service_name = "humanode-websocket-tunnel.service"

    await query.edit_message_text(get_text("msg_checking_tunnel_status", lang, service_name=service_name, server_name=server_name))

    returncode, stdout, _ = await execute_command(server_config, f"sudo systemctl status {service_name}")
    if returncode == 0 and "Active: active (running)" in stdout:
        return True
    
    await query.edit_message_text(get_text("msg_tunnel_inactive_restarting", lang, service_name=service_name))
    restart_returncode, _, restart_stderr = await execute_command(server_config, f"sudo systemctl restart {service_name}")
    if restart_returncode != 0:
        await query.edit_message_text(get_text("msg_tunnel_restart_failed", lang, error=restart_stderr), parse_mode=ParseMode.HTML)
        return False
    
    await query.edit_message_text(get_text("msg_tunnel_waiting_after_restart", lang))
    await asyncio.sleep(10)

    returncode_after, stdout_after, _ = await execute_command(server_config, f"sudo systemctl status {service_name}")
    if returncode_after == 0 and "Active: active (running)" in stdout_after:
        return True
    
    await query.edit_message_text(get_text("msg_tunnel_not_active", lang, service_name=service_name), parse_mode=ParseMode.HTML)
    return False

async def get_latest_url_from_logs(server_config: dict, query=None, lang: str = "uk"):
    base_url = "https://webapp.mainnet.stages.humanode.io/"

    if query:
        tunnel_ok = await check_and_restart_tunnel_service(server_config, query, lang)
        if not tunnel_ok:
            await query.edit_message_text(get_text("msg_tunnel_failed_to_ensure", lang, server_name=server_config['name']))
            return None
    else:
        service_name = "humanode-websocket-tunnel.service"
        returncode, stdout, _ = await execute_command(server_config, f"sudo systemctl status {service_name}")
        if not (returncode == 0 and "Active: active (running)" in stdout):
            logger.info(f"Tunnel for {server_config['name']} is inactive during background check. Attempting restart.")
            await execute_command(server_config, f"sudo systemctl restart {service_name}")
            await asyncio.sleep(10)

    try:
        log_cmd = "journalctl -u humanode-websocket-tunnel.service -n 200 --no-pager"
        returncode, stdout, stderr = await execute_command(server_config, log_cmd)
        
        if returncode == 0 and stdout:
            latest_timestamp = None
            latest_url = None
            log_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z).*?url=(wss://[^\s]+htunnel\.app)")

            for line in stdout.splitlines():
                match = log_pattern.search(line)
                if match:
                    timestamp_str, url = match.groups()
                    current_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    if latest_timestamp is None or current_timestamp > latest_timestamp:
                        latest_timestamp = current_timestamp
                        latest_url = url
            
            if latest_url:
                encoded_tunnel_url = requests.utils.quote(latest_url, safe='')
                full_url = f"{base_url}open?url={encoded_tunnel_url}"
                logger.info(f"Found most recent tunnel URL for {server_config['name']} via timestamp: {full_url}")
                return full_url
            else:
                logger.warning(f"Could not find any tunnel URL in logs for {server_config['name']}.")
        else:
            logger.error(f"Failed to get logs for tunnel service. Stderr: {stderr}")

    except Exception as e:
        logger.error(f"Error getting URL for {server_config['name']}: {e}")
    
    logger.warning(f"Could not find any URL for {server_config['name']}.")
    return None

def get_bioauth_and_epoch_times(driver: webdriver.Chrome, url: str) -> tuple[int, int]:
    if not url:
        logger.warning("Skipping Selenium check for empty URL.")
        return -1, -1

    bioauth_seconds = -1
    epoch_minutes = -1

    try:
        wait = WebDriverWait(driver, 90)  # Total wait time of 90 seconds
        logger.info(f"Selenium: Navigating to URL: {url}")
        driver.get(url)

        # This is the most reliable way: wait for the dashboard button to be clickable.
        # This single wait handles both fast and slow page loads.
        dashboard_accordion_xpath = "//span[contains(text(), 'Dashboard')]/ancestor::div[contains(@class, 'MuiAccordionSummary-root')]";
        logger.info("Waiting for the dashboard to be clickable...")
        wait.until(EC.element_to_be_clickable((By.XPATH, dashboard_accordion_xpath))).click()
        logger.info("Dashboard clicked.")

        timers_container_xpath = "//div[contains(@class, 'MuiAccordionDetails-root')]//div[contains(@class, 'css-ak0d3g')]";
        timers_container = wait.until(EC.visibility_of_element_located((By.XPATH, timers_container_xpath)))
        
        # EXPERIMENT: Instead of waiting for a specific element, we use a fixed
        # delay, just like in the working take_element_screenshot function.
        # This will help determine if the problem is with the wait condition itself.
        logger.info("Using fixed 10-second delay instead of smart wait.")
        time.sleep(10)

        screenshot_bytes = timers_container.screenshot_as_png
        image = Image.open(io.BytesIO(screenshot_bytes))
        ocr_text = pytesseract.image_to_string(image)
        logger.info(f"OCR Result:\n---\n{ocr_text}\n---")

        # More robust regex for HHH:MM:SS format
        bioauth_match = re.search(r'(\d{1,3})\s*:\s*(\d{2})\s*:\s*(\d{2})', ocr_text)
        if bioauth_match:
            h, m, s = map(int, bioauth_match.groups())
            bioauth_seconds = timedelta(hours=h, minutes=m, seconds=s).total_seconds()
            logger.info(f"Parsed Bio-authentication time: {bioauth_seconds} seconds")

        # Regex for epoch time
        progress_match = re.search(r'Progress:\s*(\d+)\s*hr[s]?\s*(\d+)\s*min', ocr_text, re.IGNORECASE)
        if progress_match:
            total_duration = timedelta(hours=4)
            progress_duration = timedelta(hours=int(progress_match.group(1)), minutes=int(progress_match.group(2)))
            remaining_duration = total_duration - progress_duration
            epoch_minutes = int(remaining_duration.total_seconds() / 60)
            logger.info(f"Parsed Epoch time remaining via OCR: {epoch_minutes} minutes")
        else:
            logger.warning("Could not parse Epoch time from OCR text. Checking for progress bar as a fallback.")
            try:
                epoch_progress_xpath = ".//p[contains(text(), 'Epoch')]/following-sibling::div//div[contains(@class, 'MuiLinearProgress-bar')]";
                epoch_element = timers_container.find_element(By.XPATH, epoch_progress_xpath)
                if epoch_element:
                    style_attribute = epoch_element.get_attribute("style")
                    epoch_minutes = parse_percentage_to_minutes(style_attribute)
                    logger.info(f"Fallback to percentage succeeded. Minutes remaining: {epoch_minutes}")
            except Exception as e:
                logger.warning(f"Fallback to percentage also failed: {e}")

    except Exception as e:
        logger.error("An exception occurred in get_bioauth_and_epoch_times.", exc_info=True)
        try:
            driver.save_screenshot(os.path.join(BASE_DIR, "selenium_error_ocr.png"))
            with open(os.path.join(BASE_DIR, "selenium_page_source_ocr.html"), "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except Exception as dump_e:
            logger.error(f"Failed to save screenshot or page source. Dump error: {dump_e}")
        return -1, -1
    
    return int(bioauth_seconds), int(epoch_minutes)

async def periodic_bioauth_check(context: ContextTypes.DEFAULT_TYPE):
    global IS_CHECK_RUNNING
    if IS_CHECK_RUNNING:
        logger.info("Skipping periodic check: a previous check is still in progress.")
        return

    IS_CHECK_RUNNING = True
    try:
        logger.info("Running periodic bioauth check...")
        state = load_state()
        now_utc = datetime.now(timezone.utc)
        settings = state["notification_settings"]
        lang = state.get("user_settings", {}).get(str(AUTHORIZED_USER_ID), {}).get("language", "uk")

        driver = create_selenium_driver()
        if not driver:
            logger.error("Failed to create Selenium driver for periodic check. Skipping this run.")
            IS_CHECK_RUNNING = False # Make sure to reset the lock
            return

        try:
            for server_id, server_config in SERVERS.items():
                server_state = state["servers"][server_id]
                data_retrieved_successfully = False

                last_check_str = server_state.get("last_full_check_utc")
                perform_full_check = not last_check_str or (now_utc - datetime.fromisoformat(last_check_str) > timedelta(hours=FULL_CHECK_INTERVAL_HOURS))

                if perform_full_check:
                    logger.info(f"Performing full bioauth check for {server_config['name']}.")
                    url = await get_latest_url_from_logs(server_config, lang=lang)
                    if url:
                        bioauth_seconds, epoch_minutes = await asyncio.to_thread(get_bioauth_and_epoch_times, driver, url)
                        
                        if bioauth_seconds > 0:
                            deadline = now_utc + timedelta(seconds=bioauth_seconds)
                            server_state.update({
                                "bioauth_deadline_utc": deadline.isoformat(), "last_full_check_utc": now_utc.isoformat(),
                                "notified_first": False, "notified_second": False, "is_in_alert_mode": False,
                                "is_in_failure_alert_mode": False
                            })
                            data_retrieved_successfully = True
                            logger.info(f"Successfully retrieved bioauth time for {server_config['name']}: {bioauth_seconds}s")
                        elif bioauth_seconds == -1 and epoch_minutes > -1:
                            data_retrieved_successfully = True
                            server_state.update({
                                "bioauth_deadline_utc": None, "last_full_check_utc": now_utc.isoformat(),
                                "is_in_failure_alert_mode": False
                            })
                            logger.info(f"Successfully checked {server_config['name']}. Bioauth time not present (normal). Epoch minutes: {epoch_minutes}")

                    if data_retrieved_successfully and server_state.get("is_in_failure_alert_mode"):
                        server_state["is_in_failure_alert_mode"] = False
                        await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_info_data_retrieval_restored", lang, server_name=server_config['name']), parse_mode=ParseMode.HTML)

                    if not data_retrieved_successfully:
                        if not server_state.get("is_in_failure_alert_mode"):
                            server_state["is_in_failure_alert_mode"] = True
                            server_state["last_failure_alert_utc"] = now_utc.isoformat()
                            await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_critical_data_failure", lang, server_name=server_config['name']), parse_mode=ParseMode.HTML)
                        else:
                            last_alert_str = server_state.get("last_failure_alert_utc")
                            if not last_alert_str or (now_utc - datetime.fromisoformat(last_alert_str) > timedelta(minutes=settings.get("alert_interval_minutes", 5) * 2)):
                                server_state["last_failure_alert_utc"] = now_utc.isoformat()
                                await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_critical_data_failure_repeat", lang, server_name=server_config['name']), parse_mode=ParseMode.HTML)

                deadline_str = server_state.get("bioauth_deadline_utc")
                if not deadline_str: continue

                deadline = datetime.fromisoformat(deadline_str)
                time_left = deadline - now_utc

                if time_left.total_seconds() < 0:
                    if not server_state.get("is_in_alert_mode"):
                        server_state["is_in_alert_mode"] = True
                        server_state["last_alert_utc"] = now_utc.isoformat()
                        await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_alert_bioauth_overdue", lang, server_name=server_config['name']), parse_mode=ParseMode.HTML)
                    else:
                        last_alert_str = server_state.get("last_alert_utc")
                        if not last_alert_str or (now_utc - datetime.fromisoformat(last_alert_str) > timedelta(minutes=settings.get("alert_interval_minutes", 5))):
                            server_state["last_alert_utc"] = now_utc.isoformat()
                            await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_alert_bioauth_overdue_repeat", lang, server_name=server_config['name']), parse_mode=ParseMode.HTML)

                elif time_left < timedelta(minutes=settings["second_warning_minutes"]) and not server_state.get("notified_second"):
                    await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_warning_bioauth_soon_second", lang, server_name=server_config['name'], minutes=settings['second_warning_minutes']), parse_mode=ParseMode.HTML)
                    server_state["notified_second"] = True
                elif time_left < timedelta(minutes=settings["first_warning_minutes"]) and not server_state.get("notified_first"):
                    await context.bot.send_message(AUTHORIZED_USER_ID, get_text("msg_warning_bioauth_soon_first", lang, server_name=server_config['name'], minutes=settings['first_warning_minutes']), parse_mode=ParseMode.HTML)
                    server_state["notified_first"] = True
        finally:
            if driver:
                driver.quit()
            
        save_state(state)
    finally:
        IS_CHECK_RUNNING = False
        logger.info("Periodic check finished.")

@translated_action
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    new_lang = query.data.replace("set_lang_", "")
    
    state = load_state()
    user_id = str(update.effective_user.id)
    state["user_settings"][user_id]["language"] = new_lang
    save_state(state)
    context.user_data['lang'] = new_lang
    
    await menu(update, context)

(EDIT_SETTING_STATE,) = range(1)

@translated_action
async def edit_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    setting_key = query.data.replace("edit_setting_", "")
    context.user_data['setting_to_edit'] = setting_key
    current_value = load_state()["notification_settings"].get(setting_key, "N/A")
    await query.edit_message_text(get_text("lbl_current_value", lang, value=current_value), parse_mode=ParseMode.HTML)
    return EDIT_SETTING_STATE

@translated_action
async def update_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    setting_key = context.user_data.get('setting_to_edit')
    if not setting_key:
        await update.message.reply_text(get_text("msg_error_session_expired", lang))
        await menu(update, context)
        return ConversationHandler.END
    try:
        new_value = int(update.message.text)
        if new_value <= 0:
            await update.message.reply_text(get_text("msg_error_value_must_be_positive", lang))
            return EDIT_SETTING_STATE
        state = load_state()
        state["notification_settings"][setting_key] = new_value
        save_state(state)
        await update.message.reply_text(get_text("msg_success_settings_updated", lang))
        del context.user_data['setting_to_edit']
        await menu(update, context)
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text(get_text("msg_error_enter_number", lang))
        return EDIT_SETTING_STATE

@translated_action
async def handle_generic_action(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Define a mapping from action prefixes to their handler functions.
    action_map = {
        "action_node_management": node_management_menu,
        "action_tunnel_management": tunnel_management_menu,
        "action_backup_menu": backup_menu,
        "action_restore_menu": restore_menu,
        "action_get_link": get_link_action,
        "action_get_bioauth_timer": get_bioauth_timer_action,
        "action_view_log": view_log_action,
        "action_start_node": lambda u, c, l, s: node_service_action(u, c, l, s, 'start'),
        "action_stop_node": lambda u, c, l, s: node_service_action(u, c, l, s, 'stop'),
        "action_restart_node": lambda u, c, l, s: node_service_action(u, c, l, s, 'restart'),
        "action_status_node": lambda u, c, l, s: node_service_action(u, c, l, s, 'status'),
        "action_start_tunnel": lambda u, c, l, s: tunnel_service_action(u, c, l, s, 'start'),
        "action_stop_tunnel": lambda u, c, l, s: tunnel_service_action(u, c, l, s, 'stop'),
        "action_restart_tunnel": lambda u, c, l, s: tunnel_service_action(u, c, l, s, 'restart'),
        "action_status_tunnel": lambda u, c, l, s: tunnel_service_action(u, c, l, s, 'status'),
        "action_get_node_version": get_node_version_action,
        "action_update_node": update_node_action,
        "action_create_backup_local": create_local_backup_action,
        "action_element_screenshot": get_element_screenshot_action,
        "action_restore_local_confirm": lambda u, c, l, s: confirm_restore_action(u, c, l, s, 'local'),
        "action_restore_github_confirm": lambda u, c, l, s: confirm_restore_action(u, c, l, s, 'github'),
        "action_restore_local_execute": restore_local_db_action,
        "action_restore_github_execute": restore_github_db_action,
    }

    # Find the matching handler and extract the server_id
    for prefix, handler in action_map.items():
        if data.startswith(prefix + "_"):
            # Correctly extract server_id from the callback data
            try:
                server_id = data[len(prefix) + 1:]
                if server_id in SERVERS:
                    await handler(update, context, lang, server_id)
                    return
            except Exception as e:
                logger.error(f"Error handling action '{data}': {e}", exc_info=True)
                # Optionally, inform the user that something went wrong
                await query.edit_message_text(get_text("msg_error_generic", lang))
                return

    logger.warning(f"Unhandled generic action: {data}")

async def get_link_action(update, context, lang, server_id):
    server_name = SERVERS[server_id]['name']
    await update.callback_query.edit_message_text(get_text("msg_getting_url", lang, server_name=server_name))
    url = await get_latest_url_from_logs(SERVERS[server_id], update.callback_query, lang)
    text = get_text("msg_link_message", lang, server_name=server_name, url=url) if url else get_text("msg_failed_to_find_link", lang, server_name=server_name)
    await update.callback_query.edit_message_text(text, disable_web_page_preview=True)

async def get_bioauth_timer_action(update, context, lang, server_id):
    query = update.callback_query
    server_name = SERVERS[server_id]['name']
    
    await query.edit_message_text(get_text("msg_getting_url", lang, server_name=server_name))
    url = await get_latest_url_from_logs(SERVERS[server_id], query, lang)
    if not url:
        await query.edit_message_text(get_text("msg_failed_to_get_url", lang))
        return

    driver = create_selenium_driver()
    if not driver:
        await query.edit_message_text(get_text("msg_error_selenium_not_initialized", lang))
        return

    try:
        bioauth_seconds, epoch_minutes = await asyncio.to_thread(get_bioauth_and_epoch_times, driver, url)

        bioauth_text = get_text("msg_bioauth_time_left", lang, time=format_seconds_to_hhmmss(bioauth_seconds)) if bioauth_seconds != -1 else get_text("msg_failed_to_get_bioauth_time", lang)
        epoch_text = get_text("msg_epoch_time_left", lang, minutes=epoch_minutes) if epoch_minutes != -1 else get_text("msg_failed_to_get_epoch_time", lang)

        await query.edit_message_text(f"{bioauth_text}\n{epoch_text}")
    finally:
        if driver:
            driver.quit()

async def view_log_action(update, context, lang, server_id):
    server_name = SERVERS[server_id]['name']
    await update.callback_query.edit_message_text(get_text("msg_getting_log", lang, server_name=server_name))
    log_cmd = "sudo journalctl -u humanode-peer.service -n 20 --no-pager"
    returncode, stdout, stderr = await execute_command(SERVERS[server_id], log_cmd)
    text = get_text("msg_log_contents", lang, log=remove_emoji(stdout.strip())) if returncode == 0 and stdout.strip() else get_text("msg_failed_to_read_log", lang, error=stderr)
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def node_service_action(update, context, lang, server_id, action):
    server_name = SERVERS[server_id]['name']
    await update.callback_query.edit_message_text(get_text("msg_executing_command", lang, action=action, server_name=server_name))
    cmd = f"sudo systemctl {action} humanode-peer.service"
    returncode, stdout, stderr = await execute_command(SERVERS[server_id], cmd)
    if action == 'status':
        text = get_text("msg_status_info", lang, service="Node", status=stdout.strip()) if returncode == 0 else get_text("msg_command_failed", lang, error=stderr)
    else:
        text = get_text("msg_command_success", lang, action=action) if returncode == 0 else get_text("msg_command_failed", lang, error=stderr)
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def tunnel_service_action(update, context, lang, server_id, action):
    server_name = SERVERS[server_id]['name']
    await update.callback_query.edit_message_text(get_text("msg_executing_command", lang, action=action, server_name=server_name))
    cmd = f"sudo systemctl {action} humanode-websocket-tunnel.service"
    returncode, stdout, stderr = await execute_command(SERVERS[server_id], cmd)
    if action == 'status':
        text = get_text("msg_status_info", lang, service="Tunnel", status=stdout.strip()) if returncode == 0 else get_text("msg_command_failed", lang, error=stderr)
    else:
        text = get_text("msg_command_success", lang, action=action) if returncode == 0 else get_text("msg_command_failed", lang, error=stderr)
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def get_node_version_action(update, context, lang, server_id):
    server_name = SERVERS[server_id]['name']
    await update.callback_query.edit_message_text(get_text("msg_getting_node_version", lang, server_name=server_name))
    version_cmd = "/root/.humanode/workspaces/default/humanode-peer -V"
    returncode, stdout, stderr = await execute_command(SERVERS[server_id], version_cmd)
    text = get_text("msg_node_version", lang, version=stdout.strip()) if returncode == 0 and stdout.strip() else get_text("msg_failed_to_get_version", lang, error=stderr)
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def update_node_action(update, context, lang, server_id):
    server_config = SERVERS[server_id]
    query = update.callback_query

    await query.edit_message_text(get_text("msg_checking_latest_release", lang))
    
    latest_tag, download_url = await asyncio.to_thread(get_latest_release_version)
    if not download_url:
        await query.edit_message_text(get_text("msg_failed_to_find_release", lang))
        return

    await query.edit_message_text(get_text("msg_downloading_release", lang, tag=latest_tag or "latest"))
    
    archive_filename = download_url.split('/')[-1]
    temp_archive_path = f"/tmp/{archive_filename}"
    temp_extract_path = "/tmp/humanode-peer-extracted"

    wget_headers = f"--header=\"Authorization: token {GITHUB_TOKEN}\"" if GITHUB_TOKEN else ""
    wget_cmd = f"wget -q {wget_headers} -O {temp_archive_path} {download_url}"

    returncode, _, stderr = await execute_command(server_config, wget_cmd)
    if returncode != 0:
        await query.edit_message_text(get_text("msg_download_error", lang, error=stderr or "Unknown wget error"), parse_mode=ParseMode.HTML)
        return

    await query.edit_message_text(get_text("msg_unpacking_release", lang))
    unpack_cmd = f"rm -rf {temp_extract_path} && mkdir -p {temp_extract_path} && tar -xzvf {temp_archive_path} -C {temp_extract_path}"
    returncode, _, stderr = await execute_command(server_config, unpack_cmd)
    if returncode != 0:
        await query.edit_message_text(get_text("msg_unpack_error", lang, error=stderr), parse_mode=ParseMode.HTML)
        await execute_command(server_config, f"rm -f {temp_archive_path}")
        return

    find_cmd = f"find {temp_extract_path} -name 'humanode-peer' -type f"
    find_returncode, find_stdout, find_stderr = await execute_command(server_config, find_cmd)
    if find_returncode != 0 or not find_stdout.strip():
        await query.edit_message_text(get_text("msg_find_binary_error", lang, error=find_stderr or "Binary not found"), parse_mode=ParseMode.HTML)
        await execute_command(server_config, f"rm -f {temp_archive_path} && rm -rf {temp_extract_path}")
        return
    
    unpacked_binary_path = find_stdout.strip().split('\n')[0]

    await query.edit_message_text(get_text("msg_stopping_service", lang))
    await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
    
    await query.edit_message_text(get_text("msg_replacing_binary", lang))
    node_binary_path = "/root/.humanode/workspaces/default/humanode-peer"
    replace_cmd = f"sudo mv {unpacked_binary_path} {node_binary_path} && sudo chmod +x {node_binary_path}"
    returncode, _, stderr = await execute_command(server_config, replace_cmd)
    if returncode != 0:
        await query.edit_message_text(get_text("msg_replace_error", lang, error=stderr), parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text(get_text("msg_node_updated_success", lang, tag=latest_tag or "latest"))

    await query.edit_message_text(get_text("msg_starting_service", lang))
    await execute_command(server_config, "sudo systemctl start humanode-peer.service")

    await execute_command(server_config, f"rm -f {temp_archive_path} && rm -rf {temp_extract_path}")


def get_latest_release_version() -> tuple[str | None, str | None]:
    url = "https://api.github.com/repos/stalkerSumy/humanode-telegram-bot/releases/latest"
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
        data = response.json()
        latest_version = data.get("tag_name")
        
        download_url = next((asset.get("browser_download_url") for asset in data.get("assets", []) if "humanode-peer" in asset.get("name", "") and asset.get("name", "").endswith(".tar.gz")), None)
        
        return latest_version, download_url
    except Exception as e:
        logger.error(f"Error getting latest release from GitHub: {e}")
        return None, None

async def create_local_backup_action(update, context, lang, server_id):
    query = update.callback_query
    server_config = SERVERS[server_id]
    
    if not server_config.get("is_local"):
        await query.edit_message_text(get_text("msg_local_backup_not_for_remote", lang))
        return

    backup_path = await create_node_db_backup(context, lang, server_id, query)
    if backup_path:
        await query.edit_message_text(get_text("msg_local_backup_created", lang, path=backup_path), parse_mode=ParseMode.HTML)

async def create_node_db_backup(context, lang, server_id, query) -> str | None:
    server_config = SERVERS[server_id]
    
    await query.edit_message_text(get_text("msg_checking_epoch_time", lang, server_name=server_config['name']))
    url = await get_latest_url_from_logs(server_config, query, lang)
    if not url:
        await query.edit_message_text(get_text("msg_failed_to_get_url_for_epoch", lang))
        return None

    driver = create_selenium_driver()
    if not driver:
        await query.edit_message_text(get_text("msg_error_selenium_not_initialized", lang))
        return None

    epoch_minutes = -1
    try:
        _, epoch_minutes = await asyncio.to_thread(get_bioauth_and_epoch_times, driver, url)
    finally:
        if driver:
            driver.quit()

    if epoch_minutes == -1:
        await query.edit_message_text(get_text("msg_failed_to_get_epoch_time_backup", lang))
        return None
    if epoch_minutes < 30:
        await query.edit_message_text(get_text("msg_epoch_ending_soon_backup_cancelled", lang, minutes=epoch_minutes))
        return None

    backup_dir = os.path.join(BASE_DIR, "humanode_backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"humanode_db_backup_{server_config['name'].replace(' ', '_')}_{timestamp}.tar"
    backup_path = os.path.join(backup_dir, backup_filename)
    db_path = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db/full/"

    await query.edit_message_text(get_text("msg_stopping_node_for_backup", lang, server_name=server_config['name']))
    returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
    if returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_stop_node", lang, error=stderr), parse_mode=ParseMode.HTML)
        return None

    await query.edit_message_text(get_text("msg_creating_db_archive", lang))
    tar_command = f"tar -cf {shlex.quote(backup_path)} -C {os.path.dirname(db_path)} {os.path.basename(db_path)}"
    returncode, _, stderr = await execute_command(server_config, tar_command)
    
    await query.edit_message_text(get_text("msg_starting_node_after_backup", lang, server_name=server_config['name']))
    start_returncode, _, start_stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
    if start_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_start_node_after_backup", lang, error=start_stderr), parse_mode=ParseMode.HTML)

    if returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_create_archive", lang, error=stderr), parse_mode=ParseMode.HTML)
        return None

    logger.info(f"Successfully created DB backup: {backup_path}")
    return backup_path

async def confirm_restore_action(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, server_id: str, restore_type: str):
    query = update.callback_query
    text = get_text(f"msg_confirm_restore_{restore_type}", lang)
    keyboard = [
        [InlineKeyboardButton(get_text("btn_confirm_restore", lang), callback_data=f"action_restore_{restore_type}_execute_{server_id}")],
        [InlineKeyboardButton(get_text("btn_cancel", lang), callback_data=f"action_restore_menu_{server_id}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def restore_local_db_action(update, context, lang, server_id):
    query = update.callback_query
    server_config = SERVERS[server_id]
    
    if not server_config.get("is_local"):
        await query.edit_message_text(get_text("msg_local_restore_not_for_remote", lang))
        return

    await query.edit_message_text(get_text("msg_finding_latest_local_backup", lang), parse_mode=ParseMode.HTML)
    
    backup_dir = os.path.join(BASE_DIR, "humanode_backups")
    list_of_files = glob.glob(f'{backup_dir}/*.tar')
    if not list_of_files:
        await query.edit_message_text(get_text("msg_no_local_backups_found", lang, path=backup_dir), parse_mode=ParseMode.HTML)
        return
    
    latest_file = max(list_of_files, key=os.path.getctime)
    await query.edit_message_text(get_text("msg_found_backup_stopping_node", lang, file=os.path.basename(latest_file)), parse_mode=ParseMode.HTML)

    returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
    if returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_stop_node", lang, error=stderr), parse_mode=ParseMode.HTML)
        return

    db_path = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db/full"
    await query.edit_message_text(get_text("msg_deleting_old_db", lang), parse_mode=ParseMode.HTML)
    rm_returncode, _, rm_stderr = await execute_command(server_config, f"rm -rf {db_path}")
    if rm_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_delete_db", lang, error=rm_stderr), parse_mode=ParseMode.HTML)
        await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        return

    await query.edit_message_text(get_text("msg_unpacking_backup", lang), parse_mode=ParseMode.HTML)
    restore_cmd = f"tar -xf {latest_file} -C /"
    restore_returncode, _, restore_stderr = await execute_command(server_config, restore_cmd)
    if restore_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_unpack_backup", lang, error=restore_stderr), parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text(get_text("msg_restore_successful", lang), parse_mode=ParseMode.HTML)

    await query.edit_message_text(get_text("msg_starting_node_after_restore", lang), parse_mode=ParseMode.HTML)
    start_returncode, _, start_stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
    if start_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_start_node_after_restore", lang, error=start_stderr), parse_mode=ParseMode.HTML)

def get_latest_snapshot_from_github() -> list[dict] | None:
    """
    Fetches snapshot asset information from GitHub.
    Handles both single .tar.gz files and multi-part archives (.part-aa, .part-ab, etc.).
    """
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        
        response = requests.get(GITHUB_SNAPSHOT_URL, timeout=15, headers=headers)
        response.raise_for_status()
        data = response.json()
        assets = data.get("assets", [])

        snapshot_parts = [asset for asset in assets if ".part-" in asset.get("name", "")]
        
        if snapshot_parts:
            snapshot_parts.sort(key=lambda x: x['name'])
            logger.info(f"Found {len(snapshot_parts)} snapshot parts.")
            return snapshot_parts
            
        single_file = next((asset for asset in assets if asset.get("name", "").endswith(".tar.gz")), None)
        if single_file:
            logger.info("Found a single .tar.gz snapshot file.")
            return [single_file]

    except Exception as e:
        logger.error(f"Error getting snapshot from GitHub: {e}", exc_info=True)
    
    return None

async def restore_github_db_action(update, context, lang, server_id):
    query = update.callback_query
    server_config = SERVERS[server_id]

    await query.edit_message_text(get_text("msg_fetching_github_snapshot_url", lang), parse_mode=ParseMode.HTML)
    
    snapshot_assets = await asyncio.to_thread(get_latest_snapshot_from_github)

    if not snapshot_assets:
        await query.edit_message_text(get_text("msg_failed_to_fetch_github_snapshot_url", lang), parse_mode=ParseMode.HTML)
        return

    downloaded_files = []
    temp_dir = "/tmp"
    
    for asset in snapshot_assets:
        asset_name = asset['name']
        asset_url = asset['browser_download_url']
        asset_path = os.path.join(temp_dir, asset_name)
        downloaded_files.append(asset_path)
        
        await query.edit_message_text(get_text("msg_downloading_snapshot", lang, filename=asset_name), parse_mode=ParseMode.HTML)
        
        wget_cmd = f"wget -q -O {shlex.quote(asset_path)} {shlex.quote(asset_url)}"
        wget_returncode, _, wget_stderr = await execute_command(server_config, wget_cmd)
        
        if wget_returncode != 0:
            await query.edit_message_text(get_text("msg_failed_to_download_snapshot", lang, error=wget_stderr), parse_mode=ParseMode.HTML)
            if downloaded_files:
                await execute_command(server_config, f"rm -f {' '.join(map(shlex.quote, downloaded_files))}")
            return

    is_multi_part = len(downloaded_files) > 1 and ".part-" in downloaded_files[0]
    
    if is_multi_part:
        first_part_name = os.path.basename(downloaded_files[0])
        combined_filename = re.sub(r'\\.part-aa$', '', first_part_name, flags=re.IGNORECASE)
        final_archive_path = os.path.join(temp_dir, combined_filename)
        
        await query.edit_message_text(get_text("msg_combining_snapshot_parts", lang, filename=combined_filename), parse_mode=ParseMode.HTML)
        
        downloaded_files.sort() 
        cat_cmd = f"cat {' '.join(map(shlex.quote, downloaded_files))} > {shlex.quote(final_archive_path)}"
        combine_returncode, _, combine_stderr = await execute_command(server_config, cat_cmd)

        if combine_returncode != 0:
            await query.edit_message_text(get_text("msg_failed_to_combine_snapshot", lang, error=combine_stderr), parse_mode=ParseMode.HTML)
            await execute_command(server_config, f"rm -f {' '.join(map(shlex.quote, downloaded_files))}")
            return
    else:
        final_archive_path = downloaded_files[0]

    await query.edit_message_text(get_text("msg_stopping_node_for_restore", lang), parse_mode=ParseMode.HTML)
    stop_returncode, _, stop_stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
    if stop_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_stop_node", lang, error=stop_stderr), parse_mode=ParseMode.HTML)
        await execute_command(server_config, f"rm -f {shlex.quote(final_archive_path)} {' '.join(map(shlex.quote, downloaded_files))}")
        return

    db_path = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db/full"
    await query.edit_message_text(get_text("msg_deleting_old_db", lang), parse_mode=ParseMode.HTML)
    rm_returncode, _, rm_stderr = await execute_command(server_config, f"rm -rf {db_path}")
    if rm_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_delete_db", lang, error=rm_stderr), parse_mode=ParseMode.HTML)
        await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        await execute_command(server_config, f"rm -f {shlex.quote(final_archive_path)} {' '.join(map(shlex.quote, downloaded_files))}")
        return

    await query.edit_message_text(get_text("msg_unpacking_snapshot", lang), parse_mode=ParseMode.HTML)
    restore_cmd = f"tar -xzvf {shlex.quote(final_archive_path)} -C /"
    restore_returncode, _, restore_stderr = await execute_command(server_config, restore_cmd)
    if restore_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_unpack_snapshot", lang, error=restore_stderr), parse_mode=ParseMode.HTML)
    else:
        await query.edit_message_text(get_text("msg_restore_successful", lang), parse_mode=ParseMode.HTML)

    await query.edit_message_text(get_text("msg_starting_node_after_restore", lang), parse_mode=ParseMode.HTML)
    start_returncode, _, start_stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
    if start_returncode != 0:
        await query.edit_message_text(get_text("msg_failed_to_start_node_after_restore", lang, error=start_stderr), parse_mode=ParseMode.HTML)

    cleanup_files = downloaded_files + ([final_archive_path] if is_multi_part else [])
    await execute_command(server_config, f"rm -f {' '.join(map(shlex.quote, cleanup_files))}")


async def get_element_screenshot_action(update, context, lang, server_id):
    query = update.callback_query
    server_name = SERVERS[server_id]['name']
    
    await query.edit_message_text(get_text("msg_getting_url", lang, server_name=server_name))
    url = await get_latest_url_from_logs(SERVERS[server_id], query, lang)
    if not url:
        await query.edit_message_text(get_text("msg_failed_to_get_url", lang))
        return

    await query.edit_message_text(get_text("msg_taking_element_screenshot", lang, server_name=server_name))
    
    driver = create_selenium_driver()
    if not driver:
        await query.edit_message_text(get_text("msg_error_selenium_not_initialized", lang))
        return

    screenshot_path = None
    try:
        screenshot_path = await asyncio.to_thread(
            take_element_screenshot, driver, url, "//div[contains(@class, 'css-ak0d3g')]"
        )
    finally:
        if driver:
            driver.quit()
    
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            await query.message.reply_photo(photo=open(screenshot_path, 'rb'), caption=f"Screenshot from {server_name}")
            await query.edit_message_text(get_text("msg_screenshot_sent", lang))
        except Exception as e:
            logger.error(f"Failed to send screenshot: {e}")
            await query.edit_message_text(get_text("msg_failed_to_send_screenshot", lang))
        finally:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
    else:
        await query.edit_message_text(get_text("msg_failed_to_take_screenshot", lang))

def take_element_screenshot(driver: webdriver.Chrome, url: str, xpath: str) -> str | None:
    screenshot_path = os.path.join(BASE_DIR, "element_screenshot.png")
    try:
        wait = WebDriverWait(driver, 90) # Increased wait time to 90s
        driver.get(url)
        
        # Wait for dashboard to be clickable and click it
        dashboard_button_xpath = "//div[@role='button' and contains(., 'Dashboard')]"
        wait.until(EC.element_to_be_clickable((By.XPATH, dashboard_button_xpath))).click()
        
        # Wait for the target element to be visible instead of a fixed sleep
        element_to_capture = wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))
        
        # A small extra delay can sometimes help ensure everything is rendered
        time.sleep(10) 
        
        element_to_capture.screenshot(screenshot_path)
        logger.info(f"Successfully captured element screenshot to {screenshot_path}")
        return screenshot_path
    except Exception as e:
        logger.error(f"Failed to take element screenshot: {e}", exc_info=True)
        try:
            driver.save_screenshot(os.path.join(BASE_DIR, "selenium_error_screenshot_element.png"))
        except Exception as dump_e:
            logger.error(f"Failed to save error screenshot: {dump_e}")
        return None

# --- Add Server Conversation ---
(
    GET_ID,
    GET_NAME,
    GET_IP,
    GET_USER,
    GET_KEY_PATH,
) = range(5)

@translated_action
async def add_server_start(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        get_text("msg_add_server_start", lang),
        parse_mode=ParseMode.HTML
    )
    context.user_data['new_server'] = {}
    return GET_ID

@translated_action
async def get_server_id(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    server_id = update.message.text.strip()
    if ' ' in server_id or not server_id.isascii():
        await update.message.reply_text(get_text("msg_error_server_id_invalid", lang))
        return GET_ID
    
    if server_id in SERVERS:
        await update.message.reply_text(get_text("msg_error_server_id_exists", lang))
        return GET_ID
    
    context.user_data['new_server']['id'] = server_id
    await update.message.reply_text(get_text("msg_add_server_name", lang), parse_mode=ParseMode.HTML)
    return GET_NAME

@translated_action
async def get_server_name(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    context.user_data['new_server']['name'] = update.message.text.strip()
    await update.message.reply_text(get_text("msg_add_server_ip", lang), parse_mode=ParseMode.HTML)
    return GET_IP

@translated_action
async def get_server_ip(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    context.user_data['new_server']['ip'] = update.message.text.strip()
    await update.message.reply_text(get_text("msg_add_server_user", lang), parse_mode=ParseMode.HTML)
    return GET_USER

@translated_action
async def get_server_user(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    context.user_data['new_server']['user'] = update.message.text.strip()
    await update.message.reply_text(get_text("msg_add_server_key", lang), parse_mode=ParseMode.HTML)
    return GET_KEY_PATH

@translated_action
async def get_server_key_path(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    key_path = update.message.text.strip()
    
    new_server_data = context.user_data['new_server']
    server_id = new_server_data['id']
    
    is_local = not key_path or key_path == '-'
    
    servers = load_servers()
    servers[server_id] = {
        "name": new_server_data['name'],
        "ip": new_server_data['ip'],
        "user": new_server_data['user'],
        "key_path": "" if is_local else key_path,
        "is_local": is_local,
    }
    
    if save_servers(servers):
        await update.message.reply_text(get_text("msg_server_added_success", lang, server_name=new_server_data['name']), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(get_text("msg_server_save_failed", lang))

    context.user_data.clear()
    await menu(update, context)
    return ConversationHandler.END

@translated_action
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    context.user_data.clear()
    await update.message.reply_text(get_text("msg_add_server_cancelled", lang))
    await menu(update, context)
    return ConversationHandler.END

def main():
    if not TOKEN or not AUTHORIZED_USER_ID:
        logger.critical("CRITICAL: Bot TOKEN or AUTHORIZED_USER_ID is not configured in config.json. Exiting.")
        return

    logger.info(f"Starting bot version: {BOT_VERSION}")
    load_translations()

    async def post_init(application: Application):
        await application.bot.set_my_commands([
            BotCommand("/start", "Start the bot"),
            BotCommand("/menu", "Show the main menu"),
        ])
        application.job_queue.run_repeating(periodic_bioauth_check, interval=timedelta(minutes=JOB_QUEUE_INTERVAL_MINUTES), first=10)

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    settings_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_setting_prompt, pattern=r"^edit_setting_")],
        states={EDIT_SETTING_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_setting_value)]},
        fallbacks=[CallbackQueryHandler(menu, pattern="^main_menu$")],
        per_message=False, conversation_timeout=300,
    )

    add_server_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_server_start, pattern="^add_server_start$")],
        states={
            GET_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_server_id)],
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_server_name)],
            GET_IP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_server_ip)],
            GET_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_server_user)],
            GET_KEY_PATH: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_server_key_path)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        per_message=False,
        conversation_timeout=300,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CallbackQueryHandler(menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(language_menu, pattern=r"^language_menu$"))
    application.add_handler(CallbackQueryHandler(set_language, pattern=r"^set_lang_"))
    application.add_handler(CallbackQueryHandler(select_server, pattern=r"^select_server_"))
    application.add_handler(CallbackQueryHandler(notification_settings_menu, pattern="^notification_settings$"))
    application.add_handler(settings_conv_handler)
    application.add_handler(add_server_conv_handler)
    application.add_handler(CallbackQueryHandler(handle_generic_action))

    logger.info("Bot handlers added. Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Bot crashed with an unhandled exception: {e}", exc_info=True)