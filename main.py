from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
import sqlite3
import jwt
import random
import re
from datetime import datetime, timedelta
from passlib.context import CryptContext
import shutil
import os
import uuid
from typing import Optional, List

from database import get_db, init_db

init_db()

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_network_key_do_not_share")
ALGORITHM = "HS256"

app = FastAPI(title="Network Equipment API (Secure)")
os.makedirs("static/uploads", exist_ok=True)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- МОДЕЛИ ДАННЫХ ---
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Пароль минимум 8 символов")

    @field_validator('password')
    def validate_password(cls, v):
        if not re.search(r'[A-Za-z]', v) or not re.search(r'\d', v):
            raise ValueError('Пароль должен содержать хотя бы одну букву и одну цифру')
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    username: str
    phone: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = None

class UserAdminUpdate(BaseModel):
    email: EmailStr
    username: str
    role: str
    phone: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = None

class OrderCreate(BaseModel):
    phone: str
    address: str
    items: list[dict] 

class OrderStatusUpdate(BaseModel):
    status: str


# --- БЕЗОПАСНОСТЬ ---
def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Отсутствует или неверный формат токена")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Срок действия токена истек")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Невалидный токен")

def get_current_admin(payload: dict = Depends(get_current_user)):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    return payload


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
def login(user: UserLogin, db: sqlite3.Connection = Depends(get_db)):
    email = user.email.lower().strip()
    cursor = db.execute("SELECT * FROM users WHERE email = ?", (email,))
    db_user = cursor.fetchone()
    if not db_user or not pwd_context.verify(user.password, db_user['password_hash']):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    
    token_data = {"sub": db_user['email'], "role": db_user['role'], "exp": datetime.utcnow() + timedelta(hours=24)}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "role": db_user['role'], "username": db_user['username']}

@app.get("/api/profile")
def get_profile(payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    email = payload["sub"]
    cursor = db.execute("SELECT email, username, phone, address FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    return dict(user) if user else {}

@app.put("/api/profile")
def update_profile(data: UserUpdate, payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    email = payload["sub"]
    try:
        if data.password:
            if len(data.password) < 8 or not re.search(r'[A-Za-z]', data.password) or not re.search(r'\d', data.password):
                raise HTTPException(status_code=400, detail="Новый пароль слишком простой")
            hashed_password = pwd_context.hash(data.password)
            db.execute("UPDATE users SET username=?, password_hash=?, phone=?, address=? WHERE email=?", 
                      (data.username, hashed_password, data.phone, data.address, email))
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
def update_user_by_admin(user_id: int, data: UserAdminUpdate, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    try:
        if data.password:
            hashed_password = pwd_context.hash(data.password)
            db.execute("UPDATE users SET email=?, username=?, role=?, password_hash=?, phone=?, address=? WHERE id=?", 
                       (data.email.lower().strip(), data.username, data.role, hashed_password, data.phone, data.address, user_id))
        else:
            db.execute("UPDATE users SET email=?, username=?, role=?, phone=?, address=? WHERE id=?", 
                       (data.email.lower().strip(), data.username, data.role, data.phone, data.address, user_id))
        db.commit()
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
        query += " AND (model_name LIKE ? OR part_number LIKE ?)"
        count_query += " AND (model_name LIKE ? OR part_number LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
        count_params.extend([f"%{search}%", f"%{search}%"])

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
    main_image_url = None
    # Если передали файлы, первый считаем главным
    if images and len(images) > 0 and images[0].filename:
        ext = os.path.splitext(images[0].filename)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            safe_filename = f"{uuid.uuid4().hex}{ext}"
            with open(f"static/uploads/{safe_filename}", "wb") as buffer:
                shutil.copyfileobj(images[0].file, buffer)
            main_image_url = f"/uploads/{safe_filename}"

    cursor = db.execute("""INSERT INTO products (category_id, vendor, model_name, part_number, description, price, image_url) 
                           VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                        (category_id, vendor, model_name, part_number, description, price, main_image_url))
    prod_id = cursor.lastrowid

    # Остальные файлы сохраняем в таблицу product_images
    for img in images[1:]:
        if img.filename:
            ext = os.path.splitext(img.filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                safe_filename = f"{uuid.uuid4().hex}{ext}"
                with open(f"static/uploads/{safe_filename}", "wb") as buffer:
                    shutil.copyfileobj(img.file, buffer)
                db.execute("INSERT INTO product_images (product_id, image_url) VALUES (?, ?)", 
                           (prod_id, f"/uploads/{safe_filename}"))
                           
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

    if images and len(images) > 0 and images[0].filename:
        # Меняем главное фото
        ext = os.path.splitext(images[0].filename)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            safe_filename = f"{uuid.uuid4().hex}{ext}"
            with open(f"static/uploads/{safe_filename}", "wb") as buffer:
                shutil.copyfileobj(images[0].file, buffer)
            db.execute("UPDATE products SET image_url=? WHERE id=?", (f"/uploads/{safe_filename}", prod_id))
            
        # Добавляем новые в галерею
        for img in images[1:]:
            if img.filename:
                ext = os.path.splitext(img.filename)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    safe_filename = f"{uuid.uuid4().hex}{ext}"
                    with open(f"static/uploads/{safe_filename}", "wb") as buffer:
                        shutil.copyfileobj(img.file, buffer)
                    db.execute("INSERT INTO product_images (product_id, image_url) VALUES (?, ?)", 
                               (prod_id, f"/uploads/{safe_filename}"))
                               
    db.commit()
    return {"message": "Товар обновлен"}

@app.delete("/api/products/{prod_id}")
def delete_product(prod_id: int, payload: dict = Depends(get_current_admin), db: sqlite3.Connection = Depends(get_db)):
    # Каскадное удаление картинок произойдет автоматически (ON DELETE CASCADE)
    db.execute("DELETE FROM products WHERE id = ?", (prod_id,))
    db.commit()
    return {"message": "Товар успешно удален"}

# --- ЗАКАЗЫ ---
@app.post("/api/checkout")
def checkout(order: OrderCreate, payload: dict = Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    email = payload["sub"]
    if not order.items: raise HTTPException(400, "Корзина пуста")

    calculated_total = 0.0
    validated_items = []
    for item in order.items:
        prod_id = item.get("id")
        qty = item.get("quantity", 1)
        if qty <= 0: continue
        cursor = db.execute("SELECT price FROM products WHERE id = ?", (prod_id,))
        product = cursor.fetchone()
        if not product: raise HTTPException(400, f"Товар с ID {prod_id} не найден")
        calculated_total += product["price"] * qty
        validated_items.append((prod_id, qty, product["price"]))

    db.execute("UPDATE users SET phone = ?, address = ? WHERE email = ?", (order.phone, order.address, email))
    cursor = db.execute("INSERT INTO orders (user_email, phone, address, total_price, status) VALUES (?, ?, ?, ?, 'В обработке')",
                        (email, order.phone, order.address, calculated_total))
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
        # Удаляем из базы
        db.execute("DELETE FROM product_images WHERE id = ?", (image_id,))
        db.commit()
        # Пытаемся удалить файл с диска (если он там есть)
        try:
            filepath = img["image_url"].lstrip("/") # убираем первый слэш
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
    return {"message": "Фотография удалена"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")