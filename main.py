from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
import sqlite3
import jwt
import hashlib
import hmac
import ipaddress
import random
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import os
import uuid
from typing import Optional, List
from urllib.parse import urlparse

from database import get_db, init_db

init_db()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    print("WARNING: переменная окружения SECRET_KEY не задана. Сгенерирован временный ключ — "
          "токены станут недействительны после перезапуска. Задайте SECRET_KEY в окружении для продакшена.")
ALGORITHM = "HS256"

# --- НАСТРОЙКИ СЕССИИ ---
try:
    ACCESS_TOKEN_EXPIRE_MINUTES = max(1, int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")))
except ValueError:
    ACCESS_TOKEN_EXPIRE_MINUTES = 120

# Secure-флаг нельзя включать при работе по HTTP: браузер просто не пришлёт cookie.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
COOKIE_SAMESITE = "strict"
SESSION_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"

if not COOKIE_SECURE:
    print("WARNING: COOKIE_SECURE не включён — cookie передаются без флага Secure. "
          "Это допустимо только для локальной разработки по HTTP; на продакшене задайте COOKIE_SECURE=1.")

app = FastAPI(title="Network Equipment API (Secure)")

# Разрешённые имена хостов (опционально). Включается только если задан ALLOWED_HOSTS,
# например на Render: ALLOWED_HOSTS=netops-catalog.onrender.com
_allowed_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _allowed_hosts:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
os.makedirs("static/uploads", exist_ok=True)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- ЗАГРУЗКА ИЗОБРАЖЕНИЙ ---
UPLOAD_DIR = os.path.join("static", "uploads")
ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 МБ

JPEG_SIGNATURE = bytes.fromhex("ffd8ff")
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
WEBP_RIFF = bytes.fromhex("52494646")
WEBP_TAG = bytes.fromhex("57454250")


def _is_valid_image(data: bytes) -> bool:
    """Проверяет сигнатуру файла (магические байты), а не только расширение."""
    if data.startswith(JPEG_SIGNATURE):
        return True
    if data.startswith(PNG_SIGNATURE):
        return True
    if data.startswith(WEBP_RIFF) and data[8:12] == WEBP_TAG:
        return True
    return False


def save_upload_image(upload: Optional[UploadFile]) -> Optional[str]:
    """Валидирует и сохраняет изображение. Возвращает публичный URL или None."""
    if not upload or not upload.filename:
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Недопустимый формат файла. Разрешены: JPG, PNG, WEBP")
    data = upload.file.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 5 МБ)")
    if not _is_valid_image(data):
        raise HTTPException(status_code=400, detail="Файл не является изображением")
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, safe_filename), "wb") as buffer:
        buffer.write(data)
    return f"/uploads/{safe_filename}"


def delete_upload_file(image_url: Optional[str]) -> None:
    """Удаляет физический файл изображения из static/uploads по его URL."""
    if not image_url:
        return
    path = os.path.join(UPLOAD_DIR, os.path.basename(image_url))
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# --- МОДЕЛИ ДАННЫХ ---
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72, description="Пароль минимум 8 символов")

    @field_validator('password')
    def validate_password(cls, v):
        if not re.search(r'[A-Za-z]', v) or not re.search(r'\d', v):
            raise ValueError('Пароль должен содержать хотя бы одну букву и одну цифру')
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)

class UserUpdate(BaseModel):
    username: str
    phone: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = Field(default=None, max_length=72)

class UserAdminUpdate(BaseModel):
    email: EmailStr
    username: str
    role: str
    phone: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = Field(default=None, max_length=72)

    @field_validator('role')
    def validate_role(cls, v):
        if v not in ('user', 'admin'):
            raise ValueError('Допустимые роли: user, admin')
        return v

class OrderCreate(BaseModel):
    phone: str
    address: str
    items: list[dict] 

class OrderStatusUpdate(BaseModel):
    status: str


