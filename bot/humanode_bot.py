import json
import logging
import subprocess
import re
import asyncio
import socket
from datetime import datetime, timedelta
import os
import time
from telegram.error import BadRequest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue

# --- Global Configuration and Localization ---
CONFIG = {}
LANG = {}

class I18n:
    def __init__(self, lang_code='en'):
        self.lang_code = lang_code
        self.load_language()

    def load_language(self):
        global LANG
        try:
            # Assuming locales directory is relative to the bot script
            locales_path = os.path.join(os.path.dirname(__file__), 'locales', f'{self.lang_code}.json')
            with open(locales_path, 'r', encoding='utf-8') as f:
                LANG = json.load(f)
            logger.info(f"Language '{self.lang_code}' loaded successfully.")
        except FileNotFoundError:
            logger.error(f"Language file for '{self.lang_code}' not found. Falling back to 'en'.")
            if self.lang_code != 'en':
                self.lang_code = 'en'
                self.load_language()
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding language file '{self.lang_code}.json': {e}")
            if self.lang_code != 'en':
                self.lang_code = 'en'
                self.load_language()

    def get(self, key, **kwargs):
        return LANG.get(key, key).format(**kwargs)

i18n = I18n() # Will be initialized properly in main()

# --- Logging Setup ---
logging.basicConfig(
    filename='humanode_bot.log',
    filemode='a',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO # Changed to INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Utility Functions ---
def remove_emoji(text: str) -> str:
    """Видаляє emoji з тексту."""
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"
        "\u3030"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(r"", text)

def format_seconds_to_hhmmss(seconds: int) -> str:
    """Форматує секунди у формат HH:MM:SS."""
    if seconds < 0:
        return "N/A"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"

async def execute_command_with_progress(server_config: dict, command: str, query, initial_message: str):
    """
    Виконує команду локально або через SSH і оновлює повідомлення в Telegram з прогресом.
    """
    last_update_time = 0
    progress_message = await query.edit_message_text(initial_message)
    last_sent_text = initial_message

    if server_config["is_local"]:
        logger.info(f"Executing local command with streaming: {command}")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    else:
        ssh_command = f"ssh -i {server_config['key_path']} {server_config['user']}@{server_config['ip']} '{command}'"
        logger.info(f"Executing SSH command with streaming: {ssh_command}")
        process = await asyncio.create_subprocess_shell(
            ssh_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    full_output = ""
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded_line = line.decode('utf-8', errors='ignore').strip()
        full_output += decoded_line + "\n"
        
        # Шукаємо прогрес-бар
        if "TRANSFERRING" in decoded_line or "TRANSFERRED" in decoded_line:
            current_time = time.time()
            # Оновлюємо не частіше, ніж раз на 3 секунди
            if current_time - last_update_time > 3:
                # Використовуємо <pre> для моноширинного тексту
                new_text = f"{initial_message}\n\n<pre>{decoded_line}</pre>"
                if new_text != last_sent_text:
                    try:
                        await progress_message.edit_text(new_text, parse_mode="HTML")
                        last_sent_text = new_text
                        last_update_time = current_time
                    except BadRequest as e:
                        if "Message is not modified" not in str(e):
                            logger.error(f"Error updating progress message: {e}")

    await process.wait()
    returncode = process.returncode
    stderr_output = (await process.stderr.read()).decode('utf-8', errors='ignore').strip()

    if returncode != 0:
        logger.error(f"Command execution error '{command}'. Stderr: {stderr_output}")
    
    return returncode, full_output, stderr_output

async def execute_command(server_config: dict, command: str) -> tuple[int, str, str]:
    """Виконує команду локально або через SSH."""
    if server_config["is_local"]:
        logger.info(f"Executing local command on {server_config['name']}: {command}")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    else:
        ssh_command = f"ssh -i {server_config['key_path']} {server_config['user']}@{server_config['ip']} '{command}'"
        logger.info(f"Executing SSH command on {server_config['name']}: {ssh_command}")
        process = await asyncio.create_subprocess_shell(
            ssh_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()

async def check_and_restart_tunnel_service(server_config: dict, query) -> bool:
    """
    Перевіряє статус служби humanode-websocket-tunnel.service і перезапускає її, якщо вона неактивна.
    Повертає True, якщо служба активна (або стала активною), False в іншому випадку.
    """
    server_name = server_config["name"]
    service_name = "humanode-websocket-tunnel.service"

    await query.edit_message_text(f"🔄 {i18n.get('checking_tunnel_status', service_name=service_name, server_name=server_name)}")

    # Перевірка поточного статусу
    returncode, stdout, stderr = await execute_command(server_config, f"sudo systemctl status {service_name}")
    if returncode == 0 and "Active: active (running)" in stdout:
        await query.edit_message_text(f"✅ {i18n.get('tunnel_already_active', service_name=service_name, server_name=server_name)}")
        return True
    else:
        logger.warning(f"Service {service_name} on {server_name} is inactive or has errors. Stderr: {stderr}")
        await query.edit_message_text(f"⚠️ {i18n.get('tunnel_inactive_restarting', service_name=service_name, server_name=server_name)}")
        
        # Спроба перезапуску
        restart_returncode, restart_stdout, restart_stderr = await execute_command(server_config, f"sudo systemctl restart {service_name}")
        if restart_returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('tunnel_restart_failed', service_name=service_name, server_name=server_name, stderr=restart_stderr)}", parse_mode="HTML")
            logger.error(f"Помилка перезапуску {service_name}: {restart_stderr}")
            return False
        
        await query.edit_message_text(f"⏳ {i18n.get('tunnel_restarting_wait', service_name=service_name, server_name=server_name)}")
        await asyncio.sleep(10) # Даємо час на запуск

        # Повторна перевірка статусу після перезапуску
        returncode_after_restart, stdout_after_restart, stderr_after_restart = await execute_command(server_config, f"sudo systemctl status {service_name}")
        if returncode_after_restart == 0 and "Active: active (running)" in stdout_after_restart:
            await query.edit_message_text(f"✅ {i18n.get('tunnel_restart_success', service_name=service_name, server_name=server_name)}")
            return True
        else:
            await query.edit_message_text(f"❌ {i18n.get('tunnel_not_active_after_restart', service_name=service_name, server_name=server_name, stderr=stderr_after_restart)}", parse_mode="HTML")
            logger.error(f"Service {service_name} not active after restart. Stderr: {stderr_after_restart}")
            return False

def get_latest_url_from_logs(server_config: dict):
    """
    Отримує найновіший URL Humanode для вказаного сервера.
    """
    base_url = "https://webapp.mainnet.stages.humanode.io/open?url="
    
    # Спочатку перевіряємо логи тунелю
    try:
        tunnel_log_cmd = "journalctl -u humanode-websocket-tunnel.service --no-pager | grep 'obtained tunnel URL' | tail -n 1"
        if not server_config["is_local"]:
            tunnel_log_cmd = f"ssh -i {server_config['key_path']} {server_config['user']}@{server_config['ip']} \"{tunnel_log_cmd}\""
        
        result = subprocess.run(tunnel_log_cmd, shell=True, capture_output=True, text=True, check=False, timeout=15)
        if result.returncode == 0 and result.stdout:
            match = re.search(r"url=(wss://[^\s]+)", result.stdout.strip())
            if match:
                wss_url = match.group(1)
                logger.info(f"Found URL in tunnel logs for {server_config['name']}: {wss_url}")
                return f"{base_url}{wss_url}"
    except Exception as e:
        logger.error(f"Error getting URL from tunnel logs for {server_config['name']}: {e}")

    # Якщо в логах тунелю немає, перевіряємо логи ноди
    try:
        node_log_cmd = "journalctl -u humanode-peer.service --no-pager | grep 'Please visit' | tail -n 1"
        if not server_config["is_local"]:
            node_log_cmd = f"ssh -i {server_config['key_path']} {server_config['user']}@{server_config['ip']} \"{node_log_cmd}\""

        result = subprocess.run(node_log_cmd, shell=True, capture_output=True, text=True, check=False, timeout=15)
        if result.returncode == 0 and result.stdout:
            match = re.search(r"(https://webapp\\.mainnet\\.stages\\.humanode\\.io/open\\?url=[^\\s]+)", result.stdout.strip())
            if match:
                full_url = match.group(1)
                if "localhost" not in full_url:
                    logger.info(f"Found URL in node logs for {server_config['name']}: {full_url}")
                    return full_url
    except Exception as e:
        logger.error(f"Error getting URL from node logs for {server_config['name']}: {e}")

    logger.warning(f"Failed to find any working URL for {server_config['name']}.")
    return None

async def check_mega_cmd_installed(server_config: dict) -> bool:
    """Перевіряє, чи встановлено mega-cmd на сервері."""
    cmd = "which mega-cmd"
    returncode, _, _ = await execute_command(server_config, cmd)
    return returncode == 0

def get_bioauth_countdown_seconds(url: str) -> tuple[int, str | None]:
    """Використовує Selenium для отримання часу до біоаутентифікації."""
    if "ws%3A%2F%2Flocalhost%3A9944" in url:
        logger.error(f"Cannot process URL with localhost: {url}")
        return -1, None

    seconds = -1
    screenshot_path = None
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 90) # Збільшено час очікування
        logger.info(f"Navigating to {url}")
        driver.get(url)
        
        dashboard_selector = "//span[contains(translate(normalize-space(.), 'dashboard', 'DASHBOARD'), 'DASHBOARD')]"
        dashboard_element = wait.until(
            EC.element_to_be_clickable((By.XPATH, dashboard_selector))
        )
        
        logger.info("Attempting to click on DASHBOARD element.")
        try:
            dashboard_element.click()
        except Exception as e:
            logger.warning(f"Standard click failed: {e}. Trying JavaScript click.")
            driver.execute_script("arguments[0].click();", dashboard_element)
        logger.info("Successfully clicked on DASHBOARD element.")

        bioauth_label_xpath = "//p[text()='Bioauth']"
        wait.until(EC.visibility_of_element_located((By.XPATH, bioauth_label_xpath)))
        logger.info("Found 'Bioauth' label.")

        timer_element_xpath = f"{bioauth_label_xpath}/following-sibling::h6[contains(text(), ':')]"
        timer_element = wait.until(
            EC.visibility_of_element_located((By.XPATH, timer_element_xpath))
        )
        
        wait.until(EC.text_to_be_present_in_element((By.XPATH, timer_element_xpath), ":"))
        
        screenshot_path = f"/tmp/bioauth_timer_{int(time.time())}.png"
        timer_element.screenshot(screenshot_path)
        logger.info(f"Timer screenshot saved to {screenshot_path}")

        time_str = timer_element.text
        logger.info(f"Found timer text: '{time_str}'")
        
        parts = time_str.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            secs = int(parts[2])
            seconds = timedelta(hours=hours, minutes=minutes, seconds=secs).total_seconds()
            logger.info(f"Parsed time into {seconds} seconds.")
        else:
            logger.error(f"Unexpected time format: {time_str}")
            seconds = -1
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
            screenshot_path = None

    except Exception as e:
        logger.error(f"An unexpected error occurred during scraping: {e}")
        if driver:
            error_screenshot_path = f"/root/bioauth_error_screenshot_{int(time.time())}.png"
            try:
                driver.save_screenshot(error_screenshot_path)
                logger.error(f"Saved error screenshot to {error_screenshot_path}")
                logger.error(f"Page source at the time of error:\n{driver.page_source}")
            except Exception as screenshot_e:
                logger.error(f"Could not save screenshot or get page source: {screenshot_e}")

        if screenshot_path and os.path.exists(screenshot_path):
            os.remove(screenshot_path)
        screenshot_path = None
        seconds = -1
    finally:
        if driver:
            driver.quit()
            
    return seconds, screenshot_path

async def perform_backup_and_upload(server_config: dict, query) -> None:
    """
    Створює бекап бази даних, завантажує його на Mega.nz з прогрес-баром
    і видаляє старі бекапи.
    """
    server_name = server_config["name"]
    db_source_dir = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db"
    local_backup_dir = "/root/humanode_backups"
    mega_backup_dir = "/Root/humanode_backups/"
    retention_days = 7
    
    await query.edit_message_text(f"🔄 {i18n.get('backup_start', server_name=server_name)}")

    # Перевірка наявності mega-cmd
    if not await check_mega_cmd_installed(server_config):
        await query.edit_message_text(f"❌ {i18n.get('mega_cmd_not_installed', server_name=server_name)}", parse_mode="HTML")
        return

    try:
        # 1. Зупинити ноду
        await query.edit_message_text(f"🛑 {i18n.get('stopping_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('stop_service_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 2. Створення архіву
        await query.edit_message_text(f"🗜️ {i18n.get('creating_archive', server_name=server_name)}")
        archive_name = f"humanode_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        local_archive_path = os.path.join(local_backup_dir, archive_name)
        
        # Переконуємося, що директорія існує
        await execute_command(server_config, f"mkdir -p {local_backup_dir}")

        tar_cmd = f"tar -czf {local_archive_path} -C {db_source_dir} ."
        returncode, _, stderr = await execute_command(server_config, tar_cmd)
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('create_archive_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 3. Завантаження на Mega.nz з прогресом
        upload_cmd = f"mega-cmd put {local_archive_path} {mega_backup_dir}"
        returncode, _, stderr = await execute_command_with_progress(
            server_config,
            upload_cmd,
            query,
            f"☁️ {i18n.get('uploading_archive', archive_name=archive_name)}"
        )
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('upload_mega_error', stderr=stderr)}", parse_mode="HTML")
            return
        
        await query.edit_message_text(f"✅ {i18n.get('archive_uploaded_success', archive_name=archive_name)}")

        # 4. Видалення локального архіву
        await execute_command(server_config, f"rm {local_archive_path}")

        # 5. Очищення старих бекапів на Mega.nz
        await query.edit_message_text(i18n.get('cleaning_old_backups'))
        # Отримати список файлів, потім видалити старі
        list_cmd = f"mega-cmd ls {mega_backup_dir}"
        _, stdout, _ = await execute_command(server_config, list_cmd)
        
        for line in stdout.splitlines():
            match = re.search(r"humanode_db_(\d{8})_(\d{6})\\.tar\\.gz", line)
            if match:
                date_str = match.group(1)
                backup_date = datetime.strptime(date_str, "%Y%m%d")
                if (datetime.now() - backup_date).days > retention_days:
                    file_to_delete = match.group(0)
                    delete_cmd = f"mega-cmd rm {mega_backup_dir}{file_to_delete}"
                    await execute_command(server_config, delete_cmd)
                    logger.info(f"Deleted old backup: {file_to_delete}")

    except Exception as e:
        logger.error(f"Unexpected error during backup: {e}")
        await query.edit_message_text(f"❌ {i18n.get('unexpected_error', error=e)}")
    finally:
        # 6. Запустити ноду (завжди)
        await query.edit_message_text(f"▶️ {i18n.get('starting_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('backup_complete_node_started', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_start_after_backup_error', stderr=stderr)}", parse_mode="HTML")

async def restore_mega_backup(server_config: dict, query, mega_file_name: str) -> None:
    """Відновлює базу даних з Mega.nz з прогрес-баром."""
    server_name = server_config["name"]
    db_full_path = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db/full"
    db_parent_dir = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db"
    mega_backup_path = f"/Root/humanode_backups/{mega_file_name}"
    local_download_path = f"/tmp/{mega_file_name}"

    await query.edit_message_text(f"🔄 {i18n.get('restore_start', server_name=server_name)}")

    try:
        # 1. Зупинити ноду
        await query.edit_message_text(f"🛑 {i18n.get('stopping_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('stop_service_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 2. Завантаження з Mega.nz з прогресом
        download_cmd = f"mega-cmd get {mega_backup_path} {local_download_path}"
        returncode, _, stderr = await execute_command_with_progress(
            server_config,
            download_cmd,
            query,
            f"☁️ {i18n.get('downloading_archive', mega_file_name=mega_file_name)}"
        )
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('download_mega_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 3. Видалення старої папки БД та розпакування
        await query.edit_message_text(i18n.get('deleting_old_db_extracting'))
        await execute_command(server_config, f"rm -rf {db_full_path}")
        
        extract_cmd = f"tar -xzvf {local_download_path} -C {db_parent_dir}"
        returncode, _, stderr = await execute_command(server_config, extract_cmd)
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('extract_archive_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 4. Очищення
        await execute_command(server_config, f"rm {local_download_path}")

    except Exception as e:
        logger.error(f"Unexpected error during restore: {e}")
        await query.edit_message_text(f"❌ {i18n.get('unexpected_error', error=e)}")
    finally:
        # 5. Запустити ноду
        await query.edit_message_text(f"▶️ {i18n.get('starting_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('restore_complete_node_started', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_start_after_restore_error', stderr=stderr)}", parse_mode="HTML")

# --- Telegram Bot Commands and Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != CONFIG.get("authorized_user_id"):
        await update.message.reply_text(i18n.get("unauthorized_access"))
        return
    await update.message.reply_text(i18n.get("welcome_message"))

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != CONFIG.get("authorized_user_id"):
        await update.message.reply_text(i18n.get("unauthorized_access"))
        return

    keyboard = [[InlineKeyboardButton(server_config["name"], callback_data=f"select_server_{server_id}")]
                for server_id, server_config in CONFIG["servers"].items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(i18n.get("select_server_prompt"), reply_markup=reply_markup)

async def select_server(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    server_id = query.data.replace("select_server_", "")
    context.user_data["selected_server_id"] = server_id
    server_config = CONFIG["servers"].get(server_id)

    if not server_config:
        await query.edit_message_text(i18n.get("server_not_found"))
        return

    server_name = server_config["name"]
    keyboard = [
        [InlineKeyboardButton(i18n.get("get_link_button"), callback_data=f"action_get_link_{server_id}")],
        [InlineKeyboardButton(i18n.get("get_bioauth_timer_button"), callback_data=f"action_get_bioauth_timer_{server_id}")],
        [InlineKeyboardButton(i18n.get("node_management_button"), callback_data=f"action_node_management_{server_id}")],
        [InlineKeyboardButton(i18n.get("backup_restore_button"), callback_data=f"action_restore_db_menu_{server_id}")],
        [InlineKeyboardButton(i18n.get("view_log_button"), callback_data=f"action_view_log_{server_id}")],
        [InlineKeyboardButton(i18n.get("back_to_servers_button"), callback_data="menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(i18n.get("selected_server_menu", server_name=server_name), reply_markup=reply_markup)

async def node_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, server_id: str) -> None:
    query = update.callback_query
    server_config = CONFIG["servers"].get(server_id)
    server_name = server_config["name"]

    keyboard = [
        [InlineKeyboardButton(i18n.get("start_node_button"), callback_data=f"action_start_node_{server_id}")],
        [InlineKeyboardButton(i18n.get("stop_node_button"), callback_data=f"action_stop_node_{server_id}")],
        [InlineKeyboardButton(i18n.get("restart_node_button"), callback_data=f"action_restart_node_{server_id}")],
        [InlineKeyboardButton(i18n.get("status_node_button"), callback_data=f"action_status_node_{server_id}")],
        [InlineKeyboardButton(i18n.get("get_node_version_button"), callback_data=f"action_get_node_version_{server_id}")],
        [InlineKeyboardButton(i18n.get("update_node_button"), callback_data=f"action_update_node_{server_id}")],
        [InlineKeyboardButton(i18n.get("back_to_server_menu_button"), callback_data=f"select_server_{server_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(i18n.get("node_management_menu_prompt", server_name=server_name), reply_markup=reply_markup)

async def restore_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, server_id: str) -> None:
    query = update.callback_query
    server_config = CONFIG["servers"].get(server_id)
    server_name = server_config["name"]

    keyboard = [
        [InlineKeyboardButton(i18n.get("create_backup_button"), callback_data=f"action_create_backup_{server_id}")],
        [InlineKeyboardButton(i18n.get("restore_local_backup_button"), callback_data=f"action_restore_local_{server_id}")],
        [InlineKeyboardButton(i18n.get("restore_mega_backup_button"), callback_data=f"action_restore_mega_{server_id}")],
        [InlineKeyboardButton(i18n.get("back_to_server_menu_button"), callback_data=f"select_server_{server_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(i18n.get("backup_restore_menu_prompt", server_name=server_name), reply_markup=reply_markup)

async def list_mega_backups(update: Update, context: ContextTypes.DEFAULT_TYPE, server_id: str) -> None:
    query = update.callback_query
    server_config = CONFIG["servers"].get(server_id)
    server_name = server_config["name"]
    mega_backup_dir = "/Root/humanode_backups/"

    await query.edit_message_text(f"☁️ {i18n.get('listing_mega_backups', server_name=server_name)}")
    list_cmd = f"mega-cmd ls {mega_backup_dir}"
    returncode, stdout, stderr = await execute_command(server_config, list_cmd)

    if returncode == 0 and stdout.strip():
        backup_files = []
        for line in stdout.splitlines():
            match = re.search(r"humanode_db_(\d{8})_(\d{6})\\.tar\\.gz", line)
            if match:
                backup_files.append(match.group(0))
        
        if backup_files:
            keyboard = [[InlineKeyboardButton(file, callback_data=f"action_restore_mega_select_{server_id}_{file}")] for file in backup_files]
            keyboard.append([InlineKeyboardButton(i18n.get("back_to_backup_menu_button"), callback_data=f"action_restore_db_menu_{server_id}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(i18n.get("select_backup_to_restore"), reply_markup=reply_markup)
        else:
            await query.edit_message_text(f"❌ {i18n.get('no_mega_backups_found', server_name=server_name)}")
    else:
        await query.edit_message_text(f"❌ {i18n.get('failed_to_list_mega_backups', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

async def restore_local_backup(server_config: dict, query, local_backup_file: str) -> None:
    server_name = server_config["name"]
    db_full_path = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db/full"
    db_parent_dir = "/root/.humanode/workspaces/default/substrate-data/chains/humanode_mainnet/db"

    await query.edit_message_text(f"🔄 {i18n.get('restore_local_start', server_name=server_name, file_name=os.path.basename(local_backup_file))}")

    try:
        # 1. Зупинити ноду
        await query.edit_message_text(f"🛑 {i18n.get('stopping_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('stop_service_error', stderr=stderr)}", parse_mode="HTML")
            return

        # 2. Видалення старої папки БД та розпакування
        await query.edit_message_text(i18n.get('deleting_old_db_extracting'))
        await execute_command(server_config, f"rm -rf {db_full_path}")
        
        extract_cmd = f"tar -xzvf {local_backup_file} -C {db_parent_dir}"
        returncode, _, stderr = await execute_command(server_config, extract_cmd)
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('extract_archive_error', stderr=stderr)}", parse_mode="HTML")
            return

    except Exception as e:
        logger.error(f"Unexpected error during local restore: {e}")
        await query.edit_message_text(f"❌ {i18n.get('unexpected_error', error=e)}")
    finally:
        # 3. Запустити ноду
        await query.edit_message_text(f"▶️ {i18n.get('starting_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('restore_complete_node_started', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_start_after_restore_error', stderr=stderr)}", parse_mode="HTML")

async def update_node_binary(server_config: dict, query) -> None:
    server_name = server_config["name"]
    node_binary_path = "/root/.humanode/workspaces/default/humanode-peer"
    
    await query.edit_message_text(f"🔄 {i18n.get('checking_latest_release', server_name=server_name)}")
    
    try:
        # Отримання поточної версії
        current_version_cmd = f"{node_binary_path} -V"
        returncode, current_version_stdout, _ = await execute_command(server_config, current_version_cmd)
        current_version = current_version_stdout.strip().splitlines()[0] if returncode == 0 and current_version_stdout else i18n.get('unknown_version')
        
        await query.edit_message_text(f"ℹ️ {i18n.get('current_node_version', server_name=server_name, version=current_version)}")

        # Отримання останньої версії з GitHub
        github_api_url = "https://api.github.com/repos/humanode-team/humanode-peer/releases/latest"
        
        # Використання curl для отримання даних з GitHub API
        curl_cmd = f"curl -s {github_api_url}"
        returncode, github_response, stderr = await execute_command(server_config, curl_cmd)

        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('failed_to_fetch_github_releases', stderr=stderr)}", parse_mode="HTML")
            return

        release_data = json.loads(github_response)
        latest_tag = release_data.get("tag_name")
        assets = release_data.get("assets", [])

        if not latest_tag or not assets:
            await query.edit_message_text(i18n.get('no_latest_release_found'))
            return

        # Пошук asset для Linux AMD64
        download_url = None
        for asset in assets:
            if "humanode-peer-linux-amd64" in asset["name"]:
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            await query.edit_message_text(i18n.get('no_linux_amd64_asset'))
            return

        await query.edit_message_text(f"⬇️ {i18n.get('downloading_new_version', latest_tag=latest_tag)}")
        
        # Завантаження нового бінарника
        download_cmd = f"wget -q -O /tmp/humanode-peer-new {download_url}"
        returncode, _, stderr = await execute_command(server_config, download_cmd)
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('download_failed', stderr=stderr)}", parse_mode="HTML")
            return

        # Зупинка служби
        await query.edit_message_text(f"🛑 {i18n.get('stopping_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('stop_service_error', stderr=stderr)}", parse_mode="HTML")
            return

        # Заміна бінарника
        await query.edit_message_text(i18n.get('replacing_binary'))
        returncode, _, stderr = await execute_command(server_config, f"sudo mv /tmp/humanode-peer-new {node_binary_path} && sudo chmod +x {node_binary_path}")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('binary_replace_failed', stderr=stderr)}", parse_mode="HTML")
            return

        # Запуск служби
        await query.edit_message_text(f"▶️ {i18n.get('starting_node_service', server_name=server_name)}")
        returncode, _, stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        if returncode != 0:
            await query.edit_message_text(f"❌ {i18n.get('node_start_after_update_error', stderr=stderr)}", parse_mode="HTML")
            return

        # Перевірка нової версії
        returncode, new_version_stdout, _ = await execute_command(server_config, current_version_cmd)
        new_version = new_version_stdout.strip().splitlines()[0] if returncode == 0 and new_version_stdout else i18n.get('unknown_version')

        await query.edit_message_text(f"✅ {i18n.get('node_updated_success', server_name=server_name, new_version=new_version)}")

    except Exception as e:
        logger.error(f"Error updating node binary for {server_name}: {e}")
        await query.edit_message_text(f"❌ {i18n.get('error_updating_node', error=e)}")
    finally:
        # Завжди намагаємося запустити ноду, якщо вона була зупинена
        await execute_command(server_config, "sudo systemctl start humanode-peer.service")


async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє дії (перезапуск, отримати посилання) для обраного сервера."""
    query = update.callback_query
    await query.answer()
    logger.debug(f"Received action callback: {query.data} from user {query.from_user.id}")

    callback_data_suffix = query.data.replace("action_", "")
    server_id = None
    action_type = None

    for s_id in CONFIG["servers"].keys(): # Use CONFIG["servers"]
        if callback_data_suffix.endswith(f"_{s_id}"):
            server_id = s_id
            action_type = callback_data_suffix[:-(len(s_id) + 1)]
            break

    if not server_id or not action_type:
        # Обробка для restore_mega_select
        if callback_data_suffix.startswith("restore_mega_select_"):
            parts = callback_data_suffix.split('_')
            server_id = parts[3]
            action_type = "restore_mega_select"
            mega_file_name = "_".join(parts[4:])
            context.user_data["mega_file_name"] = mega_file_name
        else:
            logger.error(f"Invalid callback data: {query.data}")
            await query.edit_message_text(i18n.get("invalid_action_server"))
            return

    server_config = CONFIG["servers"].get(server_id) # Use CONFIG["servers"]
    if not server_config:
        logger.error(f"Server not found: {server_id}")
        await query.edit_message_text(i18n.get("unknown_server"))
        return

    server_name = server_config["name"]

    if action_type == "create_backup":
        await perform_backup_and_upload(server_config, query)
    elif action_type == "restore_mega_select":
        mega_file_name = context.user_data.get("mega_file_name")
        if mega_file_name:
            await restore_mega_backup(server_config, query, mega_file_name)
        else:
            await query.edit_message_text(i18n.get("no_file_name_for_restore"))
    elif action_type == "node_management":
        await node_management_menu(update, context, server_id)
    elif action_type == "get_link":
        await query.edit_message_text(f"{i18n.get('searching_link', server_name=server_name)}")
        try:
            # Перевіряємо та перезапускаємо тунель, якщо потрібно
            tunnel_ok = await check_and_restart_tunnel_service(server_config, query)
            
            if not tunnel_ok:
                await query.edit_message_text(f"❌ {i18n.get('tunnel_not_working_link_impossible', server_name=server_name)}")
                return

            url = get_latest_url_from_logs(server_config)
            if url:
                await query.edit_message_text(f"{i18n.get('humanode_link_found', server_name=server_name, url=url)}")
            else:
                await query.edit_message_text(f"{i18n.get('failed_to_get_url_check_node_logs', server_name=server_name)}")
        except Exception as e:
            logger.error(f"Error in get_link for {server_name}: {e}")
            await query.edit_message_text(f"{i18n.get('error_getting_link', server_name=server_name, error=e)}")

    elif action_type == "view_log":
        await query.edit_message_text(f"{i18n.get('getting_last_log_lines', server_name=server_name)}")
        try:
            log_cmd = "sudo journalctl -u humanode-peer.service -n 20 --no-pager"
            returncode, stdout, stderr = await execute_command(server_config, log_cmd)

            if returncode == 0 and stdout.strip():
                log_contents = remove_emoji(stdout.strip())
                message = f"📄 {i18n.get('last_log_lines', server_name=server_name)}\n\n<pre>{log_contents}</pre>"
                await query.edit_message_text(message, parse_mode="HTML")
            else:
                await query.edit_message_text(f"❌ {i18n.get('failed_to_read_log', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

        except Exception as e:
            logger.error(f"Error viewing log for {server_name}: {e}")
            await query.edit_message_text(f"Виникла помилка при перегляді логу з {server_name}: {e}")

    elif action_type == "get_bioauth_timer":
        await query.edit_message_text(f"{i18n.get('checking_bioauth_timer', server_name=server_name)}")
        screenshot_path = None
        try:
            # Перевіряємо та перезапускаємо тунель, якщо потрібно
            tunnel_ok = await check_and_restart_tunnel_service(server_config, query)
            if not tunnel_ok:
                await query.edit_message_text(f"❌ {i18n.get('tunnel_not_working_link_impossible', server_name=server_name)}")
                return

            url = get_latest_url_from_logs(server_config)
            if not url:
                await query.edit_message_text(f"{i18n.get('no_humanode_link_found_bioauth', server_name=server_name)}")
                return

            remaining_seconds, screenshot_path = get_bioauth_countdown_seconds(url)

            await query.delete_message()

            if remaining_seconds != -1 and screenshot_path:
                formatted_time = format_seconds_to_hhmmss(remaining_seconds)
                caption = f"{i18n.get('bioauth_time_remaining', server_name=server_name, time=formatted_time)}"
                await query.message.reply_photo(photo=open(screenshot_path, 'rb'), caption=caption)
            else:
                await query.message.reply_text(f"{i18n.get('failed_to_get_bioauth_time', server_name=server_name)}")

        except Exception as e:
            logger.error(f"Error in get_bioauth_timer for {server_name}: {e}")
            try:
                await query.edit_message_text(f"{i18n.get('error_checking_bioauth_timer', server_name=server_name, error=e)}")
            except Exception:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"{i18n.get('error_checking_bioauth_timer', server_name=server_name, error=e)}")

        finally:
            if screenshot_path and os.path.exists(screenshot_path):
                os.remove(screenshot_path)

    elif action_type == "start_node":
        await query.edit_message_text(f"{i18n.get('starting_node_service', server_name=server_name)}")
        returncode, stdout, stderr = await execute_command(server_config, "sudo systemctl start humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('node_service_started_success', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_service_start_error', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

    elif action_type == "stop_node":
        await query.edit_message_text(f"{i18n.get('stopping_node_service', server_name=server_name)}")
        returncode, stdout, stderr = await execute_command(server_config, "sudo systemctl stop humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('node_service_stopped_success', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_service_stop_error', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

    elif action_type == "restart_node":
        await query.edit_message_text(f"{i18n.get('restarting_node_service', server_name=server_name)}")
        returncode, stdout, stderr = await execute_command(server_config, "sudo systemctl restart humanode-peer.service")
        if returncode == 0:
            await query.edit_message_text(f"✅ {i18n.get('node_service_restarted_success', server_name=server_name)}")
        else:
            await query.edit_message_text(f"❌ {i18n.get('node_service_restart_error', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

    elif action_type == "status_node":
        await query.edit_message_text(f"{i18n.get('getting_node_status', server_name=server_name)}")
        returncode, stdout, stderr = await execute_command(server_config, "sudo systemctl status humanode-peer.service")
        if returncode == 0:
            status_lines = stdout.split('\n')
            filtered_status = [line for line in status_lines if "Active:" in line or "Loaded:" in line or "Main PID:" in line or "Memory:" in line]
            status_text = "\n".join(filtered_status)
            
            if "Active: active (running)" in stdout:
                status_emoji = "✅"
            elif "Active: inactive" in stdout:
                status_emoji = "🔴"
            elif "Active: failed" in stdout:
                status_emoji = "❌"
            else:
                status_emoji = "ℹ️"

            await query.edit_message_text(f"{status_emoji} {i18n.get('node_service_status', server_name=server_name)}\n\n<pre>{status_text}</pre>", parse_mode="HTML")
        else:
            await query.edit_message_text(f"❌ {i18n.get('failed_to_get_node_status', server_name=server_name, stderr=stderr)}", parse_mode="HTML")

    elif action_type == "get_node_version":
        await query.edit_message_text(f"{i18n.get('getting_node_version', server_name=server_name)}")
        try:
            node_binary_path = "/root/.humanode/workspaces/default/humanode-peer" # This should ideally be configurable
            version_cmd = f"{node_binary_path} -V"
            returncode, stdout, stderr = await execute_command(server_config, version_cmd)

            if returncode == 0 and stdout.strip():
                version_info = stdout.strip()
                message = f"🏷️ {i18n.get('node_version', server_name=server_name)}\n\n<pre>{version_info}</pre>"
                await query.edit_message_text(message, parse_mode="HTML")
            else:
                await query.edit_message_text(f"❌ {i18n.get('failed_to_get_node_version', server_name=server_name, stderr=stderr)}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error getting node version for {server_name}: {e}")
            await query.edit_message_text(f"{i18n.get('error_getting_node_version', server_name=server_name, error=e)}")

    elif action_type == "update_node":
        await update_node_binary(server_config, query)
    elif action_type == "restore_db_menu":
        await restore_menu(update, context, server_id)
    elif action_type == "restore_local":
        backup_dir = "/root/humanode_backups/" # This should ideally be configurable
        find_latest_cmd = f"ls -t {backup_dir}humanode_db_*.tar.gz | head -n 1"
        returncode, stdout, stderr = await execute_command(server_config, find_latest_cmd)
        
        if returncode == 0 and stdout.strip():
            latest_backup_file = stdout.strip()
            await restore_local_backup(server_config, query, latest_backup_file)
        else:
            await query.edit_message_text(f"❌ {i18n.get('no_local_backups_found', backup_dir=backup_dir, server_name=server_name, stderr=stderr)}", parse_mode="HTML")

    elif action_type == "restore_mega":
        await list_mega_backups(update, context, server_id)

async def post_init(application: Application) -> None:
    """Initialise bot commands"""
    await application.bot.set_my_commands([
        BotCommand("/start", i18n.get("command_start_description")),
        BotCommand("/menu", i18n.get("command_menu_description")),
    ])

async def main() -> None:
    global CONFIG, i18n
    
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.critical(f"CRITICAL: Could not load or parse config.json. Error: {e}")
        return

    i18n = I18n(CONFIG.get("default_language", "en"))

    application = Application.builder().token(CONFIG["telegram_bot_token"]).post_init(post_init).build()

    # Setup JobQueue for background tasks
    job_queue = application.job_queue
    # This job will run every 10 minutes (600 seconds)
    job_queue.run_repeating(bioauth_check_job, interval=600, first=10) # Check every 10 minutes

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CallbackQueryHandler(select_server, pattern=r"^select_server_.*?\\Z"))
    application.add_handler(CallbackQueryHandler(handle_action, pattern=r"^action_.*?\\Z"))

    logger.info("Bot handlers added. Starting polling...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"An error occurred during bot polling: {e}")
    logger.info("Bot stopped.")

# Placeholder for bioauth_check_job - needs to be implemented based on the repository's bot logic
async def bioauth_check_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running background bioauth check...")
    bot = context.bot
    
    for server_id, server_config in CONFIG.get("servers", {}).items():
        try:
            logger.info(f"Checking server: {server_config['name']}")
            
            # Ensure tunnel is active before checking bioauth
            # Note: This is a simplified check for background job.
            # Full restart logic is in handle_action for user-triggered actions.
            tunnel_status_cmd = f"sudo systemctl status humanode-websocket-tunnel.service"
            returncode, stdout, _ = await execute_command(server_config, tunnel_status_cmd)
            if not (returncode == 0 and "Active: active (running)" in stdout):
                logger.warning(f"Tunnel service for {server_config['name']} is not active. Skipping bioauth check.")
                continue

            url = get_latest_url_from_logs(server_config)
            
            if not url:
                logger.warning(f"No active URL found for {server_config['name']}. Skipping bioauth check.")
                continue
                
            remaining_seconds, _ = get_bioauth_countdown_seconds(url) # This is a synchronous call, ideally should be run in a thread pool

            if remaining_seconds == -1:
                logger.error(f"Failed to get bioauth time for {server_config['name']}.")
                continue

            notification_key = f'notification_sent_{server_id}'
            
            # Notify if less than 10 minutes (600 seconds) remaining
            if 0 <= remaining_seconds < 600:
                if not context.bot_data.get(notification_key, False):
                    logger.info(f"Time for {server_config['name']} is below 10 minutes. Sending notification.")
                    message = i18n.get("bioauth_notification", server_name=server_config['name'], time=format_seconds_to_hhmmss(remaining_seconds))
                    
                    await bot.send_message(chat_id=CONFIG["authorized_user_id"], text=message)
                    context.bot_data[notification_key] = True
            
            # Reset notification flag if time is healthy again (e.g., > 11 minutes)
            elif remaining_seconds > 660:
                if context.bot_data.get(notification_key, False):
                    logger.info(f"Timer for {server_config['name']} is healthy again. Resetting notification flag.")
                    context.bot_data[notification_key] = False
        except Exception as e:
            logger.error(f"An error occurred during background check for {server_config['name']}: {e}")


if __name__ == "__main__":
    main()