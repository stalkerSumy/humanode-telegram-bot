import json
import logging
import subprocess
import re
import asyncio
import os
from datetime import datetime, timedelta, timezone

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Selenium imports will be handled conditionally
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service as ChromeService
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# --- Configuration Loading ---
class Config:
    def __init__(self, path='/opt/humanode-bot/config.json'):
        try:
            with open(path, 'r') as f:
                config_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[FATAL] Could not load or parse config file at {path}: {e}")
            exit(1)

        self.token = config_data.get("telegram_bot_token")
        self.authorized_user_id = config_data.get("authorized_user_id")
        self.state_file = config_data.get("state_file", "/tmp/bot_state.json")
        self.log_file = config_data.get("log_file", "/tmp/humanode_bot.log")
        self.servers = config_data.get("servers", {})
        
        # Selenium error paths
        self.selenium_error_screenshot = "/tmp/selenium_error.png"
        self.selenium_page_source = "/tmp/selenium_page_source.html"

        if not self.token or not self.authorized_user_id:
            print("[FATAL] 'telegram_bot_token' and 'authorized_user_id' must be set in config.json")
            exit(1)

# --- Global Config Instance ---
config = Config()

# --- Constants ---
FULL_CHECK_INTERVAL_HOURS = 168
JOB_QUEUE_INTERVAL_MINUTES = 1

