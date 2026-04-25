FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY main.py .

# Создаём непривилегированного пользователя для безопасности
RUN useradd -m -u 1000 baruser && chown -R baruser:baruser /app
USER baruser

EXPOSE 8000

# Запускаем приложение
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]