# 开发模式镜像（MVP）。生产可改多阶段构建 + next start。
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
# 国内网络用 npmmirror 加速；海外可删掉 --registry
RUN npm install --registry=https://registry.npmmirror.com

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
