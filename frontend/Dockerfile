# 使用 Node.js 20 构建 Vue 3 + Vite 前端产物。
FROM node:20 AS builder

# 设置前端构建工作目录。
WORKDIR /app

# 先复制依赖清单，利用 Docker 构建缓存加速重复安装。
# package-lock.json 不一定在第一步存在，所以使用通配符兼容后续 npm lock 文件。
COPY package*.json ./

# 安装前端依赖。
# npm ci 更适合 CI/CD；当 package-lock.json 尚未生成时，回退到 npm install。
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# 复制前端源码。
COPY . .

# 构建静态产物，Vite 默认输出到 dist 目录。
RUN npm run build

# 使用 nginx:alpine 托管构建后的静态文件，体积小、启动快。
FROM nginx:alpine

# 复制自定义 nginx 配置，解决 Vue history 路由刷新 404。
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制上一阶段生成的 dist 静态产物到 Nginx 默认站点目录。
COPY --from=builder /app/dist /usr/share/nginx/html

# 声明前端服务监听端口。
EXPOSE 80

# 使用 Nginx 前台模式启动，符合 Docker 容器进程模型。
CMD ["nginx", "-g", "daemon off;"]
