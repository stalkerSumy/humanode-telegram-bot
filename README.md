# Humanode Telegram Management Bot

This is a Telegram bot for managing and monitoring your Humanode nodes.

## Features

*   **Multi-Node Support**: Manage several nodes from a single bot.
*   **Node & Tunnel Management**: Start, stop, restart, and check the status of your Humanode node and the required tunnel service.
*   **Automated Bio-authentication Monitoring**: Get timely notifications before your bio-authentication expires.
*   **Automated Backups**: Create and restore node database from local or GitHub backups.
*   **Node Updates**: Update your node to the latest version directly from the bot.
*   **Multi-language Support**: UI available in English and Ukrainian.

---

## Screenshots

Here is a glimpse of the bot's interface:

| Main Menu | Server Menu |
| :---: | :---: |
| ![Main Menu](screenshots/photo_1_2025-07-30_14-06-47.jpg) | ![Server Menu](screenshots/photo_2_2025-07-30_14-06-47.jpg) |

| Node Management | Backup Menu |
| :---: | :---: |
| ![Node Management](screenshots/photo_3_2025-07-30_14-06-47.jpg) | ![Backup Menu](screenshots/photo_4_2025-07-30_14-06-47.jpg) |

| Language Settings |
| :---: |
| ![Language Settings](screenshots/photo_5_2025-07-30_14-06-58.jpg) |

---

## 🚀 Installation (Automated)

The installation is fully automated. Just run the installer script with `sudo`. It will handle dependencies, create the necessary files, and set up a `systemd` service to run the bot automatically in the background.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/stalkerSumy/humanode-telegram-bot.git
    cd humanode-telegram-bot
    ```

2.  **Run the installer:**
    ```bash
    sudo bash install.sh
    ```
    The script will install the bot to `/opt/humanode-bot`.

---

## ⚙️ Configuration

After the installation is complete, you need to configure the bot.

1.  **Edit the main configuration file:**
    Open `/opt/humanode-bot/bot/config.json` with a text editor (like `nano` or `vim`) and fill in your details:
    *   `telegram_bot_token`: Your token from BotFather.
    *   `authorized_user_id`: Your numeric Telegram User ID.
    *   `github_token` (optional): A GitHub token to avoid rate-limiting when checking for updates.

2.  **Edit the servers file:**
    Open `/opt/humanode-bot/bot/servers.json` to add your nodes. You can add as many as you need.

    **Example for a remote server:**
    ```json
    {
      "my_vps_1": {
        "name": "My Main Node (AWS)",
        "ip": "12.34.56.78",
        "user": "root",
        "key_path": "/root/.ssh/id_rsa_humanode",
        "is_local": false
      }
    }
    ```

    **Example for a local node (running on the same machine as the bot):**
    ```json
    {
       "local_node": {
        "name": "Local Node",
        "ip": "127.0.0.1",
        "user": "root",
        "key_path": "",
        "is_local": true
      }
    }
    ```

3.  **Restart the bot to apply changes:**
    After editing the configuration files, you must restart the bot for the changes to take effect.
    ```bash
    sudo systemctl restart humanode_bot
    ```

---

## 🛠️ Managing the Bot Service

The bot runs as a `systemd` service, which means it will start automatically on system boot. You can manage it with standard `systemctl` commands:

*   **Check the status:**
    ```bash
    sudo systemctl status humanode_bot
    ```

*   **View live logs:**
    ```bash
    sudo journalctl -u humanode_bot -f
    ```

*   **Stop the bot:**
    ```bash
    sudo systemctl stop humanode_bot
    ```

*   **Start the bot:**
    ```bash
    sudo systemctl start humanode_bot
    ```

---

## ❤️ Support the Project

If you find this bot useful, please consider supporting its development:

- **EVM Networks (ETH, BSC, Polygon, etc.):**
  `0x5A1D23F27bd84dd3Bc02ecCAD3d48bEAFD60dF10`

- **Humanode (HMND):**
  `hmqxDrZmJzJwNoyCdnGFdmhAVvnH984j8gFJfc2fbQ7Qnjwnq`

---
Powered by **mr.Lee** and **Gemini**
