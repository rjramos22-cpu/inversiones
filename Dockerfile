FROM python:3.11-slim

WORKDIR /app

COPY requirements_bot.txt .
RUN pip install --no-cache-dir -r requirements_bot.txt

COPY . .

CMD ["python", "investment_bot.py"]