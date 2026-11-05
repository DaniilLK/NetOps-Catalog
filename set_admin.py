import os
import sqlite3
from passlib.context import CryptContext

# Настраиваем алгоритм шифрования
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Учётные данные администратора берём из окружения (без хардкода в репозитории)
new_email = os.getenv("ADMIN_EMAIL", "admin@mail.ru")
new_password = os.getenv("ADMIN_PASSWORD")

if not new_password:
    raise SystemExit("Задайте ADMIN_PASSWORD в окружении (и при необходимости ADMIN_EMAIL).")

if len(new_password) < 8:
    raise SystemExit("ADMIN_PASSWORD должен быть не короче 8 символов.")

new_hash = pwd_context.hash(new_password)

# Подключаемся к базе и обновляем запись администратора (ищем по роли)
with sqlite3.connect("DataBase.db") as conn:
    cursor = conn.execute(
        "UPDATE users SET email = ?, password_hash = ? WHERE role = 'admin'",
        (new_email, new_hash)
    )
    updated = cursor.rowcount
    conn.commit()

if updated == 0:
    print("Пользователь с ролью 'admin' не найден — ничего не обновлено.")
else:
    print(f"Данные администратора обновлены. Логин (Email): {new_email}")