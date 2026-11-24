FROM python:3.14

RUN apt-get update && apt-get install -y \
    python3-tk \
    tk \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

CMD ["python3", "main.py"]

