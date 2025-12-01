#!/bin/bash
# 快速启动脚本 - 启动后端服务并测试 WebSocket

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Prome 小红书助手 - 后端启动脚本${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# 检查依赖
echo -e "${YELLOW}📦 检查依赖...${NC}"
if ! pip show websockets &> /dev/null; then
    echo -e "${RED}❌ websockets 未安装${NC}"
    echo -e "${YELLOW}正在安装依赖...${NC}"
    pip install -r requirements.txt
else
    echo -e "${GREEN}✅ 依赖已安装${NC}"
fi
echo ""

# 启动后端
echo -e "${YELLOW}🚀 启动后端服务...${NC}"
echo -e "${BLUE}端口: 8000${NC}"
echo -e "${BLUE}WebSocket: ws://localhost:8000/ws${NC}"
echo ""
echo -e "${YELLOW}按 Ctrl+C 停止服务${NC}"
echo ""
echo -e "${BLUE}================================================${NC}"
echo ""

# 启动 uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
