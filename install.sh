#!/bin/bash

# Кольори для виводу
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Функція для виводу ---
info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# --- Початок скрипта ---
info "Welcome to the Humanode Bot Installer!"
info "This script will guide you through the setup process."
echo

# --- 1. Перевірка залежностей ---
info "Step 1: Checking dependencies..."
command -v python3 >/dev/null 2>&1 || { error "Python 3 is not installed. Please install it and run this script again."; exit 1; }
command -v pip >/dev/null 2>&1 || { error "pip is not installed. Please install it and run this script again."; exit 1; }
info "All dependencies are present."
echo

# --- 2. Збір даних для конфігурації ---
info "Step 2: Configuring the bot. Please answer the following questions."

read -p "Enter your Telegram Bot Token: " TELEGRAM_BOT_TOKEN
read -p "Enter your authorized Telegram User ID: " AUTHORIZED_USER_ID
read -p "Enter default language (uk/en) [en]: " DEFAULT_LANGUAGE
DEFAULT_LANGUAGE=${DEFAULT_LANGUAGE:-en}

# --- Створення JSON ---
CONFIG_JSON="{\n"
CONFIG_JSON+="  \"telegram_bot_token\": \"$TELEGRAM_BOT_TOKEN\",\n"
CONFIG_JSON+="  \"authorized_user_id\": $AUTHORIZED_USER_ID,\n"
CONFIG_JSON+="  \"default_language\": \"$DEFAULT_LANGUAGE\",\n"
CONFIG_JSON+="  \"servers\": {\n"

# --- 3. Налаштування серверів ---
server_list=""
read -p "Is a Humanode node running on this same machine? (y/n) [y]: " IS_LOCAL_NODE
IS_LOCAL_NODE=${IS_LOCAL_NODE:-y}

if [[ "$IS_LOCAL_NODE" == "y" ]]; then
    info "Configuring local node..."
    read -p "Enter the username that runs the node commands (e.g., root): " LOCAL_USER
    
    server_list+="    \"local_node\": {\n"
    server_list+="      \"name\": \"Local Node\",\n"
    server_list+="      \"ip\": \"127.0.0.1\",\n"
    server_list+="      \"user\": \"$LOCAL_USER\",\n"
    server_list+="      \"key_path\": null,\n"
    server_list+="      \"is_local\": true\n"
    server_list+="    }"
fi

while true; do
    read -p "Do you want to add a remote server to manage? (y/n) [n]: " ADD_REMOTE
    ADD_REMOTE=${ADD_REMOTE:-n}
    if [[ "$ADD_REMOTE" != "y" ]]; then
        break
    fi
    
    if [ -n "$server_list" ]; then
        server_list+=",\n"
    fi

    info "Configuring a new remote server..."
    read -p "Enter a unique ID for the server (e.g., my_vps): " SERVER_ID
    read -p "Enter a display name for the server (e.g., My Awesome VPS): " SERVER_NAME
    read -p "Enter the server's IP address: " SERVER_IP
    read -p "Enter the SSH username (e.g., root): " SERVER_USER
    read -p "Enter the absolute path to the SSH private key (e.g., /root/.ssh/id_rsa): " SERVER_KEY_PATH
    
    server_list+="    \"$SERVER_ID\": {\n"
    server_list+="      \"name\": \"$SERVER_NAME\",\n"
    server_list+="      \"ip\": \"$SERVER_IP\",\n"
    server_list+="      \"user\": \"$SERVER_USER\",\n"
    server_list+="      \"key_path\": \"$SERVER_KEY_PATH\",\n"
    server_list+="      \"is_local\": false\n"
    server_list+="    }"
done

CONFIG_JSON+="$server_list\n"
CONFIG_JSON+="  }\n"
CONFIG_JSON+="}\n"

# Запис конфігурації у файл
echo -e "$CONFIG_JSON" > config.json
info "Configuration file 'config.json' created successfully."
echo

# --- 4. Налаштування Python середовища ---
info "Step 3: Setting up Python virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    error "Failed to create Python virtual environment."
    exit 1
fi

source venv/bin/activate
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    error "Failed to install Python dependencies."
    exit 1
fi
deactivate
info "Python environment is ready."
echo

# --- 5. Налаштування Systemd сервісу ---
info "Step 4: Setting up systemd service..."
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
VENV_PYTHON_PATH="$SCRIPT_DIR/venv/bin/python3"
SERVICE_FILE_PATH="/etc/systemd/system/humanode-bot.service"

# Створення конфігурації сервісу з шаблону
SERVICE_CONFIG=$(cat systemd/humanode-bot.service.template)
SERVICE_CONFIG=${SERVICE_CONFIG//__WORKING_DIR__/$SCRIPT_DIR}
SERVICE_CONFIG=${SERVICE_CONFIG//__VENV_PATH__/$VENV_PYTHON_PATH}

echo "The script needs sudo access to install the systemd service."
echo -e "$SERVICE_CONFIG" | sudo tee $SERVICE_FILE_PATH > /dev/null
if [ $? -ne 0 ]; then
    error "Failed to write systemd service file. Please run this script with a user that has sudo privileges."
    exit 1
fi

info "Reloading systemd daemon..."
sudo systemctl daemon-reload

info "Enabling and starting the bot service..."
sudo systemctl enable humanode-bot.service
sudo systemctl start humanode-bot.service

# --- Завершення ---
echo
info "-------------------------------------------------"
info "Installation complete!"
info "The bot is now running as a background service."
echo
info "You can check the bot's status with:"
warn "sudo systemctl status humanode-bot.service"
echo
info "You can view the logs with:"
warn "sudo journalctl -u humanode-bot.service -f"
info "-------------------------------------------------"

exit 0