# 前端构建容器：node 编译 Vite 产物 → 同步进共享卷 /srv/frontend，供 Caddy 静态托管。
# 让部署可复现，无需在主机预先 npm run build。
# compose 中以一次性服务运行，Caddy 用 depends_on service_completed_successfully 等其完成。
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# 多租户白标：构建期注入品牌（Vite 读取 VITE_* 环境变量进 import.meta.env）。默认=北京合胜+显示 logo。
ARG VITE_BRAND_NAME=北京合胜
ARG VITE_SHOW_LOGO=true
ENV VITE_BRAND_NAME=$VITE_BRAND_NAME VITE_SHOW_LOGO=$VITE_SHOW_LOGO
RUN npm run build
# 一次性：清空并把 dist 复制进挂载的共享卷后退出
CMD ["sh", "-c", "rm -rf /srv/frontend/* && cp -r /app/dist/. /srv/frontend/ && echo 'frontend dist published to /srv/frontend'"]