# --- Logging Setup ---
# Ensure log directory exists
os.makedirs(os.path.dirname(config.log_file), exist_ok=True)
logging.basicConfig(
    filename=config.log_file,
    filemode='a',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
if SELENIUM_AVAILABLE:
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("webdriver_manager").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- State Management ---
def load_state():
    os.makedirs(os.path.dirname(config.state_file), exist_ok=True)
    try:
        with open(config.state_file, 'r') as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    state.setdefault("notification_settings", {
        "first_warning_minutes": 30,
        "second_warning_minutes": 10,
        "alert_interval_minutes": 5,
    })
    state.setdefault("servers", {})

    for server_id in config.servers.keys():
        state["servers"].setdefault(server_id, {})
        server_state = state["servers"][server_id]
        server_state.setdefault("last_full_check_utc", None)
        server_state.setdefault("bioauth_deadline_utc", None)
        server_state.setdefault("notified_first", False)
        server_state.setdefault("notified_second", False)
        server_state.setdefault("is_in_alert_mode", False)
        server_state.setdefault("last_alert_utc", None)

    return state

def save_state(state):
    try:
        with open(config.state_file, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")

# --- Utility Functions (These remain largely the same) ---
def format_seconds_to_hhmmss(seconds: int) -> str:
    if seconds < 0: return "N/A"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}"

def remove_emoji(text: str) -> str:
    return re.sub("[\U00010000-\U0010ffff]", "", text)

def parse_percentage_to_minutes(percentage_str: str, total_epoch_minutes: int = 240) -> int:
    match = re.search(r"width:\s*(\d+\.?\d*)%", percentage_str)
    if match:
        progress_percentage = float(match.group(1))
        remaining_percentage = 100 - progress_percentage
        return int(total_epoch_minutes * (remaining_percentage / 100))
    return -1

# --- Core Bot Logic ---
async def execute_command(server_config: dict, command: str) -> tuple[int, str, str]:
    shell_command = command
    if not server_config.get("is_local", False):
        key_path = server_config.get('key_path')
        if not key_path:
            logger.error(f"SSH key path is not defined for remote server {server_config['name']}")
            return -1, "", "SSH key path not configured."
        shell_command = f"ssh -i {key_path} -o StrictHostKeyChecking=no -o ConnectTimeout=10 {server_config['user']}@{server_config['ip']} \"{command}\"
    
    process = await asyncio.create_subprocess_shell(
        shell_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()

async def get_latest_url_from_logs(server_config: dict, query=None):
    # This function remains largely the same, but we add a check for Selenium availability
    if not SELENIUM_AVAILABLE:
        if query:
            await query.edit_message_text("❌ Selenium is not installed. Cannot perform this action.")
        logger.error("Attempted to get URL but Selenium libraries are missing.")
        return None

    base_url = "https://webapp.mainnet.stages.humanode.io/"
    log_cmd = "journalctl -u humanode-websocket-tunnel.service -n 20 --no-pager"
    
    if query:
        await query.edit_message_text(f"🔄 Checking tunnel service on {server_config['name']}...")

    # Simplified tunnel check
    returncode, stdout, _ = await execute_command(server_config, f"sudo systemctl status humanode-websocket-tunnel.service")
    if not (returncode == 0 and "Active: active (running)" in stdout):
        if query: await query.edit_message_text(f"⚠️ Tunnel service inactive, restarting...")
        await execute_command(server_config, f"sudo systemctl restart humanode-websocket-tunnel.service")
        await asyncio.sleep(10)

    # Get URL from logs
    returncode, stdout, stderr = await execute_command(server_config, log_cmd)
    if returncode == 0 and stdout:
        log_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z).*?url=(wss://[^\s]+htunnel\.app)")
        latest_url = None
        latest_timestamp = None
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
            logger.info(f"Found tunnel URL for {server_config['name']}: {full_url}")
            return full_url

    logger.warning(f"Could not find any URL for {server_config['name']}. Stderr: {stderr}")
    return None

def get_bioauth_and_epoch_times(driver: webdriver.Chrome, url: str) -> tuple[int, int]:
    if not url: return -1, -1
    bioauth_seconds, epoch_minutes = -1, -1
    try:
        wait = WebDriverWait(driver, 90)
        logger.info(f"Selenium: Navigating to URL: {url}")
        driver.get(url)
        
        dashboard_selector = "//span[text()='Dashboard']"
        wait.until(EC.element_to_be_clickable((By.XPATH, dashboard_selector)))
        
        bioauth_label_xpath = "//p[text()='Bioauth']"
        wait.until(EC.visibility_of_element_located((By.XPATH, bioauth_label_xpath)))
        timer_element = wait.until(EC.visibility_of_element_located((By.XPATH, f"{bioauth_label_xpath}/following-sibling::h6")))
        
        parts = timer_element.text.split(':')
        if len(parts) == 3:
            bioauth_seconds = int(timedelta(hours=int(parts[0]), minutes=int(parts[1]), seconds=int(parts[2])).total_seconds())

        epoch_progress_xpath = "//p[text()='Epoch']/following-sibling::div//div[contains(@style, 'width')]"
        epoch_element = wait.until(EC.visibility_of_element_located((By.XPATH, epoch_progress_xpath)))
        epoch_minutes = parse_percentage_to_minutes(epoch_element.get_attribute("style"))

    except Exception:
        try:
            driver.save_screenshot(config.selenium_error_screenshot)
            with open(config.selenium_page_source, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.error(f"Selenium error. Screenshot saved to {config.selenium_error_screenshot}", exc_info=True)
        except Exception as dump_e:
            logger.error(f"Failed to save error dump. Dump error: {dump_e}", exc_info=True)
        return -1, -1
    
    return bioauth_seconds, epoch_minutes

# --- Periodic Task ---
async def periodic_bioauth_check(context: ContextTypes.DEFAULT_TYPE):
    if not SELENIUM_AVAILABLE: return
    logger.info("Running periodic bioauth check...")
    state = load_state()
    now_utc = datetime.now(timezone.utc)
    driver = context.bot_data.get('selenium_driver')
    if not driver:
        logger.error("Selenium driver not found for periodic check.")
        return

    for server_id, server_config in config.servers.items():
        server_state = state["servers"][server_id]
        last_check_str = server_state.get("last_full_check_utc")
        perform_full_check = not last_check_str or (now_utc - datetime.fromisoformat(last_check_str) > timedelta(hours=FULL_CHECK_INTERVAL_HOURS))

        if perform_full_check:
            logger.info(f"Performing full bioauth check for {server_config['name']}.")
            url = await get_latest_url_from_logs(server_config)
            if url:
                bioauth_seconds, _ = await asyncio.to_thread(get_bioauth_and_epoch_times, driver, url)
                if bioauth_seconds > 0:
                    deadline = now_utc + timedelta(seconds=bioauth_seconds)
                    server_state.update({
                        "bioauth_deadline_utc": deadline.isoformat(), "last_full_check_utc": now_utc.isoformat(),
                        "notified_first": False, "notified_second": False, "is_in_alert_mode": False
                    })
                    logger.info(f"Updated bioauth deadline for {server_config['name']} to {deadline.isoformat()}")
                else:
                    logger.error(f"Failed to get remaining seconds for {server_config['name']}.")
        
        deadline_str = server_state.get("bioauth_deadline_utc")
        if not deadline_str: continue

        deadline = datetime.fromisoformat(deadline_str)
        time_left = deadline - now_utc
        settings = state["notification_settings"]

        # Notification logic remains the same, but uses the global authorized_user_id
        if time_left.total_seconds() < 0:
            if not server_state.get("is_in_alert_mode"):
                server_state["is_in_alert_mode"] = True
                await context.bot.send_message(config.authorized_user_id, f"🔴 <b>ALERT</b>: Bioauth for <b>{server_config['name']}</b> is overdue!", parse_mode=ParseMode.HTML)
        elif time_left < timedelta(minutes=settings["second_warning_minutes"]) and not server_state.get("notified_second"):
            await context.bot.send_message(config.authorized_user_id, f"🟠 <b>WARNING</b>: Less than {settings['second_warning_minutes']} mins for bioauth on <b>{server_config['name']}</b>.", parse_mode=ParseMode.HTML)
            server_state["notified_second"] = True
        elif time_left < timedelta(minutes=settings["first_warning_minutes"]) and not server_state.get("notified_first"):
            await context.bot.send_message(config.authorized_user_id, f"🟡 <b>Reminder</b>: Less than {settings['first_warning_minutes']} mins for bioauth on <b>{server_config['name']}</b>.", parse_mode=ParseMode.HTML)
            server_state["notified_first"] = True
            
    save_state(state)

# --- Menus and UI (Refactored to use config) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == config.authorized_user_id:
        await update.message.reply_html(f"Hello, {update.effective_user.mention_html()}!", reply_markup=await main_menu_keyboard())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    keyboard = await main_menu_keyboard()
    text = "Select an action or a server to manage:"
    if query: 
        try:
            await query.edit_message_text(text, reply_markup=keyboard)
        except BadRequest as e:
            if "Message is not modified" not in str(e): logger.error(f"Error in menu: {e}")
    else: 
        await update.message.reply_text(text, reply_markup=keyboard)

async def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Notification Settings", callback_data="notification_settings")],
        *[
            [InlineKeyboardButton(server_info["name"], callback_data=f"select_server_{server_id}")]
            for server_id, server_info in config.servers.items()
        ],
    ])

async def select_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = query.data.replace("select_server_", "")
    server_config = config.servers.get(server_id)
    if not server_config:
        await query.edit_message_text("Error: Unknown server.", reply_markup=await main_menu_keyboard())
        return
        
    keyboard = [
        [InlineKeyboardButton("🔗 Get Link", callback_data=f"action_get_link_{server_id}")],
        [InlineKeyboardButton("⏱️ Bioauth Timer", callback_data=f"action_get_bioauth_timer_{server_id}")],
        [InlineKeyboardButton("⚙️ Node Management", callback_data=f"action_node_management_{server_id}")],
        [InlineKeyboardButton("📄 View Log", callback_data=f"action_view_log_{server_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
    ]
    await query.edit_message_text(f"Selected: {server_config['name']}", reply_markup=InlineKeyboardMarkup(keyboard))

# Other menus (node_management_menu, etc.) are similar and call actions
# Let's simplify and merge them into the action handler

# --- Action Handlers (Refactored) ---
async def handle_generic_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # Simple actions first
    action_map = {
        "action_get_link": get_link_action,
        "action_get_bioauth_timer": get_bioauth_timer_action,
        "action_view_log": view_log_action,
        "action_start_node": lambda u,c,s: node_service_action(u,c,s,'start'),
        "action_stop_node": lambda u,c,s: node_service_action(u,c,s,'stop'),
        "action_restart_node": lambda u,c,s: node_service_action(u,c,s,'restart'),
        "action_status_node": lambda u,c,s: node_service_action(u,c,s,'status'),
    }

    for prefix, handler in action_map.items():
        if data.startswith(prefix):
            server_id = data.replace(f"{prefix}_", "")
            if server_id in config.servers:
                await handler(update, context, server_id)
                return
    
    # Menu actions
    if data.startswith("action_node_management_"):
        server_id = data.split("_")[-1]
        keyboard = [
            [InlineKeyboardButton("🟢 Start", callback_data=f"action_start_node_{server_id}"), InlineKeyboardButton("🔴 Stop", callback_data=f"action_stop_node_{server_id}")],
            [InlineKeyboardButton("🔄 Restart", callback_data=f"action_restart_node_{server_id}"), InlineKeyboardButton("ℹ️ Status", callback_data=f"action_status_node_{server_id}")],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"select_server_{server_id}")],
        ]
        await query.edit_message_text(f"⚙️ Node Management: {config.servers[server_id]['name']}", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    logger.warning(f"Unhandled action: {data}")

async def get_link_action(update, context, server_id):
    server_config = config.servers[server_id]
    await update.callback_query.edit_message_text(f"⏳ Finding link for {server_config['name']}...")
    url = await get_latest_url_from_logs(server_config, update.callback_query)
    text = f"Link for {server_config['name']}:\n\n{url}" if url else f"❌ Could not find link for {server_config['name']}."
    await update.callback_query.edit_message_text(text, disable_web_page_preview=True)

async def get_bioauth_timer_action(update, context, server_id):
    if not SELENIUM_AVAILABLE:
        await update.callback_query.edit_message_text("❌ Selenium is not installed. Cannot perform this action.")
        return
    
    query = update.callback_query
    server_config = config.servers[server_id]
    await query.edit_message_text(f"⏳ Getting URL for {server_config['name']}...")
    url = await get_latest_url_from_logs(server_config, query)
    if not url: return

    await query.edit_message_text(f"⏱️ Checking timer for {server_config['name']} (can take up to 90s)...")
    driver = context.bot_data.get('selenium_driver')
    if not driver:
        await query.edit_message_text("❌ Selenium driver not initialized.")
        return

    bioauth_seconds, epoch_minutes = await asyncio.to_thread(get_bioauth_and_epoch_times, driver, url)
    bioauth_text = f"⏱️ Bioauth time: {format_seconds_to_hhmmss(bioauth_seconds)}" if bioauth_seconds != -1 else "❌ Bioauth time not found."
    epoch_text = f"⏳ Epoch time: {epoch_minutes} min" if epoch_minutes != -1 else "❌ Epoch time not found."
    await query.edit_message_text(f"{bioauth_text}\n{epoch_text}")

async def view_log_action(update, context, server_id):
    server_config = config.servers[server_id]
    await update.callback_query.edit_message_text(f"Getting last 20 log lines from {server_config['name']}...")
    log_cmd = "sudo journalctl -u humanode-peer.service -n 20 --no-pager"
    returncode, stdout, stderr = await execute_command(server_config, log_cmd)
    text = f"📄 Log:\n<pre>{remove_emoji(stdout.strip())}</pre>" if returncode == 0 and stdout.strip() else f"❌ Failed to read log:\n<pre>{stderr}</pre>"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def node_service_action(update, context, server_id, action):
    server_config = config.servers[server_id]
    await update.callback_query.edit_message_text(f"Executing: {action} for {server_config['name']}...")
    cmd = f"sudo systemctl {action} humanode-peer.service"
    returncode, stdout, stderr = await execute_command(server_config, cmd)
    if action == 'status':
        text = f"ℹ️ Status:\n<pre>{stdout.strip()}</pre>" if returncode == 0 else f"❌ Error:\n<pre>{stderr}</pre>"
    else:
        text = f"✅ Command '{action}' executed." if returncode == 0 else f"❌ Error:\n<pre>{stderr}</pre>"
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)

# Settings conversation remains the same as it already uses load/save state

# --- Main Application Setup ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("/start", "Start the bot"),
        BotCommand("/menu", "Show main menu"),
    ])
    if SELENIUM_AVAILABLE:
        logger.info("Selenium is available. Initializing driver...")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        service = ChromeService(ChromeDriverManager().install())
        application.bot_data['selenium_driver'] = webdriver.Chrome(service=service, options=options)
        application.job_queue.run_repeating(periodic_bioauth_check, interval=timedelta(minutes=JOB_QUEUE_INTERVAL_MINUTES), first=10)
    else:
        logger.warning("Selenium is not installed. Bioauth checks will be disabled.")

async def on_shutdown(application: Application):
    if 'selenium_driver' in application.bot_data and application.bot_data.get('selenium_driver'):
        logger.info("Closing Selenium driver.")
        application.bot_data['selenium_driver'].quit()

def main():
    logger.info("Starting bot with configuration...")
    
    application = Application.builder().token(config.token).post_init(post_init).post_shutdown(on_shutdown).build()

    # Handlers
    application.add_handler(CommandHandler("start", start, filters=filters.User(user_id=config.authorized_user_id)))
    application.add_handler(CommandHandler("menu", menu, filters=filters.User(user_id=config.authorized_user_id)))
    application.add_handler(CallbackQueryHandler(menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(select_server, pattern=r"^select_server_"))
    # The generic handler will now manage all actions, including opening sub-menus
    application.add_handler(CallbackQueryHandler(handle_generic_action, pattern=r"^action_"))

    # Settings conversation handler can be added here if needed
    
    logger.info("Bot handlers added. Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Bot crashed with an unhandled exception: {e}", exc_info=True)