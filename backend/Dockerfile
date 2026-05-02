# 使用 Python 3.11 slim 镜像，体积较小，适合 FastAPI 异步服务部署。
FROM python:3.11-slim

# 让 Python 日志直接输出到 Docker 控制台，方便 docker logs 查看实时日志。
ENV PYTHONUNBUFFERED=1

# 让 Python 不生成 .pyc 缓存文件，保持容器文件系统更干净。
ENV PYTHONDONTWRITEBYTECODE=1

# 设置容器内部工作目录，后续命令都会在 /app 下执行。
WORKDIR /app

# 先复制依赖清单，利用 Docker 构建缓存加速重复安装。
COPY requirements.txt .

# 按 requirements.txt 安装依赖，后续新增依赖时只需要维护一个文件。
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端源码到镜像中。
# 当前第一步只搭基础设施，后续步骤会在 backend 目录中加入 app 代码。
COPY . .

# 声明后端服务监听端口。
EXPOSE 8000

# 默认启动命令。
# 当前后端入口为 backend/main.py 中的 app 实例。
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
