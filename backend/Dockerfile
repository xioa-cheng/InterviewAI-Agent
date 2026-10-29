FROM python:3.12-slim

WORKDIR /app

# 安装 tesseract OCR（用于扫描件 PDF / 图片简历的文字识别）
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖以利用 Docker 层缓存
COPY requirements.txt .
# 国内 pip 镜像源，加速 langchain/chromadb/mcp 等大体量依赖安装（如不需要可删除此行）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir --default-timeout=120 -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
