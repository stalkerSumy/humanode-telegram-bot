#!/bin/bash

# Humanode Bot Universal Installer v3.3
# An interactive script that automates the entire setup process,
# including the creation of systemd services for the node and tunnel using project-specific templates.

# --- Stop on any error ---
set -e

# --- Global Variables ---
INSTALL_DIR="/opt/humanode-bot"
BOT_DIR="$INSTALL_DIR/bot"
VENV_DIR="$INSTALL_DIR/venv"
SYSTEMD_DIR="$INSTALL_DIR/systemd"

# --- Language Strings ---
declare -A TEXTS

setup_texts() {
    local lang=$1
    if [[ "$lang" == "ua" ]]; then
        TEXTS[welcome]="=================================================\n Вітаємо в інсталяторі Humanode Management Bot v3.3 \n================================================="
        TEXTS[root_needed]="Для коректної роботи інсталятора потрібні права адміністратора. Будь ласка, запустіть його через 'sudo'."
        TEXTS[dep_check]="Перевірка та встановлення системних залежностей..."
        TEXTS[dep_ok]="Системні залежності встановлено."
        TEXTS[chrome_check]="Встановлюю Google Chrome для Selenium..."
        TEXTS[chrome_ok]="Google Chrome встановлено."
        TEXTS[cloning_repo]="Клоную репозиторій в $INSTALL_DIR..."
        TEXTS[repo_exists]="Директорія $INSTALL_DIR вже існує. Оновлюю з GitHub..."
        TEXTS[config_start]="Починаю інтерактивне налаштування..."
        TEXTS[token_prompt]="Введіть ваш Telegram Bot Token: "
        TEXTS[user_id_prompt]="Введіть ваш авторизований Telegram User ID: "
        TEXTS[github_token_prompt]="Введіть ваш токен GitHub (необов'язково, можна пропустити): "
        TEXTS[input_empty_error]="Поле не може бути порожнім."
        TEXTS[add_server_prompt]="Хочете додати сервер для моніторингу? (y/n): "
        TEXTS[server_id_prompt]="Введіть унікальний ID для сервера (латиницею, без пробілів, напр., my_vps1): "
        TEXTS[server_name_prompt]="Введіть ім'я сервера для відображення (напр., 'Мій головний вузол'): "
        TEXTS[is_local_prompt]="Цей сервер - локальна машина, де запущено бота? (y/n): "
        TEXTS[server_ip_prompt]="Введіть IP адресу або хост SSH сервера: "
        TEXTS[server_user_prompt]="Введіть користувача SSH [за замовчуванням: root]: "
        TEXTS[key_path_prompt]="Введіть АБСОЛЮТНИЙ шлях до приватного ключа SSH (напр., /root/.ssh/id_rsa): "
        TEXTS[config_creating]="Генерую файли конфігурації..."
        TEXTS[config_done]="Файли конфігурації успішно створено."
        TEXTS[venv_creating]="Створюю віртуальне оточення Python..."
        TEXTS[req_installing]="Встановлюю залежності Python..."
        TEXTS[systemd_setup]="Налаштовую службу systemd для автозапуску бота..."
        TEXTS[systemd_done]="Службу бота налаштовано та запущено."
        TEXTS[node_services_setup]="Налаштування сервісів для ноди та тунелю за допомогою шаблонів..."
        TEXTS[node_name_prompt]="Введіть унікальне ім'я для вашої ноди (без пробілів, напр., MySuperNode): "
        TEXTS[node_service_creating]="Створюю сервіс 'humanode-peer.service'..."
        TEXTS[tunnel_service_creating]="Створюю сервіс 'humanode-websocket-tunnel.service'..."
        TEXTS[services_enabled]="Сервіси ноди та тунелю увімкнено для автозапуску."
        TEXTS[install_complete]="=================================\n  Встановлення завершено!  \n================================="
        TEXTS[status_cmd]="Щоб перевірити статус бота, виконайте: sudo systemctl status humanode_bot"
        TEXTS[logs_cmd]="Щоб переглянути логи, виконайте: sudo journalctl -u humanode_bot -f"
        TEXTS[start_convo]="Знайдіть вашого бота в Telegram і надішліть команду /start, щоб почати керувати вашими нодами."
    else # English
        TEXTS[welcome]="==============================================\n Welcome to the Humanode Management Bot Installer v3.3 \n============================================="
        TEXTS[root_needed]="This installer requires root privileges to run correctly. Please execute it with 'sudo'."
        TEXTS[dep_check]="Checking and installing system dependencies..."
        TEXTS[dep_ok]="System dependencies are installed."
        TEXTS[chrome_check]="Installing Google Chrome for Selenium..."
        TEXTS[chrome_ok]="Google Chrome is installed."
        TEXTS[cloning_repo]="Cloning repository into $INSTALL_DIR..."
        TEXTS[repo_exists]="Directory $INSTALL_DIR already exists. Pulling updates from GitHub..."
        TEXTS[config_start]="Starting interactive configuration..."
        TEXTS[token_prompt]="Enter your Telegram Bot Token: "
        TEXTS[user_id_prompt]="Enter your authorized Telegram User ID: "
        TEXTS[github_token_prompt]="Enter your GitHub token (optional, press Enter to skip): "
        TEXTS[input_empty_error]="Input cannot be empty."
        TEXTS[add_server_prompt]="Do you want to add a server to monitor? (y/n): "
        TEXTS[server_id_prompt]="Enter a unique ID for the server (latin chars, no spaces, e.g., my_vps1): "
        TEXTS[server_name_prompt]="Enter a friendly name for the server (e.g., 'My Main Node'): "
        TEXTS[is_local_prompt]="Is this server the local machine where the bot is running? (y/n): "
        TEXTS[server_ip_prompt]="Enter the server's SSH IP address or hostname: "
        TEXTS[server_user_prompt]="Enter the SSH user [default: root]: "
        TEXTS[key_path_prompt]="Enter the ABSOLUTE path to the SSH private key (e.g., /root/.ssh/id_rsa): "
        TEXTS[config_creating]="Generating configuration files..."
        TEXTS[config_done]="Configuration files created successfully."
        TEXTS[venv_creating]="Creating Python virtual environment..."
        TEXTS[req_installing]="Installing Python dependencies..."
        TEXTS[systemd_setup]="Setting up systemd service for bot auto-start..."
        TEXTS[systemd_done]="Bot service configured and started."
        TEXTS[node_services_setup]="Setting up services for the Node and Tunnel using templates..."
        TEXTS[node_name_prompt]="Enter a unique name for your node (no spaces, e.g., MySuperNode): "
        TEXTS[node_service_creating]="Creating 'humanode-peer.service'..."
        TEXTS[tunnel_service_creating]="Creating 'humanode-websocket-tunnel.service'..."
        TEXTS[services_enabled]="Node and tunnel services have been enabled to start on boot."
        TEXTS[install_complete]="==================================\n  Installation Complete!  \n=================================="
        TEXTS[status_cmd]="To check the bot's status, run: sudo systemctl status humanode_bot"
        TEXTS[logs_cmd]="To view the logs, run: sudo journalctl -u humanode_bot -f"
        TEXTS[start_convo]="Find your bot on Telegram and send the /start command to begin managing your nodes."
    fi
}

