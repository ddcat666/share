# AI 量化交易模拟平台

## 开发环境要求

- **后端**: Python >= 3.10
- **前端**: Node.js (推荐 18+), pnpm
- **数据库**: MySQL 8.0, Redis 7
- **可选**: Docker & Docker Compose

## 本地启动

### 方式一：Docker Compose（推荐）

```bash
# 启动 MySQL 和 Redis
docker-compose up -d mysql redis

# 查看服务状态
docker-compose ps
```

数据库默认端口：MySQL `13306`，Redis `16379`

### 方式二：手动安装数据库

自行安装 MySQL 和 Redis，确保服务运行中。

---

### 启动后端

```bash
cd backend

# 配置环境变量
cp .env.example .env
# 编辑 .env 填写数据库连接信息和 LLM API Key

# 安装依赖
pip install -e .

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API: http://localhost:8000

### 启动前端

```bash
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器
pnpm dev
```

前端页面: http://localhost:5173
