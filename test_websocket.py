#!/usr/bin/env python3
"""
WebSocket 连接测试脚本
测试 Chrome 扩展的 WebSocket 端点是否正常工作
"""

import asyncio
import websockets
import json
import sys

# 配置
BACKEND_URL = "ws://localhost:8000/ws"  # 本地测试
# BACKEND_URL = "wss://xiaohongshu-worker.zeabur.app/ws"  # 生产环境

# Token（使用你的 WORKER_SECRET 或 ext_user_id）
TOKEN = "ext_test_user"


async def test_websocket():
    """测试 WebSocket 连接"""
    url = f"{BACKEND_URL}?token={TOKEN}"
    
    print(f"🔌 尝试连接到: {url}")
    
    try:
        async with websockets.connect(url) as websocket:
            print("✅ WebSocket 连接成功！\n")
            
            # 测试 1: 发送心跳
            print("📡 测试 1: 心跳测试")
            await websocket.send(json.dumps({"type": "ping"}))
            response = await websocket.recv()
            print(f"   收到响应: {response}")
            
            data = json.loads(response)
            if data.get("type") == "pong":
                print("   ✅ 心跳测试成功\n")
            else:
                print("   ❌ 心跳响应异常\n")
            
            # 测试 2: 模拟发布结果
            print("📡 测试 2: 发送发布结果")
            publish_result = {
                "type": "publish_result",
                "data": {
                    "taskId": "test_task_123",
                    "success": True,
                    "message": "测试发布成功",
                    "timestamp": "2024-12-01T10:00:00"
                }
            }
            await websocket.send(json.dumps(publish_result))
            print(f"   发送: {json.dumps(publish_result, ensure_ascii=False)}")
            print("   ✅ 发布结果发送成功\n")
            
            # 测试 3: 模拟登录状态报告
            print("📡 测试 3: 发送登录状态")
            login_status = {
                "type": "login_status",
                "data": {
                    "isLoggedIn": True,
                    "cookies": ["web_session", "a1", "xsec_token"]
                }
            }
            await websocket.send(json.dumps(login_status))
            print(f"   发送: {json.dumps(login_status, ensure_ascii=False)}")
            print("   ✅ 登录状态发送成功\n")
            
            print("🎉 所有测试通过！WebSocket 工作正常。")
            print("\n💡 下一步：")
            print("   1. 在 Chrome 中加载扩展")
            print("   2. 使用相同的 token 连接")
            print("   3. 测试完整的发布流程")
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ 连接失败: HTTP {e.status_code}")
        print(f"   可能的原因:")
        print(f"   - Token 无效: {TOKEN}")
        print(f"   - 后端未运行")
        print(f"   - URL 配置错误")
        sys.exit(1)
        
    except ConnectionRefusedError:
        print("❌ 连接被拒绝")
        print("   请确保后端正在运行:")
        print("   cd /Users/boliu/promeplatform&xiaohongshu/xhs-worker")
        print("   uvicorn main:app --reload --port 8000")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 60)
    print("WebSocket 连接测试工具")
    print("=" * 60)
    print()
    
    try:
        asyncio.run(test_websocket())
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
