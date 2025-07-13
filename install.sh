#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

REPO_DIR="/root/humanode-bot-dist"
INSTALL_DIR="/opt/humanode-bot"
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_FILE="${INSTALL_DIR}/config.json"
LOG_FILE="${INSTALL_DIR}/humanode_bot.log"

echo "Starting Humanode Telegram Bot installation..."

# 1. Create installation directory
echo "Creating installation directory: ${INSTALL_DIR}"
sudo mkdir -p "${INSTALL_DIR}"
sudo chown -R $(whoami):$(whoami) "${INSTALL_DIR}"

# 2. Copy bot files
echo "Copying bot files to ${INSTALL_DIR}..."
cp -r "${REPO_DIR}/bot" "${INSTALL_DIR}/"
cp "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/"
cp "${REPO_DIR}/config.json.example" "${INSTALL_DIR}/"
cp -r "${REPO_DIR}/systemd" "${INSTALL_DIR}/"
cp "${REPO_DIR}/README.md" "${INSTALL_DIR}/"
cp "${REPO_DIR}/install.sh" "${INSTALL_DIR}/" # Copy itself for future updates

# 3. Create and activate virtual environment
echo "Creating Python virtual environment at ${VENV_DIR}..."
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# 4. Install Python dependencies
echo "Installing Python dependencies..."
pip install -r "${INSTALL_DIR}/requirements.txt"

# 5. Check for config.json, if not exists, create from example
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "config.json not found. Creating from config.json.example."
    cp "${INSTALL_DIR}/config.json.example" "${CONFIG_FILE}"
    echo "Please edit ${CONFIG_FILE} with your Telegram bot token, authorized user ID, and server configurations."
    echo "You can find the example configuration in ${INSTALL_DIR}/config.json.example."
    echo "Exiting installation. Please configure config.json and run install.sh again."
    exit 1
fi

# Load config.json to get server details for service file generation
echo "Loading configuration from ${CONFIG_FILE}..."
TELEGRAM_BOT_TOKEN=$(jq -r '.telegram_bot_token' "${CONFIG_FILE}")
AUTHORIZED_USER_ID=$(jq -r '.authorized_user_id' "${CONFIG_FILE}")
DEFAULT_LANGUAGE=$(jq -r '.default_language' "${CONFIG_FILE}")

# Check if jq is installed
if ! command -v jq &> /dev/null
then
    echo "jq is not installed. Please install it: sudo apt-get install jq"
    exit 1
fi

# 6. Generate systemd service files from templates
echo "Generating systemd service files..."

# Bot service
BOT_SERVICE_TEMPLATE="${INSTALL_DIR}/systemd/humanode-bot.service.template"
BOT_SERVICE_FILE="/etc/systemd/system/humanode-bot.service"
sudo cp "${BOT_SERVICE_TEMPLATE}" "${BOT_SERVICE_FILE}"
sudo sed -i "s|__WORKING_DIR__|${INSTALL_DIR}/bot|g" "${BOT_SERVICE_FILE}"
sudo sed -i "s|__VENV_PATH__|${VENV_DIR}|g" "${BOT_SERVICE_FILE}"
echo "Generated ${BOT_SERVICE_FILE}"

# Node and Tunnel services (iterate through servers in config.json)
# This part assumes that humanode-peer.service.template and humanode-websocket-tunnel.service.template
# will be used to generate service files for each server defined in config.json.
# For simplicity, I'll generate for a generic "humanode-peer" and "humanode-websocket-tunnel"
# service, assuming they are managed globally or that the user will adapt this.
# A more robust solution would generate per-server service files if needed.

# Get the first server ID from config.json
FIRST_SERVER_ID=$(jq -r '.servers | keys[0]' "${CONFIG_FILE}")
if [ -z "$FIRST_SERVER_ID" ] || [ "$FIRST_SERVER_ID" == "null" ]; then
    echo "No servers found in config.json. Skipping node and tunnel service generation."
