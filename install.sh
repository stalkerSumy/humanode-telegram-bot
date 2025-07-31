#!/bin/bash

# Humanode Bot Universal Installer v2.0
# Automates the entire setup process including dependency installation,
# configuration, and systemd service setup.

# --- Stop on any error ---
set -e

# --- Global Variables ---
INSTALL_DIR=""
VENV_DIR=""
BOT_DIR=""
SUDO_CMD=""
OWNER_USER=""
OWNER_GROUP=""

# --- Language Strings ---
declare -A TEXTS

setup_texts() {
    local lang=$1
    if [[ "$lang" == "ua" ]]; then
        TEXTS[welcome]="=================================================\n Вітаємо в інсталяторі Humanode Management Bot v2.0 \n================================================="
        TEXTS[root_needed]="Для коректної роботи інсталятора потрібні права адміністратора. Будь ласка, запустіть його через 'sudo'."
        TEXTS[dep_check]="Перевірка та встановлення залежностей..."
        TEXTS[dep_ok]="Усі залежності встановлено."
        TEXTS[cloning_repo]="Клоную репозиторій в %s..."
        TEXTS[repo_exists]="Директорія %s вже існує. Оновлюю з GitHub..."
        TEXTS[config_creating]="Створюю файли конфігурації..."
        TEXTS[config_done]="Файли конфігурації створено. Не забудьте їх відредагувати!"
        TEXTS[venv_creating]="Створюю віртуальне оточення Python..."
        TEXTS[req_installing]="Встановлюю залежності Python..."
        TEXTS[systemd_setup]="Налаштовую службу systemd для автозапуску..."
        TEXTS[systemd_done]="Службу systemd налаштовано та запущено."
        TEXTS[install_complete]="=================================\n  Встановлення завершено!  \n================================="
        TEXTS[edit_config]="ВАЖЛИВО: Відредагуйте файл '%s/config.json' та '%s/servers.json', вказавши ваші дані."
        TEXTS[status_cmd]="Щоб перевірити статус бота, виконайте: sudo systemctl status humanode_bot"
        TEXTS[logs_cmd]="Щоб переглянути логи, виконайте: sudo journalctl -u humanode_bot -f"
        TEXTS[start_cmd]="Щоб (пере)запустити бота після редагування конфігурації: sudo systemctl restart humanode_bot"
    else # English
        TEXTS[welcome]="==============================================\n Welcome to the Humanode Management Bot Installer v2.0 \n============================================="
        TEXTS[root_needed]="This installer requires root privileges to run correctly. Please execute it with 'sudo'."
        TEXTS[dep_check]="Checking and installing dependencies..."
        TEXTS[dep_ok]="All dependencies are installed."
        TEXTS[cloning_repo]="Cloning repository into %s..."
        TEXTS[repo_exists]="Directory %s already exists. Pulling updates from GitHub..."
        TEXTS[config_creating]="Creating configuration files..."
        TEXTS[config_done]="Configuration files created. Don't forget to edit them!"
        TEXTS[venv_creating]="Creating Python virtual environment..."
        TEXTS[req_installing]="Installing Python dependencies..."
        TEXTS[systemd_setup]="Setting up systemd service for auto-start..."
        TEXTS[systemd_done]="Systemd service configured and started."
        TEXTS[install_complete]="==================================\n  Installation Complete!  \n=================================="
        TEXTS[edit_config]="IMPORTANT: Edit '%s/config.json' and '%s/servers.json' with your actual data."
        TEXTS[status_cmd]="To check the bot's status, run: sudo systemctl status humanode_bot"
        TEXTS[logs_cmd]="To view the logs, run: sudo journalctl -u humanode_bot -f"
        TEXTS[start_cmd]="To (re)start the bot after editing the config: sudo systemctl restart humanode_bot"
    fi
}

# --- Helper Functions ---
info() { echo -e "\033[0;34mINFO:\033[0m $1"; }
success() { echo -e "\033[0;32mSUCCESS:\033[0m $1"; }
error() { echo -e "\033[0;31mERROR:\033[0m $1" >&2; exit 1; }
warning() { echo -e "\033[0;33mWARN:\033[0m $1"; }

