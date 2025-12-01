"""
Prome 后端 - WebSocket 服务
配合浏览器扩展使用的后端服务示例

安装依赖:
pip install fastapi uvicorn websockets python-jose

运行:
uvicorn websocket_server:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel
import json
import asyncio
import uuid
import os

app = FastAPI(title="Prome WebSocket Server")

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 选择器配置管理 ====================
# 当小红书更新DOM时，只需在这里更新选择器，所有扩展会自动同步

SELECTOR_CONFIG = {
    "version": "2024.12.01",
    "selectors": {
        "uploadInput": [
            'input[type="file"]',
            'input[accept*="image"]',
        ],
        "titleInput": [
            'input.d-text[placeholder*="标题"]',
            'input[placeholder*="填写标题"]',
            'input[placeholder*="标题"]',
            'input[maxlength="20"]',
        ],
        "contentArea": [
            '.tiptap.ProseMirror[role="textbox"]',
            '.ProseMirror[role="textbox"]',
            '[role="textbox"][contenteditable="true"]',
            '.tiptap[contenteditable="true"]',
        ],
        "publishBtn": [
            'button.publishBtn',
            'button:has-text("发布")',
        ],
        "topicBtn": [
            'button#topicBtn',
        ],
    },
    "updated_at": "2024-12-01T00:00:00Z"
}

# ==================== 数据模型 ====================

class PublishTask(BaseModel):
    id: str
    title: str
    content: str
    images: List[str] = []
    tags: List[str] = []
    scheduledTime: str
    status: str = "pending"
    createdAt: str = None
    completedAt: str = None
    error: str = None


class PublishRequest(BaseModel):
    title: str
    content: str
    images: List[str] = []
    tags: List[str] = []
    scheduledTime: Optional[str] = None


class SelectorUpdateRequest(BaseModel):
    version: str
    selectors: dict


# ==================== 连接管理 ====================

class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 用户ID -> WebSocket连接
        self.active_connections: Dict[str, WebSocket] = {}
        # 用户ID -> 发布任务队列
        self.publish_queues: Dict[str, List[PublishTask]] = {}
        # 用户ID -> 用户信息
        self.user_info: Dict[str, dict] = {}
    
    async def connect(self, user_id: str, websocket: WebSocket):
        """建立连接"""
        await websocket.accept()
        
        # 如果用户已有连接，断开旧连接
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].close()
            except:
                pass
        
        self.active_connections[user_id] = websocket
        if user_id not in self.publish_queues:
            self.publish_queues[user_id] = []
        print(f"User {user_id} connected. Total connections: {len(self.active_connections)}")
        
        # 发送当前选择器配置
        await self.send_message(user_id, {
            "type": "selector_config",
            "data": SELECTOR_CONFIG
        })
    
    def disconnect(self, user_id: str):
        """断开连接"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        print(f"User {user_id} disconnected. Total connections: {len(self.active_connections)}")
    
    def is_connected(self, user_id: str) -> bool:
        """检查用户是否在线"""
        return user_id in self.active_connections
    
    async def send_message(self, user_id: str, message: dict):
        """发送消息给指定用户"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_json(message)
                return True
            except Exception as e:
                print(f"Failed to send message to {user_id}: {e}")
                self.disconnect(user_id)
                return False
        return False
    
    async def broadcast(self, message: dict):
        """广播消息给所有用户"""
        disconnected = []
        for user_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(user_id)
        
        # 清理断开的连接
        for user_id in disconnected:
            self.disconnect(user_id)
    
    async def broadcast_selector_update(self):
        """广播选择器更新"""
        await self.broadcast({
            "type": "selector_config",
            "data": SELECTOR_CONFIG
        })
    
    def add_task(self, user_id: str, task: PublishTask):
        """添加发布任务"""
        if user_id not in self.publish_queues:
            self.publish_queues[user_id] = []
        self.publish_queues[user_id].append(task)
    
    def get_tasks(self, user_id: str) -> List[PublishTask]:
        """获取用户的发布任务"""
        return self.publish_queues.get(user_id, [])
    
    def update_task(self, user_id: str, task_id: str, updates: dict):
        """更新任务状态"""
        tasks = self.publish_queues.get(user_id, [])
        for task in tasks:
            if task.id == task_id:
                for key, value in updates.items():
                    setattr(task, key, value)
                return True
        return False
    
    def remove_task(self, user_id: str, task_id: str):
        """删除任务"""
        if user_id in self.publish_queues:
            self.publish_queues[user_id] = [
                t for t in self.publish_queues[user_id] if t.id != task_id
            ]


manager = ConnectionManager()


# ==================== Token验证 ====================

def verify_token(token: str) -> Optional[str]:
    """
    验证Token并返回用户ID
    实际项目中应该使用JWT或数据库验证
    """
    if token and (token.startswith("prome_") or token.startswith("pk_")):
        # 模拟验证：实际应该查询数据库
        return f"user_{token[-8:]}"
    return None


def get_user_from_header(authorization: str = Header(None), x_api_key: str = Header(None)):
    """从Header获取用户"""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif x_api_key:
        token = x_api_key
    
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication")
    
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return user_id


# ==================== WebSocket端点 ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    """WebSocket连接端点"""
    
    # 验证Token
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4002, reason="Invalid token")
        return
    
    # 建立连接
    await manager.connect(user_id, websocket)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            await handle_message(user_id, data)
            
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"WebSocket error for {user_id}: {e}")
        manager.disconnect(user_id)


async def handle_message(user_id: str, message: dict):
    """处理收到的WebSocket消息"""
    msg_type = message.get("type")
    data = message.get("data", {})
    
    print(f"Received from {user_id}: {msg_type}")
    
    if msg_type == "ping":
        # 心跳响应
        await manager.send_message(user_id, {"type": "pong"})
    
    elif msg_type == "publish_result":
        # 发布结果
        task_id = data.get("taskId")
        success = data.get("success")
        error_msg = data.get("message", "")
        
        manager.update_task(user_id, task_id, {
            "status": "completed" if success else "failed",
            "completedAt": datetime.now().isoformat(),
            "error": error_msg if not success else None
        })
        
        print(f"Task {task_id} {'completed' if success else 'failed'}: {error_msg}")
    
    elif msg_type == "login_status":
        # 小红书登录状态
        is_logged_in = data.get("isLoggedIn", False)
        manager.user_info[user_id] = {
            "xhs_logged_in": is_logged_in,
            "last_check": datetime.now().isoformat()
        }
        print(f"User {user_id} XHS login status: {is_logged_in}")
    
    elif msg_type == "get_selectors":
        # 扩展请求选择器配置
        await manager.send_message(user_id, {
            "type": "selector_config",
            "data": SELECTOR_CONFIG
        })


# ==================== HTTP API端点 ====================

@app.get("/")
async def root():
    """根路由"""
    return {
        "service": "Prome WebSocket Server",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/api/v1/status")
async def get_status():
    """获取服务状态"""
    return {
        "status": "ok",
        "connections": len(manager.active_connections),
        "version": "1.0.0",
        "selector_version": SELECTOR_CONFIG["version"]
    }


@app.get("/api/v1/selectors")
async def get_selectors():
    """获取当前选择器配置"""
    return SELECTOR_CONFIG


@app.put("/api/v1/selectors")
async def update_selectors(request: SelectorUpdateRequest, user_id: str = Depends(get_user_from_header)):
    """更新选择器配置（管理员接口）"""
    global SELECTOR_CONFIG
    
    SELECTOR_CONFIG["version"] = request.version
    SELECTOR_CONFIG["selectors"] = request.selectors
    SELECTOR_CONFIG["updated_at"] = datetime.now().isoformat()
    
    # 广播更新给所有连接的扩展
    await manager.broadcast_selector_update()
    
    return {"success": True, "message": "Selectors updated and broadcasted"}


@app.get("/api/v1/publish-plan")
async def get_publish_plan(user_id: str = Depends(get_user_from_header)):
    """获取发布计划"""
    tasks = manager.get_tasks(user_id)
    return {
        "tasks": [t.dict() for t in tasks]
    }


@app.post("/api/v1/publish")
async def create_publish_task(request: PublishRequest, user_id: str = Depends(get_user_from_header)):
    """创建发布任务"""
    
    # 检查用户是否在线
    if not manager.is_connected(user_id):
        raise HTTPException(
            status_code=400, 
            detail="浏览器扩展未连接，请确保扩展已安装并登录"
        )
    
    # 创建任务
    task = PublishTask(
        id=f"task_{uuid.uuid4().hex[:8]}",
        title=request.title,
        content=request.content,
        images=request.images,
        tags=request.tags,
        scheduledTime=request.scheduledTime or datetime.now().isoformat(),
        status="pending",
        createdAt=datetime.now().isoformat()
    )
    
    # 保存任务
    manager.add_task(user_id, task)
    
    # 判断是立即发布还是定时发布
    is_immediate = not request.scheduledTime
    if not is_immediate:
        try:
            scheduled_time = datetime.fromisoformat(request.scheduledTime.replace('Z', '+00:00'))
            is_immediate = scheduled_time <= datetime.now(scheduled_time.tzinfo) if scheduled_time.tzinfo else scheduled_time <= datetime.now()
        except:
            is_immediate = True
    
    if is_immediate:
        # 立即发布
        task.status = "executing"
        await manager.send_message(user_id, {
            "type": "publish",
            "data": task.dict()
        })
        return {
            "success": True,
            "task": task.dict(),
            "message": "正在发布..."
        }
    else:
        # 定时发布
        return {
            "success": True,
            "task": task.dict(),
            "message": f"已添加到发布计划，将在 {request.scheduledTime} 发布"
        }


@app.delete("/api/v1/publish/{task_id}")
async def cancel_publish_task(task_id: str, user_id: str = Depends(get_user_from_header)):
    """取消发布任务"""
    
    # 删除任务
    manager.remove_task(user_id, task_id)
    
    # 通知扩展取消任务
    if manager.is_connected(user_id):
        await manager.send_message(user_id, {
            "type": "cancel_task",
            "data": {"taskId": task_id}
        })
    
    return {"success": True}


@app.get("/api/v1/user/status")
async def get_user_status(user_id: str = Depends(get_user_from_header)):
    """获取用户状态"""
    return {
        "userId": user_id,
        "isConnected": manager.is_connected(user_id),
        "xhsStatus": manager.user_info.get(user_id, {}),
        "pendingTasks": len([t for t in manager.get_tasks(user_id) if t.status == "pending"]),
        "selectorVersion": SELECTOR_CONFIG["version"]
    }


@app.post("/api/v1/check-xhs-login")
async def request_xhs_login_check(user_id: str = Depends(get_user_from_header)):
    """请求扩展检查小红书登录状态"""
    if not manager.is_connected(user_id):
        raise HTTPException(status_code=400, detail="扩展未连接")
    
    await manager.send_message(user_id, {
        "type": "check_login"
    })
    
    return {"success": True, "message": "已请求检查登录状态"}


# ==================== 定时任务检查 ====================

async def check_scheduled_tasks():
    """检查并执行到期的定时任务"""
    while True:
        await asyncio.sleep(30)  # 每30秒检查一次
        
        now = datetime.now()
        
        for user_id, tasks in list(manager.publish_queues.items()):
            for task in tasks:
                if task.status != "pending":
                    continue
                
                try:
                    # 解析时间
                    scheduled_str = task.scheduledTime.replace('Z', '+00:00')
                    scheduled_time = datetime.fromisoformat(scheduled_str)
                    
                    # 移除时区信息进行比较（简化处理）
                    if scheduled_time.tzinfo:
                        scheduled_time = scheduled_time.replace(tzinfo=None)
                    
                    if scheduled_time <= now:
                        # 时间到，执行发布
                        task.status = "executing"
                        
                        if manager.is_connected(user_id):
                            await manager.send_message(user_id, {
                                "type": "publish",
                                "data": task.dict()
                            })
                            print(f"Executing scheduled task {task.id} for user {user_id}")
                        else:
                            task.status = "failed"
                            task.error = "用户离线，无法执行"
                            print(f"User {user_id} offline, task {task.id} failed")
                            
                except Exception as e:
                    print(f"Error checking task {task.id}: {e}")


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    # 启动定时任务检查
    asyncio.create_task(check_scheduled_tasks())
    print("Server started, scheduled task checker running")
    print(f"Selector version: {SELECTOR_CONFIG['version']}")


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