else
    echo "Using configuration from server: ${FIRST_SERVER_ID} for generic service templates."
    HUMANODE_HOME=$(jq -r ".servers.${FIRST_SERVER_ID}.humanode_home" "${CONFIG_FILE}")
    HUMANODE_BINARY_PATH=$(jq -r ".servers.${FIRST_SERVER_ID}.humanode_binary_path" "${CONFIG_FILE}")
    HUMANODE_DATA_PATH=$(jq -r ".servers.${FIRST_SERVER_ID}.humanode_data_path" "${CONFIG_FILE}")
    CHAINSPEC_PATH=$(jq -r ".servers.${FIRST_SERVER_ID}.chainspec_path" "${CONFIG_FILE}")
    HUMANODE_TUNNEL_BINARY_PATH=$(jq -r ".servers.${FIRST_SERVER_ID}.humanode_tunnel_binary_path" "${CONFIG_FILE}")
    NODE_NAME=$(jq -r ".servers.${FIRST_SERVER_ID}.name" "${CONFIG_FILE}" | sed 's/[^a-zA-Z0-9]//g' | tr '[:upper:]' '[:lower:]') # Sanitize name for service file

    # Humanode Peer service
    PEER_SERVICE_TEMPLATE="${INSTALL_DIR}/systemd/humanode-peer.service.template"
    PEER_SERVICE_FILE="/etc/systemd/system/humanode-peer.service" # Generic name
    if [ -f "${PEER_SERVICE_TEMPLATE}" ]; then
        sudo cp "${PEER_SERVICE_TEMPLATE}" "${PEER_SERVICE_FILE}"
        sudo sed -i "s|__HUMANODE_HOME__|${HUMANODE_HOME}|g" "${PEER_SERVICE_FILE}"
        sudo sed -i "s|__HUMANODE_BINARY_PATH__|${HUMANODE_BINARY_PATH}|g" "${PEER_SERVICE_FILE}"
        sudo sed -i "s|__HUMANODE_DATA_PATH__|${HUMANODE_DATA_PATH}|g" "${PEER_SERVICE_FILE}"
        sudo sed -i "s|__NODE_NAME__|${NODE_NAME}|g" "${PEER_SERVICE_FILE}"
        sudo sed -i "s|__CHAINSPEC_PATH__|${CHAINSPEC_PATH}|g" "${PEER_SERVICE_FILE}"
        echo "Generated ${PEER_SERVICE_FILE}"
    else
        echo "Warning: humanode-peer.service.template not found. Skipping peer service generation."
    fi

    # Humanode WebSocket Tunnel service
    TUNNEL_SERVICE_TEMPLATE="${INSTALL_DIR}/systemd/humanode-websocket-tunnel.service.template"
    TUNNEL_SERVICE_FILE="/etc/systemd/system/humanode-websocket-tunnel.service" # Generic name
    if [ -f "${TUNNEL_SERVICE_TEMPLATE}" ]; then
        sudo cp "${TUNNEL_SERVICE_TEMPLATE}" "${TUNNEL_SERVICE_FILE}"
        sudo sed -i "s|__HUMANODE_HOME__|${HUMANODE_HOME}|g" "${TUNNEL_SERVICE_FILE}"
        sudo sed -i "s|__HUMANODE_TUNNEL_BINARY_PATH__|${HUMANODE_TUNNEL_BINARY_PATH}|g" "${TUNNEL_SERVICE_FILE}"
        echo "Generated ${TUNNEL_SERVICE_FILE}"
    else
        echo "Warning: humanode-websocket-tunnel.service.template not found. Skipping tunnel service generation."
    fi
fi

# 7. Reload systemd, enable and start services
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling and starting humanode-bot.service..."
sudo systemctl enable humanode-bot.service
sudo systemctl start humanode-bot.service

# Enable and start node/tunnel services if they were generated
if [ -f "/etc/systemd/system/humanode-peer.service" ]; then
    echo "Enabling and starting humanode-peer.service..."
    sudo systemctl enable humanode-peer.service
    sudo systemctl start humanode-peer.service
fi

if [ -f "/etc/systemd/system/humanode-websocket-tunnel.service" ]; then
    echo "Enabling and starting humanode-websocket-tunnel.service..."
    sudo systemctl enable humanode-websocket-tunnel.service
    sudo systemctl start humanode-websocket-tunnel.service
fi

echo "Installation complete. Check bot status with: sudo systemctl status humanode-bot.service"
echo "Check node status with: sudo systemctl status humanode-peer.service"
echo "Check tunnel status with: sudo systemctl status humanode-websocket-tunnel.service"
echo "Bot logs: ${LOG_FILE}"