# --- Main Logic ---
pre_flight_checks() {
    if [[ "$EUID" -ne 0 ]]; then
        error "${TEXTS[root_needed]}"
    fi
    SUDO_CMD="" # We are already root

    info "${TEXTS[dep_check]}"
    if command -v apt-get &> /dev/null; then
        apt-get update > /dev/null
        apt-get install -y git python3 python3-venv curl tesseract-ocr > /dev/null
    elif command -v dnf &> /dev/null; then
        dnf install -y git python3 python3-virtualenv curl tesseract > /dev/null
    elif command -v pacman &> /dev/null; then
        pacman -Syu --noconfirm git python python-virtualenv curl tesseract > /dev/null
    else
        warning "Unsupported package manager. Please install dependencies manually: git, python3, python3-venv, curl, tesseract-ocr"
    fi
    success "${TEXTS[dep_ok]}"
}

setup_directories_and_repo() {
    INSTALL_DIR="/opt/humanode-bot"
    BOT_DIR="$INSTALL_DIR/bot"
    VENV_DIR="$INSTALL_DIR/venv"
    local repo_url="https://github.com/stalkerSumy/humanode-telegram-bot.git"

    if [ -d "$INSTALL_DIR/.git" ]; then
        info "$(printf "${TEXTS[repo_exists]}" "$INSTALL_DIR")"
        cd "$INSTALL_DIR"
        git pull
    else
        info "$(printf "${TEXTS[cloning_repo]}" "$INSTALL_DIR")"
        mkdir -p "$INSTALL_DIR"
        git clone "$repo_url" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
}

setup_configuration() {
    info "${TEXTS[config_creating]}"
    if [ ! -f "$BOT_DIR/config.json" ]; then
        cp "$INSTALL_DIR/config.json.example" "$BOT_DIR/config.json"
    fi
    if [ ! -f "$BOT_DIR/servers.json" ]; then
        echo "{}" > "$BOT_DIR/servers.json"
    fi
    success "${TEXTS[config_done]}"
}

setup_python_venv() {
    info "${TEXTS[venv_creating]}"
    python3 -m venv "$VENV_DIR"
    info "${TEXTS[req_installing]}"
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" > /dev/null
}

setup_systemd() {
    info "${TEXTS[systemd_setup]}"
    local service_file_template="$INSTALL_DIR/systemd/humanode_bot.service.template"
    local service_file_dest="/etc/systemd/system/humanode_bot.service"

    # Determine user to run as. If script is run with sudo, SUDO_USER is the original user.
    OWNER_USER="${SUDO_USER:-$(whoami)}"
    OWNER_GROUP=$(id -gn "$OWNER_USER")

    # Set ownership of the entire directory
    chown -R "$OWNER_USER:$OWNER_GROUP" "$INSTALL_DIR"

    local exec_start_path="$VENV_DIR/bin/python3 $BOT_DIR/humanode_bot.py"

    # Create service file from template
    sed -e "s|{{USER}}|$OWNER_USER|g" \
        -e "s|{{GROUP}}|$OWNER_GROUP|g" \
        -e "s|{{WORKING_DIRECTORY}}|$BOT_DIR|g" \
        -e "s|{{EXEC_START}}|$exec_start_path|g" \
        "$service_file_template" > "$service_file_dest"

    systemctl daemon-reload
    systemctl enable humanode_bot.service
    systemctl start humanode_bot.service
    success "${TEXTS[systemd_done]}"
}

print_final_instructions() {
    echo -e "\n\033[1;32m${TEXTS[install_complete]}\033[0m\n"
    warning "$(printf "${TEXTS[edit_config]}" "$BOT_DIR" "$BOT_DIR")"
    info "${TEXTS[start_cmd]}"
    info "${TEXTS[status_cmd]}"
    info "${TEXTS[logs_cmd]}"
}

main() {
    read -p "Виберіть мову / Select language (ua/en) [en]: " lang
    lang=${lang:-en}
    setup_texts "$lang"
    
    echo -e "\n\033[1;34m${TEXTS[welcome]}\033[0m\n"

    pre_flight_checks
    setup_directories_and_repo
    setup_configuration
    setup_python_venv
    setup_systemd
    print_final_instructions
}

# --- Run main function ---
main
