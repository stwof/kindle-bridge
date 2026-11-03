# Kindle Bridge 容器镜像（Debian/Ubuntu 系基础，Python 3.11 以兼容 Coqui TTS）
# 构建： docker build -t kindle-bridge .
# 运行： docker run -d --name kb -p 8765:8765 -v "$(pwd)/inbox:/app/inbox" -v "$(pwd)/export:/app/export" kindle-bridge
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com

# 编译依赖（TTS 的 C 扩展需要 gcc + python-dev）。
# 若需要 MOBI→EPUB 转换，请取消下一行 calibre 的注释（apt 体积较大，会显著增大镜像）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential python3-dev \
        # calibre \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-tts.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-tts.txt

COPY . .

# 容器场景监听所有网卡；如需仅本机，在 docker run 时改用 -p 127.0.0.1:8765:8765
EXPOSE 8765
CMD ["sh", "-c", "python app.py --host 0.0.0.0 --port 8765 --no-browser"]
