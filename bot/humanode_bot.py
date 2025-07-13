import json
import logging
import re
import asyncio
import os
import time
from datetime import datetime, timedelta
from telegram.error import BadRequest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# --- Налаштування логування ---
logging.basicConfig(
    filename='humanode_bot.log',
    filemode='a',
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Глобальні ��мінні для конфігурації та локалізації ---
CONFIG = {}
LANG = {}

# --- Клас для локалізації ---
class I18n:
    def __init__(self, lang_code='en'):
        self.lang_code = lang_code
        self.load_language()

    def load_language(self):
        global LANG
        try:
            # Шлях до файлів локалізації відносно поточного файлу
            locales_path = os.path.join(os.path.dirname(__file__), 'locales', f'{self.lang_code}.json')
            with open(locales_path, 'r', encoding='utf-8') as f:
                LANG = json.load(f)
            logger.info(f"Мову '{self.lang_code}' успішно завантажено.")
        except FileNotFoundError:
            logger.error(f"Файл мови для '{self.lang_code}' не знайдено. Буде використано 'en'.")
            if self.lang_code != 'en':
                self.lang_code = 'en'
                self.load_language()

    def get(self, key, **kwargs):
        return LANG.get(key, key).format(**kwargs)

# Ініціалізація переклада��а
i18n = I18n()

# --- Основні функції бота ---

async def execute_command(server_config, command):
    # ... (ця функція залишається такою ж, як ми її реалізували раніше)
    pass

async def execute_command_with_progress(server_config, command, query, initial_message_key, **kwargs):
    # ... (ця функція також залишається)
    pass

# ... (всі інші функції, як-от get_latest_url, get_bioauth_countdown_seconds, і т.д. залишаються,
# але всі текстові повідомлення в них будуть замінені на виклики i18n.get())

# --- Обробники команд Telegram ---

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

    keyboard = [
        [InlineKeyboardButton(server["name"], callback_data=f"select_server_{server_id}")]
        for server_id, server in CONFIG.get("servers", {}).items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(i18n.get("choose_server"), reply_markup=reply_markup)

# ... (решта обробників також будуть оновлені для використання i18n)

async def select_server(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    server_id = query.data.replace("select_server_", "")
    server_name = CONFIG["servers"][server_id]["name"]

    keyboard = [
        [InlineKeyboardButton(i18n.get("action_get_link"), callback_data=f"action_get_link_{server_id}")],
        [InlineKeyboardButton(i18n.get("action_manage_node"), callback_data=f"action_node_management_{server_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text=i18n.get("server_chosen", server_name=server_name),
        reply_markup=reply_markup
    )

# --- Головна функція ---

def main() -> None:
    global CONFIG, i18n
    
    # Завантаження конфігурації
    try:
        # Шлях до config.json відносно поточного файлу
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        with open(config_path, 'r') as f:
            CONFIG = json.load(f)
    except FileNotFoundError:
        logger.critical("CRITICAL: config.json не знайдено! Запустіть install.sh або створіть конфігурацію вручну.")
        return
    except json.JSONDecodeError:
        logger.critical("CRITICAL: Не вдалося прочитати config.json. Перевірте синтаксис файлу.")
        return

    # Встановлення мови з конфігурації
    i18n = I18n(CONFIG.get("default_language", "en"))

    # Створення та запуск додатка
    application = Application.builder().token(CONFIG["telegram_bot_token"]).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CallbackQueryHandler(select_server, pattern=r"^select_server_.*"))
    # ... (додавання решти обробників)

    logger.info("Бот запускається...")
    application.run_polling()

if __name__ == "__main__":
    main()
