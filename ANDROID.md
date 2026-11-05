# Android-приложение (TWA) для NetOps Catalog

Приложение — это **Trusted Web Activity**: тонкая обёртка над сайтом
`https://netops-catalog.onrender.com`, которая открывает его в движке Chrome
на весь экран. Своего кода у приложения нет, поэтому любые правки сайта сразу
видны в приложении и пересобирать APK не нужно.

**Android Studio не требуется.** APK собирается в браузере на
[pwabuilder.com](https://www.pwabuilder.com) за несколько минут.

---

## Готовый APK (скачать и поставить)

Собранная и подписанная сборка лежит в GitHub Releases — пересобирать ничего не нужно:

- Страница релиза: <https://github.com/DaniilLK/NetOps-Catalog/releases/latest>
- Прямая ссылка на файл: <https://github.com/DaniilLK/NetOps-Catalog/releases/download/v1.0.0/NetOps.apk>

| Параметр | Значение |
|---|---|
| package | `com.daniilk.netopscatalog` |
| размер | 913 141 байт (~892 KB) |
| SHA-256 файла | `FF22B864CA34EF5679C847A0A8072C5F6D3D4CC81040B9CBADE0FB89BC8C71C5` |
| SHA-256 подписи | `11:F2:D4:5B:E1:C4:85:2B:A5:EE:57:06:E6:C9:12:39:95:2C:A5:E6:55:B8:35:6A:54:25:25:6D:8C:49:98:B6` |

Установка: скачать файл на телефоне → разрешить установку из этого источника
(*Настройки → Приложения → Специальный доступ → Установка неизвестных приложений*)
→ открыть файл и подтвердить.

Обновление сборки: собрать новый APK на pwabuilder.com и приложить его к релизу
(*Releases → у нужного релиза **Edit** → Attach binaries*) либо создать новый релиз
с новым тегом. Ставить поверх можно только сборки, подписанные тем же
`signing.keystore` — иначе приложение придётся удалить.

> Сам APK в git не коммитится (см. `.gitignore`): он живёт только как asset релиза,
> поэтому история репозитория не распухает.

---

## Что уже подготовлено в репозитории

| Файл | Зачем |
|---|---|
| `static/manifest.json` | PWA-манифест: имя, иконки, `start_url`, `display: standalone` — по нему PWABuilder собирает приложение |
| `static/icons/*.png` | Иконки 192, 512, maskable и apple-touch. Сейчас это заглушки (crimson + белая «N») — замените своим логотипом в тех же размерах |
| `static/service-worker.js` | Кэширует только оболочку (`/`, css, js, манифест). Запросы `/api/*` не кэшируются никогда |
| `static/.well-known/assetlinks.json` | Привязка домена к приложению. Туда нужно вписать SHA-256 отпечаток подписи (шаг 3) |
| `static/index.html` | `<link rel="manifest">`, `theme-color`, `apple-touch-icon` |
| `static/main.js` | Регистрация service worker в `DOMContentLoaded` |

---

## Шаг 1. Задеплоить сайт

Все изменения должны быть на проде — PWABuilder читает манифест по публичному URL.

```bash
git add -A
git commit -m "Add PWA manifest, icons, service worker and TWA asset links"
git push origin main
```

На Render: **Manual Deploy → Deploy latest commit** (или дождитесь auto-deploy).
Проверка, что всё доступно:

```bash
curl -sS https://netops-catalog.onrender.com/manifest.json
curl -sS https://netops-catalog.onrender.com/service-worker.js -o NUL -w "%{http_code}\n"
curl -sS https://netops-catalog.onrender.com/.well-known/assetlinks.json
curl -sS https://netops-catalog.onrender.com/icons/icon-512.png -o NUL -w "%{http_code} %{content_type}\n"
```

Ожидаемо: `200` и `application/json` / `text/javascript` (или `application/javascript`)
/ `image/png`. Если `manifest.json` отдаётся как `text/html` — значит его перехватывает
SPA-фолбэк, проверьте, что файл действительно лежит в `static/`.

---

## Шаг 2. Собрать APK в PWABuilder

1. Открыть <https://www.pwabuilder.com>, вставить `https://netops-catalog.onrender.com`, нажать **Start**.
2. Дождаться отчёта: манифест, HTTPS и service worker должны быть «зелёными».
3. Блок **Android** → **Package for Android**.
4. Заполнить:
   - **App name**: `NetOps Catalog`
   - **Short name**: `NetOps`
   - **Package ID**: `com.daniilk.netopscatalog` (должен совпадать с `package_name` в `assetlinks.json`)
   - **Version code** / **Version name**: `1` / `1.0.0` (увеличивать при каждой пересборке)
5. **Signing key**:
   - **Create new** — PWABuilder сгенерирует keystore и подпишет APK/AAB (проще всего);
   - **Use mine** — если у вас уже есть `.keystore`;
   - скачанный keystore и пароли сохраните: без него нельзя выпустить обновление.
6. **Download Package** → скачать **APK** (для установки руками) или **AAB** (для Google Play).
7. Скопировать с той же страницы **SHA-256 fingerprint** — он понадобится на шаге 3.

---

## Шаг 3. Привязать домен к приложению

Без этого шага приложение работает, но показывает адресную строку сверху.
После подтверждения связки Google Chrome открывает сайт полноэкранно.

1. Открыть `static/.well-known/assetlinks.json` и заменить строку-заглушку
   `ВСТАВЬТЕ_SHA256_ОТПЕЧАТОК_ИЗ_PWABUILDER` на отпечаток из PWABuilder
   (формат `AA:BB:CC:...`, ровно 32 байта через двоеточие):

```json
"sha256_cert_fingerprints": [
  "14:6D:E9:83:C5:73:06:50:D8:EE:B9:95:2F:34:FC:64:16:A0:83:42:E6:1D:BE:A8:8A:04:96:B2:3F:CF:44:E5"
]
```

2. Закоммитить и задеплоить:

```bash
git add static/.well-known/assetlinks.json
git commit -m "Add TWA signing fingerprint"
git push origin main
```

3. Подождать деплой Render и проверить, что файл отдаётся без редиректа:

```bash
curl -sS -D - https://netops-catalog.onrender.com/.well-known/assetlinks.json -o NUL
```

Ожидаемо `200 OK`, `content-type: application/json`, без `location:`.

4. Проверить саму связку у Google (может занять от минуты до суток):

<https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://netops-catalog.onrender.com&relation=delegate_permission/common.handle_all_urls>

В ответе должен появиться ваш `package_name` и отпечаток. Если пусто —
проверьте отпечаток, HTTPS и отсутствие редиректов у файла, затем на телефоне
«Настройки → Приложения → Chrome → Хранилище → Очистить данные» и заново
запустите приложение.

---

## Шаг 4. Установить APK на телефон

1. Передать APK на телефон (Telegram «Избранное», кабель, Google Drive).
2. Открыть файл → Android спросит разрешение «Устанавливать неизвестные приложения»
   для файлового менеджера/браузера → разрешить.
3. Установить и запустить.

Что проверить:

- приложение открывается без адресной строки (если она есть — шаг 3 ещё не подтверждён);
- вход в аккаунт работает, после перезапуска сессия сохраняется (cookie живут в профиле Chrome);
- кнопка «назад» возвращает по истории сайта, а с главной — закрывает приложение.

---

## Шаг 5. Публикация в Google Play (необязательно)

1. Аккаунт разработчика Google Play — 25 $ разово.
2. Загрузить **AAB** из PWABuilder, заполнить карточку: иконка 512×512,
   2–8 скриншотов, описание, **политика конфиденциальности** (обязательна: приложение
   принимает email/пароли и хранит данные заказов).
3. Включить **Play App Signing** (по умолчанию) и взять отпечаток из
   *Play Console → Test and release → Setup → App integrity → App signing key certificate*.
   Этот отпечаток добавить в `sha256_cert_fingerprints` **вместе** с отпечатком
   ключа, которым подписан AAB (PWABuilder выдаёт его как *upload key*):

```json
"sha256_cert_fingerprints": [
  "ОТПЕЧАТОК_UPLOAD_КЛЮЧА",
  "ОТПЕЧАТОК_КЛЮЧА_GOOGLE_PLAY"
]
```

4. Учесть требования Play: приложение не должно быть «просто обёрткой» без нативной
   ценности — TWA с подтверждённой связкой домена такое требование проходит,
   чистый WebView-контейнер может быть отклонён.

---

## Обновления

| Что меняете | Нужен новый APK? |
|---|---|
| Контент, стили, JS, товары, API | Нет — подтягивается с сайта |
| Иконка, имя приложения, version code | Да — пересобрать в PWABuilder и заново установить/загрузить в Play |
| `package_name` или ключ подписи | Да + обновить `assetlinks.json` |

Если меняете иконки/манифест/стили — не забудьте поднять версию кэша:
в `static/service-worker.js` увеличить `CACHE_NAME` (например на `netops-shell-v3`),
а в `static/index.html` обновить `?v=` у `/main.css` и `/main.js`. Иначе часть
клиентов (в первую очередь телефоны) останется на старой оболочке.

Статика отдаётся с `Cache-Control: no-cache` (см. middleware `static_cache_control`
в `main.py`) — браузер обязан ревалидировать файлы по ETag, поэтому даже без
смены `?v=` новая версия подхватывается при следующей загрузке страницы.

Проверить, какая версия файлов реально загрузилась на устройстве, можно по метке
в подвале сайта: `сборка 2026.11.05` (`.build-tag` в `static/index.html`).
Метку нужно менять вместе с версией, чтобы отличать сборки.

---

## Сборка без PWABuilder (Bubblewrap, локально)

Нужны Node.js, JDK 17 и Android SDK command-line tools (Android Studio не нужна):

```bash
npm install -g @bubblewrap/cli
bubblewrap doctor
bubblewrap init --manifest https://netops-catalog.onrender.com/manifest.json
bubblewrap build          # соберёт app-release-signed.apk и .aab
bubblewrap fingerprint    # SHA-256 для assetlinks.json
```

---

## Если что-то не так

| Симптом | Причина и решение |
|---|---|
| Сверху видна адресная строка | `assetlinks.json` не подтверждён: неверный отпечаток, не тот `package_name`, файл отдаётся с редиректом или старый деплой |
| Белый экран при запуске | Free-план Render «уснул» — первый запрос идёт 30–50 с. Повторный запуск открывает сразу |
| «Приложение не установлено» | APK скачан не полностью или на телефоне уже стоит сборка с другим ключом подписи — удалите старую |
| Бесконечный редирект на вход | Проверьте, что сайт открыт по HTTPS и `COOKIE_SECURE=1` задан (см. `RENDER.md`) |
| Логин «слетает» | Пользователь заходит в другом профиле Chrome; TWA использует системный браузер |
| Приложение не работает без Chrome | TWA требует Chrome; на устройствах без него откроется обычная вкладка — установите Chrome из Play |
| Картинки товаров пропали | На Render файловая система эфемерная: загрузки живут до перезапуска (см. `RENDER.md`) |
| На телефоне сайт тёмный, на ПК светлый | Chrome на Android включает Auto Dark Theme и инвертирует цвета. Отключено декларацией `color-scheme: only light` (meta в `index.html` + `:root` в `main.css`). Если после деплоя всё ещё тёмный — приложение не перезагрузило страницу: закройте его полностью (свайп из списка последних) и откройте заново; убедитесь, что в подвале видна свежая метка `сборка …`. Крайний случай — Chrome → Настройки → Тема → снять «Применять тёмную тему к сайтам» |

---

## Ограничения текущей реализации

- Иконки — заглушки; для публикации в Play замените их на логотип (192, 512 и maskable 512 в `static/icons/`).
- Связка домена заработает только после ручной вставки отпечатка (шаг 3) — до этого адресная строка остаётся.
- Офлайн-режим ограничен оболочкой: при отсутствии сети откроется страница, но данные каталога не загрузятся (API не кэшируется намеренно).

