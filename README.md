# Wayfair Service Pro — Auto-Claim Bot

Бот для автоматического мгновенного принятия заявок в Wayfair Service Pro.

---

## Как это работает

1. Бот аутентифицируется через API Wayfair (email + пароль)
2. Каждые 2 секунды опрашивает список доступных заявок (`GetAvailableJobsQueryV2`)
3. При появлении новой заявки немедленно отправляет `JobClaimMutationV2`
4. Если заявка уже принята — фиксирует ошибку и продолжает мониторинг
5. Автоматически обновляет токен авторизации до его истечения

## Архитектура

| Файл | Ответственность |
|---|---|
| `wayfair/wayfair_config.py` | Настройки, загрузка хэшей из `gql_hashes.json`, переменные окружения |
| `wayfair/wayfair_api.py` | HTTP-клиент: аутентификация, JWT-парсинг, auto-refresh токена, GraphQL |
| `wayfair/wayfair_bot.py` | Основная логика: polling loop, автоматический claim, статистика |
| `wayfair/update_hashes.py` | Скрипт обновления хэшей при выходе новой версии приложения |
| `wayfair/gql_hashes.json` | 36 GraphQL операций с хэшами (автогенерируется) |
| `wayfair_service.service` | Systemd unit для автозапуска после перезагрузки сервера |
| `API_DOCS.md` | Полная документация API (endpoints, хэши, модели данных) |

---

## Быстрый старт

### 1. Клонировать репозиторий

```bash
git clone https://github.com/rinat3636/wayfair-auto-claim-bot.git
cd wayfair-auto-claim-bot
```

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Настроить переменные окружения

```bash
cp .env.example .env
# Отредактировать .env — указать WAYFAIR_EMAIL и WAYFAIR_PASSWORD
```

### 4. Запустить бота

```bash
python -m wayfair.wayfair_bot
```

---

## Автообновление токена

Бот автоматически обновляет Bearer token:

- Парсит JWT `exp` claim для определения точного времени истечения
- Обновляет токен за 5 минут до истечения (настраивается через `TOKEN_REFRESH_MARGIN`)
- Сначала пробует лёгкий refresh через `authenticate_with_token`
- Если не удалось — делает полную авторизацию через email/пароль
- Защита от race conditions через `asyncio.Lock`

## Обновление хэшей при обновлении приложения

При обновлении Wayfair Service Pro GraphQL хэши могут измениться. Бот:

1. **Автоматически определяет** ошибку `PersistedQueryNotFound` и логирует предупреждение
2. **Обновляет хэши одной командой:**

```bash
# Автоматически скачивает последний APK, декомпилирует, извлекает новые хэши
python -m wayfair.update_hashes

# Или из локального APK файла
python -m wayfair.update_hashes /path/to/wayfair.apk
```

Требуется `apktool`: `sudo apt-get install apktool`

---

## Настройки (переменные окружения)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `WAYFAIR_EMAIL` | — | Email аккаунта Wayfair Service Pro |
| `WAYFAIR_PASSWORD` | — | Пароль аккаунта |
| `POLL_INTERVAL_SECONDS` | `2` | Интервал опроса (сек) |
| `CLAIM_RETRY_LIMIT` | `3` | Макс. попыток claim на одну заявку |
| `REQUEST_TIMEOUT` | `15` | Таймаут HTTP-запросов (сек) |
| `TOKEN_REFRESH_MARGIN` | `300` | Запас времени до истечения токена (сек) |
| `LOG_FILE` | `wayfair_bot.log` | Путь к файлу логов |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

---

## Автозапуск (systemd)

```bash
# Скопировать unit-файл
sudo cp wayfair_service.service /etc/systemd/system/wayfair-bot.service

# Отредактировать пути в файле если нужно
sudo nano /etc/systemd/system/wayfair-bot.service

# Активировать и запустить
sudo systemctl daemon-reload
sudo systemctl enable wayfair-bot
sudo systemctl start wayfair-bot

# Проверить статус
sudo systemctl status wayfair-bot
journalctl -u wayfair-bot -f
```

---

## Логирование

Бот ведёт двойное логирование: в консоль и в файл (`wayfair_bot.log`).

### Формат записей

```
2025-06-20 10:00:01 [INFO] wayfair.bot: NEW JOB  id=12345  date=2025-06-25  appeared=2025-06-20T10:00:01+00:00
2025-06-20 10:00:01 [INFO] wayfair.bot: CLAIM ATTEMPT  id=12345  date=2025-06-25  ts=2025-06-20T10:00:01+00:00
2025-06-20 10:00:01 [INFO] wayfair.bot: CLAIM SUCCESS  id=12345  reaction=350 ms  msg=Job claimed successfully
```

### Что записывается

- Время появления заявки
- ID заявки (`proJobRoundId`)
- Время отправки claim
- Результат принятия (SUCCESS / FAILED)
- Время реакции в миллисекундах
- Ошибки аутентификации и сетевые ошибки

---

## Пример успешного автоматического принятия

```
2025-06-20 10:00:00 [INFO] wayfair.bot: ══════════════════════════════════════
2025-06-20 10:00:00 [INFO] wayfair.bot: Wayfair Service Pro Auto-Claim Bot starting…
2025-06-20 10:00:00 [INFO] wayfair.bot: Poll interval: 2.0 s
2025-06-20 10:00:00 [INFO] wayfair.bot: ══════════════════════════════════════
2025-06-20 10:00:01 [INFO] wayfair.api: Authentication successful
2025-06-20 10:00:01 [INFO] wayfair.api: Token stored (expires in 60 min)
2025-06-20 10:00:03 [INFO] wayfair.bot: NEW JOB  id=98765  date=2025-06-22  appeared=2025-06-20T10:00:03+00:00
2025-06-20 10:00:03 [INFO] wayfair.bot: CLAIM ATTEMPT  id=98765  date=2025-06-22  ts=2025-06-20T10:00:03+00:00
2025-06-20 10:00:03 [INFO] wayfair.bot: CLAIM SUCCESS  id=98765  reaction=280 ms  msg=Job claimed successfully
2025-06-20 10:50:01 [INFO] wayfair.api: Token expiring soon — refreshing…
2025-06-20 10:50:01 [INFO] wayfair.api: Token refreshed via authenticate_with_token
2025-06-20 10:50:01 [INFO] wayfair.api: Token stored (expires in 60 min)
```

---

## API

Полная документация API доступна в [API_DOCS.md](API_DOCS.md).

### Ключевые операции

- **GetAvailableJobsQueryV2** — список доступных заявок
- **GetJobDetailsQueryV2** — детали заявки
- **JobClaimMutationV2** — принять заявку
- **JobCancelMutationV2** — отменить заявку

### Безопасность

- Все запросы идут по HTTPS
- Авторизация через Bearer token
- Токен обновляется автоматически до истечения
- SSL Pinning приложения не влияет на бота (бот работает напрямую с сервером)