# --- Helper Functions ---
info() { echo -e "\033[0;34mINFO:\033[0m $1"; }
success() { echo -e "\033[0;32mSUCCESS:\033[0m $1"; }
error() { echo -e "\033[0;31mERROR:\033[0m $1" >&2; exit 1; }
prompt_for_input() {
    local prompt_text="$1"
    local var_name="$2"
    local allow_empty="${3:-false}"
    local input_value
    while true; do
        read -p "$prompt_text" input_value
        if [ -n "$input_value" ] || [ "$allow_empty" = true ]; then
            eval "$var_name=\"$input_value\""; break
        else
            info "${TEXTS[input_empty_error]}"; fi
    done
}

# --- Installation Steps ---
pre_flight_checks() {
    if [[ "$EUID" -ne 0 ]]; then error "${TEXTS[root_needed]}"; fi
    info "${TEXTS[dep_check]}"
    apt-get update -y > /dev/null
    apt-get install -y git python3 python3-venv curl tesseract-ocr wget jq > /dev/null
    success "${TEXTS[dep_ok]}"

    info "${TEXTS[chrome_check]}"
    if ! command -v google-chrome-stable &> /dev/null; then
        wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
        apt-get install -y /tmp/chrome.deb > /dev/null
        rm /tmp/chrome.deb
    fi
    success "${TEXTS[chrome_ok]}"
}

setup_repo() {
    local repo_url="https://github.com/stalkerSumy/humanode-telegram-bot.git"
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "$(printf "${TEXTS[repo_exists]}" "$INSTALL_DIR")"
        cd "$INSTALL_DIR" && git pull
    else
        info "$(printf "${TEXTS[cloning_repo]}" "$INSTALL_DIR")"
        git clone "$repo_url" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
}

