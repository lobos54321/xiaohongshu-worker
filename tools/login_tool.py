#!/usr/bin/env python3
"""
小红书本地登录工具
用于提取完整的Cookie（包括HttpOnly）并上传到后端服务器

使用方法：
    python login_tool.py --user-id YOUR_USER_ID --backend-url https://your-backend.com
"""

import os
import sys
import time
import json
import argparse
import requests
from pathlib import Path

# 添加父目录到路径以便导入core模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from DrissionPage import ChromiumPage, ChromiumOptions


class LoginTool:
    def __init__(self, user_id: str, backend_url: str, worker_secret: str = None):
        self.user_id = user_id
        self.backend_url = backend_url.rstrip('/')
        self.worker_secret = worker_secret or os.getenv('WORKER_SECRET', '')
        self.page = None
        
    def start_browser(self):
        """启动可见浏览器"""
        print("🚀 正在启动浏览器...")
        
        co = ChromiumOptions()
        co.headless(False)  # 可见模式
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_user_agent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        
        self.page = ChromiumPage(co)
        print("✅ 浏览器已启动")
        
    def navigate_to_login(self):
        """导航到登录页面"""
        print("🌐 正在打开小红书创作者平台...")
        self.page.get("https://creator.xiaohongshu.com/login")
        time.sleep(3)
        print("✅ 登录页面已打开")
        
    def wait_for_login(self, timeout=300):
        """等待用户登录成功"""
        print("\n" + "="*60)
        print("📱 请在浏览器中扫码登录小红书")
        print("="*60)
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            current_url = self.page.url
            
            # 检查是否登录成功（URL包含creator且不是login页面）
            if 'creator.xiaohongshu.com' in current_url and 'login' not in current_url:
                print("\n✅ 检测到登录成功！")
                return True
            
            # 或者检查特定元素
            try:
                # 检查是否有用户头像或其他登录后才有的元素
                if self.page.ele('css:.user-info', timeout=1) or \
                   self.page.ele('css:.avatar', timeout=1) or \
                   'creator/home' in current_url or \
                   'creator/publish' in current_url:
                    print("\n✅ 检测到登录成功！")
                    return True
            except:
                pass
            
            # 显示等待进度
            elapsed = int(time.time() - start_time)
            remaining = timeout - elapsed
            print(f"\r⏳ 等待登录中... ({elapsed}s / {timeout}s)", end='', flush=True)
            
            time.sleep(2)
        
        print("\n\n❌ 登录超时！请重新运行工具。")
        return False
        
    def extract_cookies(self):
        """提取所有Cookie（包括HttpOnly）"""
        print("\n🍪 正在提取Cookie...")
        
        try:
            # DrissionPage的cookies()方法可以获取所有Cookie，包括HttpOnly
            cookies = self.page.cookies(all_domains=True, all_info=True)
            
            # 过滤只保留xiaohongshu.com相关的Cookie
            xhs_cookies = [c for c in cookies if 'xiaohongshu' in c.get('domain', '')]
            
            print(f"✅ 成功提取 {len(xhs_cookies)} 个Cookie")
            print(f"📝 Cookie名称: {[c['name'] for c in xhs_cookies[:10]]}")  # 只显示前10个
            
            return xhs_cookies
            
        except Exception as e:
            print(f"❌ 提取Cookie失败: {e}")
            return []
    
    def upload_cookies(self, cookies):
        """上传Cookie到后端"""
        print("\n📤 正在上传Cookie到后端...")
        
        # 获取User-Agent
        ua = self.page.run_js('return navigator.userAgent')
        
        # 准备数据
        data = {
            "user_id": self.user_id,
            "cookies": cookies,
            "ua": ua
        }
        
        # 准备请求头
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.worker_secret:
            headers["Authorization"] = f"Bearer {self.worker_secret}"
        
        try:
            # 发送请求
            response = requests.post(
                f"{self.backend_url}/api/v1/login/sync-complete",
                json=data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Cookie上传成功！")
                print(f"📝 服务器响应: {result.get('message', 'Success')}")
                return True
            else:
                print(f"❌ 上传失败: HTTP {response.status_code}")
                print(f"   响应内容: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 上传请求失败: {e}")
            return False
    
    def cleanup(self):
        """清理浏览器"""
        if self.page:
            print("\n🧹 正在关闭浏览器...")
            try:
                self.page.quit()
                print("✅ 浏览器已关闭")
            except:
                pass
    
    def run(self):
        """执行完整流程"""
        try:
            # 1. 启动浏览器
            self.start_browser()
            
            # 2. 导航到登录页
            self.navigate_to_login()
            
            # 3. 等待用户登录
            if not self.wait_for_login():
                return False
            
            # 4. 提取Cookie
            cookies = self.extract_cookies()
            if not cookies:
                print("❌ 未能提取到有效的Cookie")
                return False
            
            # 5. 上传到后端
            if not self.upload_cookies(cookies):
                print("❌ Cookie上传失败")
                return False
            
            print("\n" + "="*60)
            print("🎉 设置完成！您现在可以使用全自动运营模式了")
            print("="*60)
            
            return True
            
        except KeyboardInterrupt:
            print("\n\n⚠️ 用户取消操作")
            return False
            
        except Exception as e:
            print(f"\n\n❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        finally:
            self.cleanup()


def main():
    parser = argparse.ArgumentParser(
        description='小红书本地登录工具 - 用于全自动运营模式',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
    python login_tool.py --user-id user_123 --backend-url https://your-backend.com
    
环境变量:
    WORKER_SECRET - 后端认证密钥（可选，也可以在后端环境变量中配置）
        """
    )
    
    parser.add_argument(
        '--user-id',
        required=True,
        help='用户ID（从Prome平台获取）'
    )
    
    parser.add_argument(
        '--backend-url',
        required=True,
        help='后端API地址（例如: https://xiaohongshu-worker.zeabur.app）'
    )
    
    parser.add_argument(
        '--worker-secret',
        help='后端认证密钥（可选）',
        default=None
    )
    
    args = parser.parse_args()
    
    # 打印欢迎信息
    print("\n" + "="*60)
    print("  小红书本地登录工具 - 全自动运营模式设置")
    print("="*60)
    print(f"\n用户ID: {args.user_id}")
    print(f"后端地址: {args.backend_url}")
    print()
    
    # 创建工具实例并运行
    tool = LoginTool(
        user_id=args.user_id,
        backend_url=args.backend_url,
        worker_secret=args.worker_secret
    )
    
    success = tool.run()
    
    # 返回适当的退出码
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
