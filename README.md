# Humanode Management Bot

A Telegram bot to manage and monitor your Humanode nodes.

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
bash <(curl -sSL https://raw.githubusercontent.com/stalkerSumy/humanode-bot-dist/main/install.sh)
```

## Usage

After installation, the bot will be running as a `systemd` service.

- To check the bot's status: `sudo systemctl status humanode-bot`
- To view its logs: `sudo journalctl -u humanode-bot -f`

Open Telegram, find your bot, and send the `/start` command to begin.

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