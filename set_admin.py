import sqlite3
from passlib.context import CryptContext

# Настраиваем алгоритм шифрования
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Генерируем хэш для нового простого пароля
new_password = "admin"
new_hash = pwd_context.hash(new_password)
new_email = "admin@mail.ru"

# Подключаемся к базе и обновляем запись администратора (ищем по роли)
with sqlite3.connect("DataBase.db") as conn:
    conn.execute(
        "UPDATE users SET email = ?, password_hash = ? WHERE role = 'admin'", 
        (new_email, new_hash)
    )
    conn.commit()

print(f"Данные администратора успешно обновлены!\nЛогин (Email): {new_email}\nПароль: {new_password}")