# --- БЕЗОПАСНОСТЬ ---
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# login/register/logout выполняются до появления валидной CSRF-пары, поэтому исключены
CSRF_EXEMPT_PATHS = {"/api/login", "/api/register", "/api/logout"}
# Отозванные токены (логаут): jti -> unix-время истечения. В памяти процесса.
_revoked_tokens: dict = {}


def _pwd_fingerprint(password_hash: str) -> str:
    """Отпечаток хэша пароля: после смены пароля старые токены перестают работать."""
    return hmac.new(SECRET_KEY.encode(), password_hash.encode(), hashlib.sha256).hexdigest()[:32]


def create_access_token(row: sqlite3.Row) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": row["email"],
        "role": row["role"],
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": secrets.token_urlsafe(16),
        "pwd": _pwd_fingerprint(row["password_hash"]),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def set_auth_cookies(response: Response, row: sqlite3.Row) -> None:
    """Выдаёт httpOnly-cookie с JWT и читаемую JS CSRF-cookie (double-submit)."""
    max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        SESSION_COOKIE, create_access_token(row),
        max_age=max_age, httponly=True, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(32),
        max_age=max_age, httponly=False, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=COOKIE_SECURE,
        httponly=True, samesite=COOKIE_SAMESITE,
    )
    response.delete_cookie(
        CSRF_COOKIE, path="/", secure=COOKIE_SECURE,
        httponly=False, samesite=COOKIE_SAMESITE,
    )


