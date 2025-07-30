#!/bin/bash

# Humanode Bot Universal Installer
# Installs and configures the Humanode management bot.
# Supports interactive installation with language selection.

# --- Stop on any error ---
set -e

# --- Language Strings ---
# Will be populated after user selection
declare -A TEXTS

setup_texts() {
    local lang=$1
    if [[ "$lang" == "ua" ]]; then
        TEXTS[welcome]="=================================================\n Вітаємо в інсталяторі Humanode Management Bot \n================================================="
        TEXTS[dep_check]="Перевірка необхідних залежностей..."
        TEXTS[dep_missing]="Відсутні наступні залежності: %s."
        TEXTS[dep_install_prompt]="Скрипт може спробувати встановити їх автоматично. Продовжити? (y/n): "
        TEXTS[dep_installing]="Встановлюю відсутні залежності..."
        TEXTS[dep_manual_install]="Будь ласка, встановіть їх вручну (напр., 'sudo apt update && sudo apt install -y %s')."
        TEXTS[dep_ok]="Усі залежності встановлено."
        TEXTS[install_dir_prompt]="Введіть директорію для встановлення [за замовчуванням: /opt/humanode-bot]: "
        TEXTS[sudo_needed]="Для встановлення в %s потрібні права адміністратора (sudo)."
        TEXTS[cloning_repo]="Клоную репозиторій в %s..."
        TEXTS[repo_exists]="Директорія %s вже існує. Оновлюю з GitHub..."
        TEXTS[config_start]="Починаю інтерактивне налаштування..."
        TEXTS[token_prompt]="Введіть ваш Telegram Bot Token: "
        TEXTS[user_id_prompt]="Введіть ваш авторизований Telegram User ID: "
        TEXTS[github_token_prompt]="Введіть ваш токен GitHub для доступу до приватних репозиторіїв (необов'язково, можна пропустити): "
        TEXTS[input_empty_error]="Поле не може бути порожнім."
        TEXTS[add_server_prompt]="Хочете додати сервер для моніторингу? (y/n): "
        TEXTS[server_id_prompt]="Введіть унікальний ID для сервера (латиницею, без пробілів, напр., my_vps1): "
        TEXTS[server_name_prompt]="Введіть ім'я сервера для відображення (напр., 'Мій головний вузол'): "
        TEXTS[is_local_prompt]="Цей сервер - локальна машина, де запущено бота? (y/n): "
        TEXTS[server_ip_prompt]="Введіть IP адресу або хост SSH сервера: "
        TEXTS[server_user_prompt]="Введіть користувача SSH [за замовчуванням: root]: "
        TEXTS[key_path_prompt]="Введіть АБСОЛЮТНИЙ шлях до приватного ключа SSH (напр., /root/.ssh/id_rsa): "
        TEXTS[config_creating]="Створюю файл конфігурації config.json..."
        TEXTS[config_done]="Файл конфігурації успішно створено."
        TEXTS[venv_creating]="Створюю віртуальне оточення Python..."
        TEXTS[venv_done]="Віртуальне оточення готове."
        TEXTS[req_installing]="Встановлюю залежності Python з requirements.txt..."
        TEXTS[req_done]="Залежності Python встановлено."
        TEXTS[systemd_setup]="Налаштовую службу systemd для автозапуску..."
        TEXTS[systemd_done]="Службу systemd налаштовано."
        TEXTS[install_complete]="=================================\n  Встановлення завершено!  \n================================="
        TEXTS[status_cmd]="Щоб перевірити статус бота, виконайте: sudo systemctl status humanode-bot"
        TEXTS[logs_cmd]="Щоб переглянути логи, виконайте: sudo journalctl -u humanode-bot -f"
        TEXTS[start_convo]="Щоб почати розмову з ботом, знайдіть його в Telegram і надішліть команду /start."
    else # English
        TEXTS[welcome]="==============================================\n Welcome to the Humanode Management Bot Installer \n=============================================="
        TEXTS[dep_check]="Checking for required dependencies..."
        TEXTS[dep_missing]="The following dependencies are missing: %s."
        TEXTS[dep_install_prompt]="The script can attempt to install them automatically. Proceed? (y/n): "
        TEXTS[dep_installing]="Installing missing dependencies..."
        TEXTS[dep_manual_install]="Please install them manually (e.g., 'sudo apt update && sudo apt install -y %s')."
        TEXTS[dep_ok]="All dependencies are installed."
        TEXTS[install_dir_prompt]="Enter the installation directory [default: /opt/humanode-bot]: "
        TEXTS[sudo_needed]="Administrator privileges (sudo) are required to install to %s."
        TEXTS[cloning_repo]="Cloning repository into %s..."
        TEXTS[repo_exists]="Directory %s already exists. Pulling updates from GitHub..."
        TEXTS[config_start]="Starting interactive configuration..."
        TEXTS[token_prompt]="Enter your Telegram Bot Token: "
        TEXTS[user_id_prompt]="Enter your authorized Telegram User ID: "
        TEXTS[github_token_prompt]="Enter your GitHub token for private repo access (optional, press Enter to skip): "
        TEXTS[input_empty_error]="Input cannot be empty."
        TEXTS[add_server_prompt]="Do you want to add a server to monitor? (y/n): "
        TEXTS[server_id_prompt]="Enter a unique ID for the server (latin chars, no spaces, e.g., my_vps1): "
        TEXTS[server_name_prompt]="Enter a friendly name for the server (e.g., 'My Main Node'): "
        TEXTS[is_local_prompt]="Is this server the local machine where the bot is running? (y/n): "
        TEXTS[server_ip_prompt]="Enter the server's SSH IP address or hostname: "
        TEXTS[server_user_prompt]="Enter the SSH user [default: root]: "
        TEXTS[key_path_prompt]="Enter the ABSOLUTE path to the SSH private key (e.g., /root/.ssh/id_rsa): "
        TEXTS[config_creating]="Generating config.json file..."
        TEXTS[config_done]="Configuration file created successfully."
        TEXTS[venv_creating]="Creating Python virtual environment..."
        TEXTS[venv_done]="Virtual environment is ready."
        TEXTS[req_installing]="Installing Python dependencies from requirements.txt..."
        TEXTS[req_done]="Python dependencies installed."
        TEXTS[systemd_setup]="Setting up systemd service for auto-start..."
        TEXTS[systemd_done]="Systemd service configured."
        TEXTS[install_complete]="==================================\n  Installation Complete!  \n=================================="
        TEXTS[status_cmd]="To check the bot's status, run: sudo systemctl status humanode-bot"
        TEXTS[logs_cmd]="To view the logs, run: sudo journalctl -u humanode-bot -f"
        TEXTS[start_convo]="To start a conversation with your bot, find it on Telegram and send the /start command."
    fi
}

