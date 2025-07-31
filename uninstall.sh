#!/bin/bash

# Humanode Bot Uninstaller
# Safely removes the bot and all related components.

# --- Language Strings ---
declare -A TEXTS

setup_texts() {
    local lang=$1
    if [[ "$lang" == "ua" ]]; then
        TEXTS[welcome]="=================================================\n      Деінсталятор Humanode Management Bot      \n================================================="
        TEXTS[root_needed]="Для коректної роботи потрібні права адміністратора. Будь ласка, запустіть скрипт через 'sudo'."
        TEXTS[confirm_prompt]="ПОПЕРЕДЖЕННЯ: Ця дія повністю видалить бота, його конфігурацію та службу systemd. Ви впевнені, що хочете продовжити? (y/n): "
        TEXTS[stopping_service]="Зупиняю службу humanode_bot..."
        TEXTS[disabling_service]="Вимикаю автозапуск служби humanode_bot..."
        TEXTS[removing_service_file]="Видаляю файл служби systemd..."
        TEXTS[reloading_daemon]="Оновлюю конфігурацію systemd..."
        TEXTS[removing_install_dir]="Видаляю директорію встановлення /opt/humanode-bot..."
        TEXTS[complete]="=================================\n  Деінсталяцію завершено!  \n================================="
        TEXTS[cancelled]="Деінсталяцію скасовано користувачем."
    else # English
        TEXTS[welcome]="==============================================\n      Humanode Management Bot Uninstaller      \n=============================================="
        TEXTS[root_needed]="This script requires root privileges to run correctly. Please execute it with 'sudo'."
        TEXTS[confirm_prompt]="WARNING: This action will permanently delete the bot, its configuration, and the systemd service. Are you sure you want to continue? (y/n): "
        TEXTS[stopping_service]="Stopping humanode_bot service..."
        TEXTS[disabling_service]="Disabling humanode_bot service auto-start..."
        TEXTS[removing_service_file]="Removing systemd service file..."
        TEXTS[reloading_daemon]="Reloading systemd daemon..."
        TEXTS[removing_install_dir]="Removing installation directory /opt/humanode-bot..."
        TEXTS[complete]="==================================\n  Uninstallation Complete!  \n=================================="
        TEXTS[cancelled]="Uninstallation cancelled by the user."
    fi
}

# --- Helper Functions ---
info() { echo -e "\033[0;34mINFO:\033[0m $1"; }
error() { echo -e "\033[0;31mERROR:\033[0m $1" >&2; exit 1; }

# --- Main Logic ---
main() {
    read -p "Виберіть мову / Select language (ua/en) [en]: " lang
    lang=${lang:-en}
    setup_texts "$lang"

    echo -e "\n\033[1;33m${TEXTS[welcome]}\033[0m\n"

    if [[ "$EUID" -ne 0 ]]; then
        error "${TEXTS[root_needed]}"
    fi

    read -p "${TEXTS[confirm_prompt]}" -n 1 -r
    echo
    if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
        info "${TEXTS[cancelled]}"
        exit 0
    fi

    local service_file="/etc/systemd/system/humanode_bot.service"
    local install_dir="/opt/humanode-bot"

    info "${TEXTS[stopping_service]}"
    systemctl stop humanode_bot.service || true # Ignore error if not running

    info "${TEXTS[disabling_service]}"
    systemctl disable humanode_bot.service || true # Ignore error if not enabled

    if [ -f "$service_file" ]; then
        info "${TEXTS[removing_service_file]}"
        rm -f "$service_file"
    fi

    info "${TEXTS[reloading_daemon]}"
    systemctl daemon-reload

    if [ -d "$install_dir" ]; then
        info "${TEXTS[removing_install_dir]}"
        rm -rf "$install_dir"
    fi

    echo -e "\n\033[1;32m${TEXTS[complete]}\033[0m\n"
}

# --- Run main function ---
main