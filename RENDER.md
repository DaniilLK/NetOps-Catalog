# Деплой на Render.com — пошагово

Приложение: https://netops-catalog.onrender.com

Сервис уже создан вручную (не через Blueprint), поэтому `render.yaml` из репозитория
Render **не читает** — все настройки задаются в панели, как описано ниже.
(`render.yaml` можно оставить как шпаргалку или удалить, на работу он не влияет.)

---

## Шаг 1. Переменные окружения (главное)

1. Открыть https://dashboard.render.com и выбрать сервис **netops-catalog**.
2. В верхнем меню сервиса открыть вкладку **Environment**.
3. В блоке **Environment Variables** нажать **Add Environment Variable**.
   Появляются два поля: **Key** и **Value**. Добавить три переменные:

| Key (поле Key) | Value (поле Value) | Зачем |
|---|---|---|
| `SECRET_KEY` | нажать **Generate** справа от поля Value (Render подставит случайную строку) | Ключ подписи JWT. Без него ключ случайный и **сессии слетают после каждого засыпания/рестарта** free-инстанса |
| `COOKIE_SECURE` | `1` | Cookie получают флаг `Secure` (только HTTPS) + включается HSTS |
| `TRUST_PROXY_HEADERS` | `1` | IP клиента берётся из `X-Forwarded-For` → лимит попыток входа работает по-настоящему, а не «на весь прокси» |

4. Необязательные переменные (можно не добавлять):

| Key | Value | Зачем |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `120` | Время жизни сессии в минутах (по умолчанию 120) |
| `ALLOWED_HOSTS` | `netops-catalog.onrender.com` | Включает `TrustedHostMiddleware`. **Не задавайте**, если пользуетесь preview-окружениями — они получат 400 |
| `DB_PATH` | `/var/data/DataBase.db` | Только если подключите Render Disk (платный план) |

5. Нажать **Save Changes** (внизу страницы). Render сразу запустит новый деплой —
   смотреть прогресс во вкладках **Events** и **Logs**.

> Важно про `SECRET_KEY`: если позже сгенерировать его заново, все активные сессии
> станут недействительными (пользователи просто увидят «Сессия истекла»).

---

## Шаг 2. Start Command

1. В меню сервиса открыть вкладку **Settings**.
2. Найти блок **Build & Deploy**.
3. Проверить поля:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command** — в поле должна быть **ровно одна строка**, без обратных кавычек,
     без дефиса в начале и без слова `javascript`. Render передаёт содержимое поля в bash
     как есть, поэтому любая markdown-обёртка ломает запуск:

     uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"

   > Признак ошибки — в логах деплоя `bash: line 1: javascript: command not found`.
   > Это значит, что в поле вставили markdown-блок вместе с обратными кавычками.
   > Неверная строка начинается с дефиса и слова `javascript`:

4. Поле **Start Command** заменить целиком: Ctrl+A → Delete → вставить команду →
   **Save Changes** (снова будет редеплой).

Почему именно так:
- `--host 0.0.0.0 --port $PORT` — Render сам назначает порт и передаёт его в `$PORT`,
  приложение обязано слушать все интерфейсы (иначе «No open ports detected» / 502);
- `--proxy-headers --forwarded-allow-ips="*"` — перед uvicorn стоит прокси Render,
  без этих флагов приложение видит IP прокси вместо IP клиента.

---

## Шаг 3. Автодеплой из git

Там же, **Settings → Build & Deploy**:
- **Auto-Deploy**: `Yes` — тогда каждый `git push` в ветку деплоится сам;
- если `No` — деплой вручную: кнопка **Manual Deploy** справа вверху → **Deploy latest commit**.

---

## Шаг 4. Проверка после деплоя (2 минуты)

### 4.1. Заголовки безопасности (PowerShell)

```powershell
curl.exe -sS -m 60 -D - -o NUL https://netops-catalog.onrender.com/api/profile
```

Должно быть `HTTP/1.1 401 Unauthorized` и в заголовках:

```
cache-control: no-store
x-content-type-options: nosniff
x-frame-options: DENY
content-security-policy: default-src 'self'; ...
strict-transport-security: max-age=31536000; includeSubDomains
```

HSTS появляется только если `COOKIE_SECURE=1`.

### 4.2. Cookie сессии (DevTools)

`curl` с JSON-логином в PowerShell 5.1 неудобен: PowerShell портит кавычки в теле запроса
и по умолчанию не включает TLS 1.2, поэтому проще проверить в браузере:

1. Открыть сайт, войти под своей учётной записью.
2. `F12` → вкладка **Application** (Firefox: **Storage**) → **Cookies** →
   `https://netops-catalog.onrender.com`.
3. Проверить две записи:

| Cookie | HttpOnly | Secure | SameSite |
|---|---|---|---|
| `access_token` | ✓ должен быть | ✓ | `Strict` |
| `csrf_token` | ✗ (его читает JS) | ✓ | `Strict` |