def _revoke_token(token: str) -> None:
    """Добавляет jti токена в чёрный список до момента его естественного истечения."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        _revoked_tokens[jti] = float(exp)
    now = time.time()
    for key in [k for k, v in _revoked_tokens.items() if v < now]:
        _revoked_tokens.pop(key, None)


def get_current_user(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict:
    # Основной способ — httpOnly-cookie (недоступна для JS).
    # Authorization: Bearer оставлен для внешних клиентов (curl/Postman).
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Срок действия сессии истек")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Невалидный токен")

    # Логаут отзывает конкретный токен, даже если подпись и срок ещё валидны
    if payload.get("jti") in _revoked_tokens:
        raise HTTPException(status_code=401, detail="Сессия завершена")

    row = db.execute(
        "SELECT email, role, password_hash FROM users WHERE email = ?", (payload.get("sub"),)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    # Смена пароля (своя или админом) инвалидирует ранее выданные токены
    pwd_claim = payload.get("pwd")
    if not isinstance(pwd_claim, str) or not hmac.compare_digest(
        pwd_claim.encode(), _pwd_fingerprint(row["password_hash"]).encode()
    ):
        raise HTTPException(status_code=401, detail="Сессия устарела. Войдите заново.")

    # Роль берём из БД: понижение/повышение прав действует мгновенно
    payload["role"] = row["role"]
    return payload

def get_current_admin(payload: dict = Depends(get_current_user)):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    return payload


# --- БЕЗОПАСНЫЕ HTTP-ЗАГОЛОВКИ ---
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    # Внешние скрипты/шрифты не нужны; 'unsafe-inline' остаётся из-за inline-обработчиков в HTML
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
    if COOKIE_SECURE:
        # Имеет смысл только при реальном HTTPS (иначе браузер игнорирует заголовок)
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Ответы API не должны кэшироваться (там персональные данные и сессия)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --- КЭШИРОВАНИЕ СТАТИКИ ---
# StaticFiles не отдаёт Cache-Control, и браузер (особенно Chrome на Android)
# может неделями показывать старую версию HTML/CSS/JS без ревалидации — после
# деплоя на телефоне оставался прежний вид. no-cache = файл можно кэшировать,
# но перед каждым использованием обязательна проверка по ETag (ответ 304).
@app.middleware("http")
async def static_cache_control(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".css", ".js", ".json")):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# --- ЗАЩИТА ОТ CSRF (double-submit cookie + проверка Origin) ---
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    # CSRF опасен только для cookie-аутентификации: браузер прикладывает cookie сам.
    # Запрос с Authorization: Bearer из чужой формы отправить нельзя, поэтому его пропускаем.
    needs_check = (
        request.method not in SAFE_METHODS
        and request.url.path not in CSRF_EXEMPT_PATHS
        and not request.headers.get("Authorization", "").startswith("Bearer ")
    )
    if needs_check:
        origin = request.headers.get("origin")
        # Сравниваем только хост: схема может отличаться за reverse-proxy.
        # Основная защита всё равно в double-submit токене ниже.
        if origin and urlparse(origin).netloc.lower() != request.url.netloc.lower():
            return JSONResponse(status_code=403, content={"detail": "Запрос с недопустимого источника"})

        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get("x-csrf-token", "")
        if not cookie_token or not header_token or not hmac.compare_digest(
            cookie_token.encode(), header_token.encode()
        ):
            return JSONResponse(status_code=403, content={"detail": "CSRF-токен отсутствует или неверен"})

    return await call_next(request)


# --- ЗАЩИТА ОТ ПЕРЕБОРА ПАРОЛЕЙ (в памяти процесса) ---
_login_attempts: dict = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 10
LOGIN_MAX_ATTEMPTS_PER_IP = 50
LOGIN_WINDOW_SECONDS = 300


def check_login_rate_limit(identifier: str, max_attempts: int = LOGIN_MAX_ATTEMPTS) -> None:
    """Только проверяет лимит. Счётчик увеличивает record_login_failure (успешный вход не считается)."""
    now = time.time()
    attempts = [t for t in _login_attempts.get(identifier, []) if now - t < LOGIN_WINDOW_SECONDS]
    if attempts:
        _login_attempts[identifier] = attempts
    if len(attempts) >= max_attempts:
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Попробуйте позже.")

    # Не даём словарю расти бесконечно при переборе множества email/IP
    if len(_login_attempts) > 5000:
        for key in [k for k, v in _login_attempts.items() if not v or now - v[-1] > LOGIN_WINDOW_SECONDS]:
            _login_attempts.pop(key, None)


def record_login_failure(identifier: str) -> None:
    _login_attempts[identifier].append(time.time())


def _is_trusted_peer(host: str) -> bool:
    """True, если запрос пришёл от локального адреса или reverse-proxy (Render, Docker, ngrok)."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def get_client_ip(request: Request) -> str:
    """Реальный IP клиента даже за reverse-proxy.

    За прокси Render request.client.host — это адрес прокси, поэтому берём последний
    хоп X-Forwarded-For (его добавляет сам прокси, подделать его снаружи нельзя).
    Если доверять заголовку нельзя (прямое подключение из интернета), используем адрес пира.
    Принудительно включить доверие: TRUST_PROXY_HEADERS=1
    """
    peer = request.client.host if request.client else ""
    trust_mode = os.getenv("TRUST_PROXY_HEADERS", "auto").strip().lower()
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]

    if hops and (trust_mode == "1" or (trust_mode != "0" and _is_trusted_peer(peer))):
        try:
            return str(ipaddress.ip_address(hops[-1]))
        except ValueError:
            pass  # мусор в заголовке — игнорируем
    return peer or "unknown"


# --- АВТОРИЗАЦИЯ ---
@app.post("/api/register")
def register(user: UserRegister, db: sqlite3.Connection = Depends(get_db)):
    email = user.email.lower().strip()
    while True:
        random_username = f"user_{random.randint(1000, 9999)}"
        cursor = db.execute("SELECT id FROM users WHERE username = ?", (random_username,))
        if not cursor.fetchone(): break

    hashed_password = pwd_context.hash(user.password)
    try:
        db.execute("INSERT INTO users (email, username, password_hash, role) VALUES (?, ?, ?, 'user')", 
                   (email, random_username, hashed_password))
        db.commit()
        return {"message": "Успешная регистрация", "username": random_username}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Этот email уже зарегистрирован")