# --- Helper Functions ---
info() { echo -e "\033[0;34mINFO:\033[0m $1"; }
success() { echo -e "\033[0;32mSUCCESS:\033[0m $1"; }
error() { echo -e "\033[0;31mERROR:\033[0m $1" >&2; exit 1; }
prompt_for_input() {
    local prompt_text="$1"
    local var_name="$2"
    local is_secret="${3:-false}"
    local input_value
    while true; do
        if [ "$is_secret" = true ]; then
            read -sp "$prompt_text" input_value
            echo
        else
            read -p "$prompt_text" input_value
        fi
        if [ -n "$input_value" ]; then
            eval "$var_name=\"$input_value\""
            break
        else
            info "${TEXTS[input_empty_error]}"
        fi
    done
}

# --- Main Logic ---
main() {
    # 1. Language Selection
    read -p "Виберіть мову / Select language (ua/en) [en]: " lang
    lang=${lang:-en}
    setup_texts "$lang"
    
    echo -e "\n\033[1;34m${TEXTS[welcome]}\033[0m\n"

    # 2. Pre-flight Checks
    info "${TEXTS[dep_check]}"
    local missing_deps=()
    local deps=("git" "python3" "python3-venv" "jq" "curl" "tesseract-ocr")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            missing_deps+=("$dep")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        local missing_str="${missing_deps[*]}"
        printf -v msg "${TEXTS[dep_missing]}" "$missing_str"
        info "$msg"
        if command -v apt-get &> /dev/null; then
            read -p "${TEXTS[dep_install_prompt]}" -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                info "${TEXTS[dep_installing]}"
                sudo apt-get update
                sudo apt-get install -y "${missing_deps[@]}"
            else
                error "Встановлення скасовано користувачем. / Installation cancelled by user."
            fi
        else
            printf -v manual_install_msg "${TEXTS[dep_manual_install]}" "$missing_str"
            error "Не вдалося знайти 'apt-get'. $manual_install_msg / Could not find 'apt-get'. $manual_install_msg"
        fi
    fi
    success "${TEXTS[dep_ok]}"

    # 3. Get Installation Directory
    read -p "${TEXTS[install_dir_prompt]}" INSTALL_DIR
    INSTALL_DIR=${INSTALL_DIR:-/opt/humanode-bot}
    
    # Convert to absolute path
    INSTALL_DIR=$(readlink -f "$INSTALL_DIR")

    # Check if sudo is needed and available
    if [[ ! -w "$(dirname "$INSTALL_DIR")" ]] && [[ "$EUID" -ne 0 ]]; then
        info "$(printf "${TEXTS[sudo_needed]}" "$INSTALL_DIR")"
        if ! command -v sudo &> /dev/null; then
            error "sudo command not found, but required to install in $INSTALL_DIR"
        fi
        SUDO_CMD="sudo"
    fi

    # 4. Clone or Update Repository
    local repo_url="https://github.com/stalkerSumy/humanode-telegram-bot.git"

    if [ -d "$INSTALL_DIR" ]; then
        info "$(printf "${TEXTS[repo_exists]}" "$INSTALL_DIR")"
        cd "$INSTALL_DIR"
        $SUDO_CMD git remote set-url origin "$repo_url"
        $SUDO_CMD env GIT_TERMINAL_PROMPT=0 git pull
    else
        info "$(printf "${TEXTS[cloning_repo]}" "$INSTALL_DIR")"
        $SUDO_CMD mkdir -p "$INSTALL_DIR"
        local tmp_dir; tmp_dir=$(mktemp -d)
        env GIT_TERMINAL_PROMPT=0 git clone "$repo_url" "$tmp_dir"
        $SUDO_CMD rsync -a "$tmp_dir/" "$INSTALL_DIR/"
        rm -rf "$tmp_dir"
    fi
    cd "$INSTALL_DIR"

    # 5. Gather Configuration
    info "${TEXTS[config_start]}"
    local bot_dir="$INSTALL_DIR/bot"
    local config_file="$bot_dir/config.json"
    local servers_file="$bot_dir/servers.json"
    
    prompt_for_input "${TEXTS[token_prompt]}" token true
    prompt_for_input "${TEXTS[user_id_prompt]}" user_id
    read -p "${TEXTS[github_token_prompt]}" github_token

    local json_config
    json_config=$(jq -n \
                  --arg token "$token" \
                  --arg user_id "$user_id" \
                  --arg github_token "$github_token" \
                  '{
                      "telegram_bot_token": $token, \
                      "authorized_user_id": ($user_id | tonumber),\n                      "github_token": $github_token
                   }')

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

    info "${TEXTS[config_creating]}"
    echo "$json_config" | jq '.' | $SUDO_CMD tee "$config_file" > /dev/null
    echo "$servers_config" | jq '.' | $SUDO_CMD tee "$servers_file" > /dev/null
    success "${TEXTS[config_done]}"

    # 6. Setup Python Environment
    local venv_dir="$INSTALL_DIR/venv"
    info "${TEXTS[venv_creating]}"
    $SUDO_CMD python3 -m venv "$venv_dir"
    
    info "${TEXTS[req_installing]}"
    $SUDO_CMD "$venv_dir/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    success "${TEXTS[req_done]}"

    # 7. Set ownership
    if [ -n "$SUDO_CMD" ]; then
        $SUDO_CMD chown -R "$(whoami):$(id -gn)" "$INSTALL_DIR"
    fi

    # 8. Setup systemd Service
    info "${TEXTS[systemd_setup]}"
    local service_file="/etc/systemd/system/humanode-bot.service"
    
    $SUDO_CMD bash -c "cat > $service_file" << EOL
[Unit]
Description=Humanode Management Bot
After=network.target

[Service]
User=$(whoami)
Group=$(id -gn)
WorkingDirectory=$bot_dir
ExecStart=$venv_dir/bin/python3 $bot_dir/humanode_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

    $SUDO_CMD systemctl daemon-reload
    $SUDO_CMD systemctl enable humanode-bot.service
    $SUDO_CMD systemctl restart humanode-bot.service
    success "${TEXTS[systemd_done]}"

    # 9. Final instructions
    echo -e "\n\033[1;32m${TEXTS[install_complete]}\033[0m\n"
    info "${TEXTS[status_cmd]}"
    info "${TEXTS[logs_cmd]}"
    info "${TEXTS[start_convo]}"
}

# --- Run main function ---
main