4. Вкладка **Application → Local Storage**: должен быть только `cart`, токена там быть не должно.
5. Выйти и зайти снова — старая cookie должна перестать работать
   (`/api/profile` отдаёт 401, повторный запрос с отозванным токеном — тоже 401).

### 4.3. CSP и картинки

- **Console**: не должно быть ошибок `Refused to load ... because it violates Content Security Policy`;
- картинки товаров из `/uploads/...` должны отображаться (в политике `img-src 'self'`);
- **Network → запрос `/api/...` → Response Headers**: визуально те же заголовки, что в 4.1.

---

## Шаг 5. Если что-то не работает

| Симптом | Причина | Что сделать |
|---|---|---|
| `bash: line 1: javascript: command not found`, `Exited with status 127` | в Start Command вставлен markdown-блок вместо команды | очистить поле целиком и вставить только команду (шаг 2) |
| Коммит запушен в GitHub, но сайт отдаёт старый код (нет `x-frame-options`) | Auto-Deploy выключен, либо сервис собран из другой ветки, либо деплой упал и Render держит прежний инстанс | **Manual Deploy → Deploy latest commit**; в **Settings** проверить **Branch = main** и **Auto-Deploy = Yes**; посмотреть **Events** — там причина падения |
| «Сессия истекла» после каждого захода / выкидывает через 15 минут | не задан `SECRET_KEY` (ключ генерируется случайно при старте) | добавить `SECRET_KEY` (шаг 1) и задеплоить |
| Вход проходит, но следующее действие даёт 403 «CSRF-токен отсутствует» | в браузере старый `main.js` из кэша | Ctrl+F5; проверить, что задеплоен последний коммит |
| 429 «Слишком много попыток входа» на пустом месте | все пользователи считаются одним IP прокси | `TRUST_PROXY_HEADERS=1` + флаги `--proxy-headers` в Start Command |
| 502 / «No open ports detected» | приложение слушает не `0.0.0.0`/не `$PORT` | исправить Start Command (шаг 2) |
| Деплой падает на `bcrypt` | сборка под новую версию Python | в `requirements.txt` заменить `bcrypt==4.0.1` на `bcrypt>=4.1.2` |
| Логин работает, но сайт «пустой» | CSP блокирует внешний ресурс | посмотреть Console; сообщить, поправим политику |

---

## Ограничение free-плана: эфемерный диск

Файловая система контейнера стирается при каждом деплое и после засыпания сервиса
(15 минут без запросов). Значит `DataBase.db` откатывается к версии **из git**, а
загруженные админом картинки в `static/uploads` исчезают. Для учебного теста это
нормально: база всегда есть в репозитории.

Если нужна сохранность — Render Disk (платный инстанс) на `/var/data`,
`DB_PATH=/var/data/DataBase.db`, и один раз положить туда `DataBase.db`.

---

## Секреты

`SECRET_KEY`, `ADMIN_PASSWORD` и `.env` в git не коммитятся (`.env` уже в `.gitignore`).
`DataBase.db` в репозитории **остаётся намеренно** — по условию задания.

## HTTPS

Render сам выдаёт сертификат и редиректит HTTP → HTTPS, настраивать нечего.
`COOKIE_SECURE=1` безопасно включать только на HTTPS-домене (на localhost по HTTP
браузер cookie с флагом `Secure` не сохранит).

---

## Результат проверки продакшена (05.11.2026, коммит 4ad3f05)

| Проверка | Результат |
|---|---|
| `GET /api/profile` без сессии | `401` + `cache-control: no-store`, `x-frame-options: DENY`, `x-content-type-options: nosniff`, `referrer-policy: no-referrer`, `permissions-policy`, `content-security-policy`, `strict-transport-security: max-age=31536000` |
| `POST /api/checkout` с `Origin: https://evil.example` | `403` «Запрос с недопустимого источника» |
| `POST /api/checkout` без `Origin` и без `X-CSRF-Token` | `403` «CSRF-токен отсутствует или неверен» |
| `POST /api/logout` | `Set-Cookie: access_token=""; HttpOnly; Secure; SameSite=strict; Max-Age=0` и `csrf_token=""; Secure; SameSite=strict` |
| 11 неудачных логинов подряд | `401` ×10, затем `429` «Слишком много попыток входа» |
| `/main.js` | есть `X-CSRF-Token`, `localStorage` — только для `cart` |
| `GET /` и `GET /api/products` | `200` |

Вывод: `SECRET_KEY`, `COOKIE_SECURE=1`, `TRUST_PROXY_HEADERS=1` на сервисе заданы,
новые middleware работают в проде. Лимит попыток входа хранится в памяти процесса,
поэтому очищается при каждом рестарте/деплое сервиса.

---

## Android-приложение

Сайт упакован в APK как **Trusted Web Activity** (Android Studio не нужна).
Манифест, иконки, service worker и `assetlinks.json` уже в репозитории;
пошаговая сборка в PWABuilder — в [`ANDROID.md`](ANDROID.md).
