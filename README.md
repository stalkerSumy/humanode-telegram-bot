# Humanode Management Bot

A Telegram bot to manage and monitor your Humanode nodes.

## Features

- Interactive installation
- Multi-language support (English/Ukrainian)
- Manage multiple servers (local and remote via SSH)
- Get bio-authentication and epoch timers using Selenium
- Start, stop, restart, and check the status of your node service
- View node logs directly from Telegram

## Installation

To install the bot, run the following command on your server and follow the on-screen instructions:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/stalkerSumy/humanode-bot-dist/main/install.sh)
```

## Usage

After installation, the bot will be running as a `systemd` service.

- To check the bot's status: `sudo systemctl status humanode-bot`
- To view its logs: `sudo journalctl -u humanode-bot -f`

Open Telegram, find your bot, and send the `/start` command to begin.

 Uninstallation

 To completely remove the bot and its service from your system, run the following command:
 
```
  /bin/bash -c "$(curl -sSL https://raw.githubusercontent.com/stalkerSumy/humanode-telegram-bot/main/uninstall.sh)"
```


## ❤️ Support the Project

If you find this bot useful, please consider supporting its development:

- **EVM Networks (ETH, BSC, Polygon, etc.):**
  `0x5A1D23F27bd84dd3Bc02ecCAD3d48bEAFD60dF10`

- **Humanode (HMND):**
  `hmqxDrZmJzJwNoyCdnGFdmhAVvnH984j8gFJfc2fbQ7Qnjwnq`

---
Powered by **mr.Lee** and **Gemini**