interactive_configuration() {
    info "${TEXTS[config_start]}"
    
    prompt_for_input "${TEXTS[token_prompt]}" token
    prompt_for_input "${TEXTS[user_id_prompt]}" user_id
    prompt_for_input "${TEXTS[github_token_prompt]}" github_token true

    jq -n \
      --arg token "$token" \
      --arg user_id "$user_id" \
      --arg github_token "$github_token" \
      '{telegram_bot_token: $token, authorized_user_id: ($user_id | tonumber), github_token: $github_token}' > "$BOT_DIR/config.json"

    local servers_config="{}"
    while true; do
        read -p "${TEXTS[add_server_prompt]}" add_server
        if [[ ! "$add_server" =~ ^[Yy]$ ]]; then break; fi

        prompt_for_input "${TEXTS[server_id_prompt]}" server_id
        prompt_for_input "${TEXTS[server_name_prompt]}" server_name
        read -p "${TEXTS[is_local_prompt]}" is_local_raw
        
        local is_local="false"; local ip="127.0.0.1"; local user="root"; local key_path=""
        if [[ "$is_local_raw" =~ ^[Yy]$ ]]; then
            is_local="true"
        else
            prompt_for_input "${TEXTS[server_ip_prompt]}" ip
            read -p "${TEXTS[server_user_prompt]}" user; user=${user:-root}
            prompt_for_input "${TEXTS[key_path_prompt]}" key_path
        fi

        servers_config=$(echo "$servers_config" | jq \
            --arg id "$server_id" --arg name "$server_name" --arg ip "$ip" --arg user "$user" \
            --arg key_path "$key_path" --argjson is_local "$is_local" \
            '.[$id] = {name: $name, ip: $ip, user: $user, key_path: $key_path, is_local: $is_local}')
    done
    echo "$servers_config" | jq '.' > "$BOT_DIR/servers.json"
    success "${TEXTS[config_done]}"
}

setup_environment() {
    info "${TEXTS[venv_creating]}"
    python3 -m venv "$VENV_DIR"
    info "${TEXTS[req_installing]}"
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" > /dev/null
}

setup_bot_systemd() {
    info "${TEXTS[systemd_setup]}"
    local owner_user="${SUDO_USER:-$(whoami)}"
    local owner_group=$(id -gn "$owner_user")
    chown -R "$owner_user:$owner_group" "$INSTALL_DIR"

    local exec_start_path="$VENV_DIR/bin/python3 $BOT_DIR/humanode_bot.py"
    sed -e "s|{{USER}}|$owner_user|g" \
        -e "s|{{GROUP}}|$owner_group|g" \
        -e "s|{{WORKING_DIRECTORY}}|$BOT_DIR|g" \
        -e "s|{{EXEC_START}}|$exec_start_path|g" \
        "$SYSTEMD_DIR/humanode_bot.service.template" > "/etc/systemd/system/humanode_bot.service"

    systemctl daemon-reload
    systemctl enable --now humanode_bot.service
    success "${TEXTS[systemd_done]}"
}

setup_node_services() {
    info "${TEXTS[node_services_setup]}"
    
    # 1. Prompt for Node Name
    prompt_for_input "${TEXTS[node_name_prompt]}" NODE_NAME

    # 2. Define paths
    local humanode_home="/root/.humanode/workspaces/default"
    local peer_binary_path="$humanode_home/humanode-peer"
    local tunnel_binary_path="$humanode_home/humanode-websocket-tunnel"
    local data_path="$humanode_home"
    local chainspec_path="/root/chainspec.json"

    # 3. Create humanode-peer.service from template
    info "${TEXTS[node_service_creating]}"
    sed -e "s|__HUMANODE_HOME__|$humanode_home|g" \
        -e "s|__HUMANODE_BINARY_PATH__|$peer_binary_path|g" \
        -e "s|__HUMANODE_DATA_PATH__|$data_path|g" \
        -e "s|__NODE_NAME__|$NODE_NAME|g" \
        -e "s|__CHAINSPEC_PATH__|$chainspec_path|g" \
        "$SYSTEMD_DIR/humanode-peer.service.template" > "/etc/systemd/system/humanode-peer.service"

    # 4. Create humanode-websocket-tunnel.service from template
    info "${TEXTS[tunnel_service_creating]}"
    sed -e "s|__HUMANODE_HOME__|$humanode_home|g" \
        -e "s|__HUMANODE_TUNNEL_BINARY_PATH__|$tunnel_binary_path|g" \
        "$SYSTEMD_DIR/humanode-websocket-tunnel.service.template" > "/etc/systemd/system/humanode-websocket-tunnel.service"

    # 5. Reload daemon and enable services
    systemctl daemon-reload
    systemctl enable humanode-peer.service
    systemctl enable humanode-websocket-tunnel.service
    success "${TEXTS[services_enabled]}"
}


# --- Main Execution ---
main() {
    read -p "Виберіть мову / Select language (ua/en) [en]: " lang; lang=${lang:-en}
    setup_texts "$lang"
    echo -e "\n\033[1;34m${TEXTS[welcome]}\033[0m\n"

    pre_flight_checks
    setup_repo
    interactive_configuration
    setup_environment
    setup_bot_systemd
    setup_node_services

    echo -e "\n\033[1;32m${TEXTS[install_complete]}\033[0m\n"
    info "${TEXTS[status_cmd]}"
    info "${TEXTS[logs_cmd]}"
    info "${TEXTS[start_convo]}"
}

main
