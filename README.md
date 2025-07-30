# Humanode Management Bot
✦ Disclaimer: Everything you do is at your own risk!

  The bot is installed on an already prepared node. In the launcher, stop the node, exit the launcher, and then install the bot. It is
  important to start at the beginning of an epoch.

A Telegram bot to manage and monitor your Humanode nodes.

✦ English translation:

  Core Features

  This Telegram bot is designed for comprehensive management and monitoring of your Humanode nodes.

   * Interactive Menu-Driven Control:
       * A convenient button-based interface in Telegram for accessing all functions.
       * Support for multiple languages (Ukrainian/English).

   * Multi-Server Management:
       * Ability to manage both a local node and remote servers via SSH.
       * Secure connection using SSH keys.

   * Timer Monitoring (Selenium + OCR):
       * Automatic URL Retrieval: The bot independently finds the current link to the web dashboard by analyzing tunnel logs.
       * Timer Recognition: Uses Selenium to access the web dashboard and OCR technology (Tesseract) to read the time remaining for
         bio-authentication and the end of the epoch.
       * Automatic Notifications: Sends warnings when the time for bio-authentication becomes critically low (e.g., 30 and 10 minutes).

   * Node and Service Management:
       * Full control over the humanode-peer service: start, stop, restart, and status checks.
       * Management of the humanode-websocket-tunnel service to ensure a stable connection.
       * Ability to view the latest node logs directly in Telegram.

   * Updates and Backups:
       * Node Update: Automatically downloads the latest version of the humanode-peer binary from GitHub and installs it.
       * Backup Creation: Creates local backups of the node's database.
       * Restore from Backup: Ability to restore the database from a local file or from an official snapshot from GitHub, including support for
         multi-part archives.


#UA#
## Основні функції

Цей Telegram-бот призначений для комплексного керування та моніторингу ваших нод Humanode.

*   **Інтерактивне керування через меню:**
    *   Зручний інтерфейс на основі кнопок у Telegram для доступу до всіх функцій.
    *   Підтримка кількох мов (українська/англійська).

*   **Керування кількома серверами:**
    *   Можливість керувати як локальною нодою, так і віддаленими серверами через SSH.
    *   Безпечне підключення за допомогою SSH-ключів.

*   **Моніторинг таймерів (Selenium + OCR):**
    *   **Автоматичне отримання URL:** Бот самостійно знаходить актуальне посилання на веб-панель, аналізуючи логи тунелю.
    *   **Розпізнавання таймерів:** Використовує Selenium для доступу до веб-панелі та технологію OCR (Tesseract) для зчитування часу, що залишився до біоаутентифікації та кінця епохи.
    *   **Автоматичні сповіщення:** Надсилає попередження, коли час до біоаутентифікації стає критично малим (наприклад, 30 та 10 хвилин).

*   **Керування нодою та сервісами:**
    *   Повний контроль над сервісом `humanode-peer`: запуск, зупинка, перезапуск та перевірка статусу.
    *   Керування сервісом `humanode-websocket-tunnel` для забезпечення стабільного з'єднання.
    *   Можливість переглядати останні логи ноди безпосередньо в Telegram.

*   **Оновлення та резервне копіювання:**
    *   **Оновлення ноди:** Автоматичне завантаження останньої версії бінарного файлу `humanode-peer` з GitHub та його встановлення.
    *   **Резервне копіювання:** Створення локальних бекапів бази даних ноди.
    *   **Відновлення з бекапу:** Можливість відновити базу даних з локального файлу або з офіційного знімку (snapshot) з GitHub, включаючи підтримку багатофайлових архівів.

## Installation

To install the bot, run the following command on your server and follow the on-screen instructions:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/stalkerSumy/humanode-telegram-bot/main/install.sh)
```

## Usage

After installation, the bot will be running as a `systemd` service.

- To check the bot's status: `sudo systemctl status humanode-bot`
- To view its logs: `sudo journalctl -u humanode-bot -f`

Open Telegram, find your bot, and send the `/start` command to begin.

## Screenshots

| Main Menu | Server Menu |
| :---: | :---: |
| <img src="screenshots/photo_1_2025-07-30_14-06-47.jpg" width="300"> | <img src="screenshots/photo_2_2025-07-30_14-06-47.jpg" width="300"> |

| Node Management | Backup Menu |
| :---: | :---: |
| <img src="screenshots/photo_3_2025-07-30_14-06-47.jpg" width="300"> | <img src="screenshots/photo_4_2025-07-30_14-06-47.jpg" width="300"> |

| Bio-Auth Timer |
| :---: |
| <img src="screenshots/photo_5_2025-07-30_14-06-58.jpg" width="300"> |


## Uninstallation

To completely remove the bot and its service from your system, run the following command:

```bash
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