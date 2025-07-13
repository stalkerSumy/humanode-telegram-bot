#!/bin/bash

# Humanode Management Bot Uninstaller

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

# --- Main Uninstallation Logic ---
main() {
    echo -e "${C_BLUE}=================================================${C_RESET}"
    echo -e "${C_BLUE} Welcome to the Humanode Management Bot Uninstaller ${C_RESET}"
    echo -e "${C_BLUE}=================================================${C_RESET}"
    echo

    # Check if running as root, if not, prepend sudo
    if [ "$EUID" -ne 0 ]; then
        SUDO_CMD="sudo"
        info "This script needs to run with root privileges."
    else
        SUDO_CMD=""
    fi

    # 1. Stop and disable the systemd service
    BOT_SERVICE_FILE="/etc/systemd/system/humanode-bot.service"
    if [ -f "$BOT_SERVICE_FILE" ]; then
        info "Stopping and disabling the 'humanode-bot.service'..."
        $SUDO_CMD systemctl stop humanode-bot.service
        $SUDO_CMD systemctl disable humanode-bot.service
        $SUDO_CMD rm -f "$BOT_SERVICE_FILE"
        info "Reloading systemd daemon..."
        $SUDO_CMD systemctl daemon-reload
        success "Systemd service has been removed."
    else
        info "Systemd service file not found. Skipping."
    fi

    # 2. Remove the installation directory
    read -p "Enter the installation directory to remove [default: /opt/humanode-bot]: " INSTALL_DIR
    INSTALL_DIR=${INSTALL_DIR:-/opt/humanode-bot}

    if [ -d "$INSTALL_DIR" ]; then
        read -p "This will permanently delete the directory '$INSTALL_DIR' and all its contents. Are you sure? (y/n): " CONFIRM
        if [[ "$CONFIRM" == "y" ]]; then
            info "Removing installation directory: $INSTALL_DIR..."
            $SUDO_CMD rm -rf "$INSTALL_DIR"
            success "Directory removed."
        else
            info "Uninstallation cancelled by user."
            exit 0
        fi
    else
        info "Installation directory '$INSTALL_DIR' not found. Nothing to remove."
    fi

    echo
    echo -e "${C_GREEN}========================${C_RESET}"
    echo -e "${C_GREEN}  Uninstallation Complete!  ${C_RESET}"
    echo -e "${C_GREEN}========================${C_RESET}"
}

# Run the main function
main
