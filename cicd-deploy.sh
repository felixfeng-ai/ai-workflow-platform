#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# 雅秩 - CI/CD 部署脚本（Docker 化）
# ════════════════════════════════════════════════════════════════
# 由 GitHub Actions（.github/workflows/deploy.yml）经 SSH 调用：
#   bash /opt/projecthub-ai/cicd-deploy.sh
# 也可手动执行：cd /opt/projecthub-ai && sudo bash cicd-deploy.sh
#
# 前置条件（首次部署手动完成，见 DEPLOYMENT.md）：
#   - Docker Engine + docker compose plugin 已安装
#   - 仓库已 clone 到 /opt/projecthub-ai
#   - /opt/projecthub-ai/.env 已按 .env.example 配置
#   - 部署流水线提供 PROJECTHUB_GITHUB_DEPLOY_TOKEN 时，脚本会同步平台级部署 Token
#
# 回滚：git reset --hard <上一提交> && bash cicd-deploy.sh
# ════════════════════════════════════════════════════════════════

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_step() { echo -e "\n${GREEN}━━━ $1 ━━━${NC}"; }
print_info() { echo -e "  ${YELLOW}→${NC} $1"; }
print_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
print_err()  { echo -e "  ${RED}✗${NC} $1"; }

PROJECT_DIR="/opt/projecthub-ai"
COMPOSE="docker compose"
HEALTH_URL="http://127.0.0.1:8080/health"   # 网关入口端口与 docker-compose.yml 保持一致

# ════════════════════════════════════════════════════════════════
# 第一步：环境检查
# ════════════════════════════════════════════════════════════════
print_step "环境检查"

if [ "$(id -u)" -ne 0 ]; then
    print_err "请用 root 运行（sudo bash cicd-deploy.sh）"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    print_err "未安装 Docker，请按 DEPLOYMENT.md 首次部署清单安装"
    exit 1
fi

if ! command -v git &> /dev/null; then
    print_err "未安装 git"
    exit 1
fi

print_ok "Docker：$(docker --version 2>/dev/null)"
print_ok "Compose：$(docker compose version 2>/dev/null | head -1)"

if [ ! -d "$PROJECT_DIR/.git" ]; then
    print_err "$PROJECT_DIR 不是 git 仓库，请先 clone：git clone <你的私有仓库> $PROJECT_DIR"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    print_err "$PROJECT_DIR/.env 不存在，请先 cp .env.example .env 并填入配置"
    exit 1
fi

cd "$PROJECT_DIR"

# 平台级 GitHub 部署凭据由 GitHub Actions Secret 注入，用户无需为每个项目手工配置。
# 只更新 .env 中的单个键，不打印 Token。
if [ -n "${PROJECTHUB_GITHUB_DEPLOY_TOKEN:-}" ]; then
    print_info "同步平台级 GitHub 部署凭据..."
    TMP_ENV=$(mktemp)
    awk -v token="$PROJECTHUB_GITHUB_DEPLOY_TOKEN" '
        BEGIN { found = 0 }
        /^GITHUB_DEPLOY_TOKEN=/ {
            print "GITHUB_DEPLOY_TOKEN=" token
            found = 1
            next
        }
        { print }
        END {
            if (!found) print "GITHUB_DEPLOY_TOKEN=" token
        }
    ' "$PROJECT_DIR/.env" > "$TMP_ENV"
    mv "$TMP_ENV" "$PROJECT_DIR/.env"
    chmod 600 "$PROJECT_DIR/.env"
    print_ok "平台级 GitHub 部署凭据已更新"
fi

# ════════════════════════════════════════════════════════════════
# 第二步：拉取最新代码（5 次重试）
# ════════════════════════════════════════════════════════════════
print_step "拉取最新代码"

for i in $(seq 1 5); do
    if git fetch origin main && git reset --hard origin/main; then
        print_ok "代码已更新到 $(git rev-parse --short HEAD)"
        break
    fi
    if [ "$i" -eq 5 ]; then
        print_err "git fetch/reset 连续 5 次失败，中止部署"
        exit 1
    fi
    print_info "第 $i 次拉取失败，3 秒后重试..."
    sleep 3
done

# ════════════════════════════════════════════════════════════════
# 第三步：构建并启动核心服务（Dify 不在核心 compose 内，默认不启动）
# ════════════════════════════════════════════════════════════════
print_step "构建并启动服务"

print_info "构建镜像..."
$COMPOSE build

print_info "启动服务..."
$COMPOSE up -d --build --remove-orphans

print_ok "服务已启动"

# ════════════════════════════════════════════════════════════════
# 第四步：等待后端健康（最长 ~120s）
# 后端 entrypoint 会先跑 alembic upgrade head 再启动，需要等待迁移完成
# ════════════════════════════════════════════════════════════════
print_step "等待后端健康"

healthy=""
for i in $(seq 1 24); do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        healthy="yes"
        break
    fi
    if [ "$i" -eq 24 ]; then
        print_err "后端 120s 内未就绪，查看日志："
        $COMPOSE logs --tail=50 backend
        exit 1
    fi
    print_info "等待就绪（${i}/24，每 5s 一次）..."
    sleep 5
done

if [ -n "$healthy" ]; then
    BODY=$(curl -sf "$HEALTH_URL" || echo "{}")
    print_ok "后端健康：$BODY"
fi

# ════════════════════════════════════════════════════════════════
# 第五步：整体状态检查
# ════════════════════════════════════════════════════════════════
print_step "服务状态"

for service in postgres redis backend frontend nginx; do
    STATUS=$($COMPOSE ps "$service" --format "{{.Status}}" 2>/dev/null || echo "unknown")
    if echo "$STATUS" | grep -qE "Up|healthy"; then
        print_ok "$service：$STATUS"
    else
        print_err "$service：$STATUS"
        $COMPOSE logs --tail=30 "$service"
    fi
done

# 校验业务 API 已被网关接管（未登录应返回 401 而非 404）
API_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/api/projects 2>/dev/null || echo "000")
if [ "$API_CODE" = "401" ]; then
    print_ok "网关 /api/ 已接管（401 未授权，符合预期）"
else
    print_err "网关 /api/ 返回 $API_CODE（预期 401），请检查 nginx 与 backend"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  雅秩 部署完成！${NC}"
echo -e "${GREEN}  入口：http://服务器IP:8080/ （HTTPS 按 DEPLOYMENT.md 启用）${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "常用命令："
echo "  查看日志：    docker compose logs -f"
echo "  查看后端日志：docker compose logs -f backend"
echo "  重启服务：    docker compose restart"
echo "  停止服务：    docker compose down"
echo "  回滚：        git reset --hard <上一提交> && bash cicd-deploy.sh"
echo ""
