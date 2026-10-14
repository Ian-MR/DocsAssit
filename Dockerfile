FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y sqlite3 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir torch \
	--index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY storage/ ./storage/

RUN mkdir -p docs raws normalizeds chunks

ENTRYPOINT ["python", "src/main.py"]