@app.post("/api/login")
def login(
    user: UserLogin,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    email = user.email.lower().strip()
    client_ip = get_client_ip(request)
    check_login_rate_limit(f"email:{email}")
    check_login_rate_limit(f"ip:{client_ip}", LOGIN_MAX_ATTEMPTS_PER_IP)
    cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
    db_user = cursor.fetchone()
    if not db_user or not pwd_context.verify(user.password, db_user['password_hash']):
        record_login_failure(f"email:{email}")
        record_login_failure(f"ip:{client_ip}")
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    _login_attempts.pop(f"email:{email}", None)
    # Токен больше не возвращается в теле ответа: только httpOnly-cookie
    set_auth_cookies(response, db_user)
    return {
        "message": "Вход выполнен",
        "email": db_user["email"],
        "role": db_user["role"],
        "username": db_user["username"],
    }


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _revoke_token(token)
    clear_auth_cookies(response)
    return {"message": "Выход выполнен"}

@app.get("/api/profile")
def get_profile(payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    email = payload["sub"]
    cursor = db.execute("SELECT email, username, role, phone, address FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    return dict(user) if user else {}

@app.put("/api/profile")
def update_profile(
    data: UserUpdate,
    response: Response,
    payload: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    email = payload["sub"]
    try:
        if data.password:
            if len(data.password) < 8 or not re.search(r'[A-Za-z]', data.password) or not re.search(r'\d', data.password):
                raise HTTPException(status_code=400, detail="Новый пароль слишком простой")
            hashed_password = pwd_context.hash(data.password)
            db.execute("UPDATE users SET username=?, password_hash=?, phone=?, address=? WHERE email=?",
                      (data.username, hashed_password, data.phone, data.address, email))
            db.commit()
            # Смена пароля инвалидирует старый токен — сразу выдаём новый
            refreshed = db.execute(
                "SELECT email, role, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
            if refreshed:
                set_auth_cookies(response, refreshed)
        else:
            db.execute("UPDATE users SET username=?, phone=?, address=? WHERE email=?",
                      (data.username, data.phone, data.address, email))
            db.commit()
        return {"message": "Профиль обновлен"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Ошибка обновления")

@app.get("/api/users")
def get_users(payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT id, email, username, role, phone, address FROM users")
    return [dict(row) for row in cursor.fetchall()]

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if target and target["email"] == payload["sub"]:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return {"message": "Пользователь удален"}

@app.put("/api/users/{user_id}")
def update_user_by_admin(
    user_id: int,
    data: UserAdminUpdate,
    response: Response,
    payload: dict = Depends(get_current_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        if data.password:
            hashed_password = pwd_context.hash(data.password)
            db.execute("UPDATE users SET email=?, username=?, role=?, password_hash=?, phone=?, address=? WHERE id=?", 
                       (data.email.lower().strip(), data.username, data.role, hashed_password, data.phone, data.address, user_id))
        else:
            db.execute("UPDATE users SET email=?, username=?, role=?, phone=?, address=? WHERE id=?", 
                       (data.email.lower().strip(), data.username, data.role, data.phone, data.address, user_id))
        db.commit()
        # Если админ правит сам себя и сменил пароль — перевыпускаем cookie,
        # иначе его собственный токен станет невалидным из-за отпечатка пароля.
        new_email = data.email.lower().strip()
        if new_email == payload["sub"]:
            refreshed = db.execute(
                "SELECT email, role, password_hash FROM users WHERE email = ?", (new_email,)
            ).fetchone()
            if refreshed:
                set_auth_cookies(response, refreshed)
        return {"message": "Пользователь обновлен"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Этот Email или Никнейм уже занят")


# --- КАТАЛОГ ---
@app.get("/api/products")
def get_products(
    category_slug: Optional[str] = None, vendor: Optional[str] = None,
    search: Optional[str] = None, page: int = 1, limit: int = 12,
    db: sqlite3.Connection = Depends(get_db)
):
    page = max(1, page)
    limit = max(1, min(limit, 100))

    query = "SELECT * FROM products WHERE 1=1"
    count_query = "SELECT COUNT(*) as count FROM products WHERE 1=1"
    params, count_params = [], []

    if category_slug:
        category_map = {"switches": 1, "transceivers": 2, "cables": 3}
        if category_slug in category_map:
            query += " AND category_id = ?"
            count_query += " AND category_id = ?"
            params.append(category_map[category_slug])
            count_params.append(category_map[category_slug])

    if vendor:
        query += " AND vendor = ?"
        count_query += " AND vendor = ?"
        params.append(vendor)
        count_params.append(vendor)

    if search:
        query += " AND (model_name LIKE ? OR part_number LIKE ? OR vendor LIKE ? OR description LIKE ?)"
        count_query += " AND (model_name LIKE ? OR part_number LIKE ? OR vendor LIKE ? OR description LIKE ?)"
        params.extend([f"%{search}%"] * 4)
        count_params.extend([f"%{search}%"] * 4)

    total = db.execute(count_query, count_params).fetchone()["count"]
    offset = (page - 1) * limit
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = db.execute(query, params)
    products = [dict(row) for row in cursor.fetchall()]
    
        # Добавляем дополнительные фото и их ID
    for p in products:
        img_cursor = db.execute("SELECT id, image_url FROM product_images WHERE product_id = ?", (p['id'],))
        imgs = img_cursor.fetchall()
        p['images'] = [row['image_url'] for row in imgs]
        p['image_ids'] = [row['id'] for row in imgs]
    
    return {"items": products, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/api/products")
async def create_product(
    vendor: str = Form(...),
    category_id: int = Form(...),
    model_name: str = Form(...),
    part_number: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    images: List[UploadFile] = File(default=[]), # Принимаем список файлов
    payload: dict = Depends(get_current_admin),
    db: sqlite3.Connection = Depends(get_db)
):
    # Первый файл — главное фото, остальные — галерея
    main_image_url = save_upload_image(images[0]) if images else None
    gallery_urls = [url for url in (save_upload_image(img) for img in images[1:]) if url]

    cursor = db.execute("""INSERT INTO products (category_id, vendor, model_name, part_number, description, price, image_url)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (category_id, vendor, model_name, part_number, description, price, main_image_url))
    prod_id = cursor.lastrowid

    for image_url in gallery_urls:
        db.execute("INSERT INTO product_images (product_id, image_url) VALUES (?, ?)",
                   (prod_id, image_url))

    db.commit()
    return {"message": "Товар успешно добавлен"}

@app.put("/api/products/{prod_id}")
async def update_product(
    prod_id: int,
    vendor: str = Form(...),
    category_id: int = Form(...),
    model_name: str = Form(...),
    part_number: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    images: List[UploadFile] = File(default=[]),
    payload: dict = Depends(get_current_admin),
    db: sqlite3.Connection = Depends(get_db)
):
    # Обновляем текстовые данные
    db.execute("""UPDATE products SET category_id=?, vendor=?, model_name=?, part_number=?, description=?, price=? WHERE id=?""",
               (category_id, vendor, model_name, part_number, description, price, prod_id))

    # Меняем главное фото (если передали новое) и удаляем старое с диска
    if images and images[0].filename:
        new_main = save_upload_image(images[0])
        if new_main:
            old = db.execute("SELECT image_url FROM products WHERE id = ?", (prod_id,)).fetchone()
            db.execute("UPDATE products SET image_url=? WHERE id=?", (new_main, prod_id))
            if old and old["image_url"]:
                delete_upload_file(old["image_url"])

    # Добавляем новые фото в галерею
    for img in images[1:]:
        image_url = save_upload_image(img)
        if image_url:
            db.execute("INSERT INTO product_images (product_id, image_url) VALUES (?, ?)",
                       (prod_id, image_url))

    db.commit()
    return {"message": "Товар обновлен"}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: int, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    # Собираем изображения товара, чтобы удалить и файлы с диска
    main = db.execute("SELECT image_url FROM products WHERE id = ?", (prod_id,)).fetchone()
    gallery = db.execute("SELECT image_url FROM product_images WHERE product_id = ?", (prod_id,)).fetchall()

    # Строки product_images удалятся каскадно (ON DELETE CASCADE)
    db.execute("DELETE FROM products WHERE id = ?", (prod_id,))
    db.commit()

    if main and main["image_url"]:
        delete_upload_file(main["image_url"])
    for row in gallery:
        delete_upload_file(row["image_url"])
    return {"message": "Товар успешно удален"}

# --- ЗАКАЗЫ ---
@app.post("/api/checkout")
def checkout(order: OrderCreate, payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    email = payload["sub"]
    if not order.items: raise HTTPException(400, "Корзина пуста")
    if len(order.items) > 100:
        raise HTTPException(400, "Слишком много позиций в заказе (максимум 100)")

    calculated_total = 0.0
    validated_items = []
    for item in order.items:
        prod_id = item.get("id")
        try:
            qty = int(item.get("quantity", 1))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректное количество товара")
        if qty <= 0:
            continue
        if qty > 1000:
            raise HTTPException(400, "Слишком большое количество товара (максимум 1000)")
        cursor = db.execute("SELECT price FROM products WHERE id = ?", (prod_id,))
        product = cursor.fetchone()
        if not product: raise HTTPException(400, f"Товар с ID {prod_id} не найден")
        calculated_total += product["price"] * qty
        validated_items.append((prod_id, qty, product["price"]))

    if not validated_items:
        raise HTTPException(400, "В заказе нет корректных товаров")

    phone = (order.phone or "").strip()
    address = (order.address or "").strip()
    if not phone or not address:
        raise HTTPException(400, "Укажите телефон и адрес доставки")

    db.execute("UPDATE users SET phone = ?, address = ? WHERE email = ?", (phone, address, email))
    cursor = db.execute("INSERT INTO orders (user_email, phone, address, total_price, status) VALUES (?, ?, ?, ?, 'В обработке')",
                        (email, phone, address, calculated_total))
    order_id = cursor.lastrowid
    for prod_id, qty, item_price in validated_items:
        db.execute("INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                   (order_id, prod_id, qty, item_price))
    db.commit()
    return {"message": "Заказ оформлен", "order_id": order_id}

@app.get("/api/orders/user")
def get_user_orders(payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT id, total_price, status, created_at FROM orders WHERE user_email = ? ORDER BY id DESC", (payload["sub"],))
    return [dict(row) for row in cursor.fetchall()]

@app.get("/api/orders")
def get_all_orders(payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT id, user_email, phone, address, total_price, status, created_at FROM orders ORDER BY id DESC")
    return [dict(row) for row in cursor.fetchall()]

@app.put("/api/orders/{order_id}/status")
def update_order_status(order_id: int, data: OrderStatusUpdate, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (data.status, order_id))
    db.commit()
    return {"message": "Статус изменен"}

@app.put("/api/orders/{order_id}/cancel")
def cancel_user_order(order_id: int, payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.execute("SELECT status, user_email FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    if not order: raise HTTPException(404, "Заказ не найден")
    if order['user_email'] != payload["sub"]: raise HTTPException(403, "Чужой заказ")
    if order['status'] != 'В обработке': raise HTTPException(400, "Нельзя отменить")
    db.execute("UPDATE orders SET status = 'Отменен' WHERE id = ?", (order_id,))
    db.commit()
    return {"message": "Заказ отменен"}

@app.delete("/api/images/{image_id}")
def delete_product_image(image_id: int, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    # Ищем картинку, чтобы удалить физический файл
    cursor = db.execute("SELECT image_url FROM product_images WHERE id = ?", (image_id,))
    img = cursor.fetchone()
    if img:
        db.execute("DELETE FROM product_images WHERE id = ?", (image_id,))
        db.commit()
        delete_upload_file(img["image_url"])
    return {"message": "Фотография удалена"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")