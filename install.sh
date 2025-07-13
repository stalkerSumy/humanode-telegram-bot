#!/bin/bash

# Humanode Management Bot Interactive Installer
# This script downloads the bot from GitHub, and guides the user through installation.

# --- Configuration ---
REPO_URL="https://github.com/stalkerSumy/humanode-telegram-bot.git"

# --- Colors for output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_YELLOW='\033[0;33m'

# --- Helper Functions ---
info() {
    echo -e "${C_BLUE}INFO:${C_RESET} $1"
}

success() {
    echo -e "${C_GREEN}SUCCESS:${C_RESET} $1"
}

error() {
    echo -e "${C_RED}ERROR:${C_RESET} $1" >&2
    exit 1
}

warning() {
    echo -e "${C_YELLOW}WARNING:${C_RESET} $1"
}

# --- Pre-flight Checks ---
check_dependencies() {
    info "Checking for required dependencies..."
    local missing_deps=()
    local deps=("git" "python3" "python3-venv" "jq" "curl")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            missing_deps+=("$dep")
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        error "The following dependencies are missing: ${missing_deps[*]}. Please install them using your package manager (e.g., 'sudo apt update && sudo apt install ${missing_deps[*]}')."
    fi
    success "All dependencies are installed."
}

# --- Main Installation Logic ---
main() {
    echo -e "${C_BLUE}===============================================${C_RESET}"
    echo -e "${C_BLUE} Welcome to the Humanode Management Bot Installer ${C_RESET}"
    echo -e "${C_BLUE}===============================================${C_RESET}"
    echo

    check_dependencies

    # 1. Get Installation Directory
    read -p "Enter the installation directory [default: /opt/humanode-bot]: " INSTALL_DIR
    INSTALL_DIR=${INSTALL_DIR:-/opt/humanode-bot}

    # Check if running as root, if not, prepend sudo for directory creation
    if [ "$EUID" -ne 0 ]; then
        SUDO_CMD="sudo"
    else
        SUDO_CMD=""
    fi
    
    # 2. Clone or Update Repository
    if [ -d "$INSTALL_DIR" ]; then
        info "Directory $INSTALL_DIR already exists."
        read -p "Do you want to overwrite or update it? (y/n): " OVERWRITE
        if [[ "$OVERWRITE" == "y" ]]; then
            if [ -d "$INSTALL_DIR/.git" ]; then
                info "Existing installation found. Updating from GitHub..."
                cd "$INSTALL_DIR" || exit 1
                git pull origin main --ff-only || git pull origin master --ff-only || error "Failed to pull updates from GitHub."
            else
                info "Directory is not a git repository. Removing and re-cloning."
                $SUDO_CMD rm -rf "$INSTALL_DIR"
                git clone "$REPO_URL" "$INSTALL_DIR" || error "Failed to clone repository."
            fi
        else
            info "Using existing directory. Note: This might cause issues if it's not a valid installation."
        fi
    else
        info "Cloning repository into $INSTALL_DIR..."
        $SUDO_CMD mkdir -p "$INSTALL_DIR" || error "Failed to create directory. Please check permissions."
        $SUDO_CMD chown -R "$(whoami):$(whoami)" "$INSTALL_DIR" || warning "Could not change ownership of $INSTALL_DIR."
        git clone "$REPO_URL" "$INSTALL_DIR" || error "Failed to clone repository."
    fi
    
    cd "$INSTALL_DIR" || error "Could not change to installation directory $INSTALL_DIR"

    # 3. Gather Configuration
    info "Starting interactive configuration..."
    CONFIG_FILE="${INSTALL_DIR}/config.json"
    
    read -sp "Enter your Telegram Bot Token: " TELEGRAM_BOT_TOKEN
    echo
    read -p "Enter your authorized Telegram User ID: " AUTHORIZED_USER_ID
    read -p "Enter default language (e.g., en, uk) [default: en]: " DEFAULT_LANGUAGE
    DEFAULT_LANGUAGE=${DEFAULT_LANGUAGE:-en}

    # Initialize config with basic info
    JSON_CONFIG=$(jq -n \
                  --arg token "$TELEGRAM_BOT_TOKEN" \
                  --arg user_id "$AUTHORIZED_USER_ID" \
                  --arg lang "$DEFAULT_LANGUAGE" \
                  '{telegram_bot_token: $token, authorized_user_id: ($user_id | tonumber), default_language: $lang, servers: {}}')

    # Loop to add servers
    while true; do
        read -p "Do you want to add a server? (y/n): " ADD_SERVER
        if [[ "$ADD_SERVER" != "y" ]]; then
            break
        fi

        read -p "Enter a unique ID for the server (e.g., my_vps1): " SERVER_ID
        read -p "Enter a friendly name for the server (e.g., 'My Main Node'): " SERVER_NAME
        read -p "Is this server the local machine where the bot is running? (y/n): " IS_LOCAL_RAW
        
        if [[ "$IS_LOCAL_RAW" == "y" ]]; then
            IS_LOCAL="true"
            SERVER_IP="127.0.0.1"
            SERVER_USER="root" # Placeholder
            KEY_PATH=""      # Placeholder
        else
            IS_LOCAL="false"
            read -p "Enter server IP address or hostname: " SERVER_IP
            read -p "Enter SSH user [default: root]: " SERVER_USER
            SERVER_USER=${SERVER_USER:-root}
            read -p "Enter the absolute path to the SSH private key (e.g., /root/.ssh/id_rsa): " KEY_PATH
        fi

        # Add server to JSON config
        JSON_CONFIG=$(echo "$JSON_CONFIG" | jq \
            --arg id "$SERVER_ID" \
            --arg name "$SERVER_NAME" \
            --arg ip "$SERVER_IP" \
            --arg user "$SERVER_USER" \
            --arg key_path "$KEY_PATH" \
            --argjson is_local "$IS_LOCAL" \
            '.servers[$id] = {name: $name, ip: $ip, user: $user, key_path: $key_path, is_local: $is_local}')
    done

    # Write the config file
    info "Generating config.json..."
    echo "$JSON_CONFIG" | jq '.' > "$CONFIG_FILE" || error "Failed to create config.json."
    success "Configuration file created at $CONFIG_FILE"

    # 4. Setup Python Environment
    VENV_DIR="${INSTALL_DIR}/venv"
    info "Creating Python virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || error "Failed to create virtual environment."
    
    info "Installing Python dependencies..."
    source "${VENV_DIR}/bin/activate"
    pip install -r "${INSTALL_DIR}/requirements.txt" || error "Failed to install Python dependencies."
    deactivate
    success "Python environment is ready."

    # 5. Setup systemd Service
    info "Setting up systemd service..."
    BOT_SERVICE_TEMPLATE="${INSTALL_DIR}/systemd/humanode-bot.service.template"
    BOT_SERVICE_FILE="/etc/systemd/system/humanode-bot.service"

    if [ ! -f "$BOT_SERVICE_TEMPLATE" ]; then
        error "Service template not found at $BOT_SERVICE_TEMPLATE"
    fi

    $SUDO_CMD cp "$BOT_SERVICE_TEMPLATE" "$BOT_SERVICE_FILE"
    $SUDO_CMD sed -i "s|__WORKING_DIR__|${INSTALL_DIR}/bot|g" "$BOT_SERVICE_FILE"
    $SUDO_CMD sed -i "s|__VENV_PATH__|${VENV_DIR}|g" "$BOT_SERVICE_FILE"
    
    info "Reloading systemd daemon and starting the bot service..."
    $SUDO_CMD systemctl daemon-reload
    $SUDO_CMD systemctl enable humanode-bot.service
    $SUDO_CMD systemctl restart humanode-bot.service
    
    echo
    echo -e "${C_GREEN}=====================================${C_RESET}"
    echo -e "${C_GREEN}  Installation Complete!             ${C_RESET}"
    echo -e "${C_GREEN}=====================================${C_RESET}"
    echo
    info "You can check the bot's status with: ${C_YELLOW}sudo systemctl status humanode-bot.service${C_RESET}"
    info "You can view the logs with: ${C_YELLOW}sudo journalctl -u humanode-bot.service -f${C_RESET}"
    info "To start a conversation with your bot, find it on Telegram and send the /menu command."
}

# Run the main function
main
