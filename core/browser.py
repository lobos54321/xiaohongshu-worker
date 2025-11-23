import os
import time
import shutil
import random
from DrissionPage import ChromiumPage, ChromiumOptions
from pyvirtualdisplay import Display
from .utils import download_video

class BrowserManager:
    def __init__(self, user_id: str):
        self.user_id = user_id
        # === Enterprise Design: User Data Isolation ===
        # Each user's data is stored in a separate directory
        # In Zeabur, /app/data needs to be a mounted Volume
        self.user_data_dir = f"/app/data/users/{user_id}"
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.page = None
        self.display = None

    def _get_options(self, proxy_url: str = None, user_agent: str = None):
        co = ChromiumOptions()
        # Linux Environment Configuration
        co.set_browser_path('/usr/bin/chromium')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-dev-shm-usage')
        
        # === 1. Security: Proxy Injection ===
        if proxy_url:
            co.set_proxy(proxy_url)
            
        # === 2. Security: User Agent & Fingerprint ===
        if user_agent:
            co.set_user_agent(user_agent)
        else:
            # Default fallback UA if none provided
            co.set_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        # Key: Point to user-specific directory
        co.set_user_data_path(self.user_data_dir)
        co.auto_port()  # Auto-assign debug port for concurrency
        co.headless(True) # Must enable headless mode (with Xvfb)
        return co

    def start_browser(self, proxy_url: str = None, user_agent: str = None):
        """Initialize browser session"""
        if self.page:
            return self.page

        # Start virtual display (Linux required)
        self.display = Display(visible=0, size=(1920, 1080))
        self.display.start()

        co = self._get_options(proxy_url, user_agent)
        self.page = ChromiumPage(co)
        return self.page

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Open login page, switch to QR mode, and return Base64 image
        """
        try:
            page = self.start_browser(proxy_url, user_agent)
            
            print(f"[{self.user_id}] 🔍 Opening Creator Center login...")
            page.get("https://creator.xiaohongshu.com/login")
            page.wait.load_start()
            
            # Check if we are already logged in
            if "creator/home" in page.url:
                return {"status": "logged_in", "msg": "Already logged in"}

            # === Switch to QR Code Mode ===
            # Look for the QR code image first
            qr_img = page.ele('.qrcode-img', timeout=2)
            
            if not qr_img:
                print(f"[{self.user_id}] 👀 SMS mode detected, switching to QR...")
                # Try to find the switch button (usually top-right corner)
                # Strategy: Look for div with class containing 'switch' or specific structure
                switch_btn = page.ele('css:div[class*="switch"]', timeout=3)
                
                if not switch_btn:
                    # Fallback: Try finding by SVG or specific position if class is obfuscated
                    # This is a heuristic; might need adjustment if XHS changes UI
                    switch_btn = page.ele('xpath://div[contains(@class, "login-box")]//div[contains(@class, "icon")]')

                if switch_btn:
                    switch_btn.click()
                    time.sleep(1) # Wait for animation
                else:
                    print(f"[{self.user_id}] ⚠️ Warning: Switch button not found")

            # Wait for QR code to render
            print(f"[{self.user_id}] ⏳ Waiting for QR render...")
            qr_box = page.wait.ele('css:div[class*="qrcode"]', timeout=10)
            
            if qr_box:
                # Capture only the QR code area
                base64_str = qr_box.get_screenshot(as_base64=True)
                return {"status": "waiting_scan", "qr_image": base64_str}
            else:
                raise Exception("QR code element not found")

        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR: {str(e)}")
            return {"status": "error", "msg": str(e)}

    def check_login_status(self):
        """
        Check if the current session has successfully logged in
        """
        if not self.page:
            return False
            
        try:
            # Check URL
            if "creator/home" in self.page.url:
                return True
            
            # Check for specific element
            if self.page.ele('text:发布笔记', timeout=1):
                return True
                
            return False
        except:
            return False

    def close(self):
        """Clean up resources"""
        if self.page:
            self.page.quit()
            self.page = None
        if self.display:
            self.display.stop()
            self.display = None

    def execute_publish(self, cookies: str, video_url: str, title: str, desc: str, proxy_url: str = None, user_agent: str = None):
        local_video_path = None
        
        try:
            print(f"[{self.user_id}] 🚀 Starting publish task...")
            
            # 1. Download video
            local_video_path = download_video(video_url)

            # 2. Start browser (if not already started)
            page = self.start_browser(proxy_url, user_agent)
            
            # 3. Inject/Update Cookie
            page.get("https://creator.xiaohongshu.com")
            
            if cookies:
                # If cookies are provided as string, inject them
                # Note: If we just logged in via QR, cookies are already in the browser session
                page.set.cookies(cookies)
                page.refresh()
                time.sleep(3)

            # 4. Check login status
            if "login" in page.url:
                raise Exception("Cookie expired or not logged in")

            print(f"[{self.user_id}] 🔐 Login verified, entering publish page...")
            page.get('https://creator.xiaohongshu.com/publish/publish')
            
            # 5. Upload video
            upload_input = page.ele('tag:input@type=file', timeout=10)
            if not upload_input:
                raise Exception("Upload input not found")
                
            upload_input.input(local_video_path)
            print(f"[{self.user_id}] 📤 Uploading video...")
            
            # Wait for upload completion
            page.wait.ele('text:重新上传', timeout=120)
            print(f"[{self.user_id}] ✅ Upload complete")

            # 6. Fill content
            ele_title = page.ele('@@placeholder=填写标题')
            if ele_title: ele_title.input(title)
            
            ele_desc = page.ele('.ql-editor')
            if ele_desc: ele_desc.input(desc)

            # 7. Click Publish
            btn_publish = page.ele('text:发布', index=1)
            if btn_publish:
                btn_publish.click()
                page.wait(3)
                print(f"[{self.user_id}] 🎉 Publish executed")
            else:
                raise Exception("Publish button not found")
            
            return True, "Publish successful"

        except Exception as e:
            print(f"[{self.user_id}] ❌ Error: {str(e)}")
            if self.page:
                self.page.get_screenshot(path='/tmp', name=f'error_{self.user_id}.png')
            return False, str(e)
            
        finally:
            self.close()
            if local_video_path and os.path.exists(local_video_path):
                os.remove(local_video_path)
