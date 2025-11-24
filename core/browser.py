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
        # Use relative path to support both Docker (/app/data) and local dev
        self.user_data_dir = os.path.abspath(f"data/users/{user_id}")
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.page = None
        self.display = None

    def _get_options(self, proxy_url: str = None, user_agent: str = None):
        co = ChromiumOptions()
        
        # Auto-detect OS and set browser path
        import platform
        if platform.system() == 'Linux':
            co.set_browser_path('/usr/bin/chromium')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.headless(True) # Must enable headless mode (with Xvfb on Linux)
        else:
            # On Mac/Windows, DrissionPage usually finds Chrome automatically. 
            # Use native headless to avoid Xvfb dependency
            co.set_argument('--headless=new')
            
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
        return co

    def start_browser(self, proxy_url: str = None, user_agent: str = None):
        """Initialize browser session"""
        if self.page:
            return self.page

        # Start virtual display (Linux required)
        import platform
        if platform.system() == 'Linux':
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
                # Strategy: Look for the login box container first
                login_box = page.ele('.css-1age63q', timeout=2)
                switch_btn = None
                
                if login_box:
                    # Look for the corner image inside the login box
                    switch_btn = login_box.ele('tag:img', timeout=1)
                
                if not switch_btn:
                    # Fallback: Try the obfuscated class directly
                    switch_btn = page.ele('.css-wemwzq', timeout=1)

                if not switch_btn:
                    # Fallback: Old selector
                    switch_btn = page.ele('css:div[class*="switch"]', timeout=1)

                if switch_btn:
                    print(f"[{self.user_id}] 🖱️ Clicking switch button: {switch_btn}")
                    # Try JS click for better reliability
                    page.run_js("arguments[0].click()", switch_btn)
                    
                    # Wait for page transition
                    print(f"[{self.user_id}] ⏱️ Waiting for page transition...")
                    time.sleep(5) # Wait longer for animation and render
                    
                    # Verify the switch by checking for text change
                    page_text = page.html
                    if "扫码登录" in page_text or "QR" in page_text.upper():
                        print(f"[{self.user_id}] ✅ Successfully switched to QR mode")
                    elif "短信登录" in page_text:
                        print(f"[{self.user_id}] ⚠️ Warning: Still in SMS mode after click, trying to refresh")
                        page.refresh()
                        time.sleep(3)
                    else:
                        print(f"[{self.user_id}] ⚠️ Warning: Cannot determine login mode")
                else:
                    print(f"[{self.user_id}] ⚠️ Warning: Switch button not found")

            # Re-check for QR code after potential switch
            # Try multiple strategies for finding the QR code
            qr_box = None
            
            # Strategy 1: Look for canvas element (most common for QR codes)
            qr_box = page.ele('tag:canvas', timeout=3)
            
            if not qr_box:
                # Strategy 2: Look for div containing "qrcode" or "qr" in class name
                qr_box = page.ele('css:div[class*="qrcode"], css:div[class*="qr-"]', timeout=2)
            
            if not qr_box:
                # Strategy 3: Look for img with qr in src or alt
                qr_box = page.ele('css:img[alt*="qr"], css:img[src*="qrcode"], css:img[alt*="scan"]', timeout=2)
            
            if not qr_box:
                # Strategy 4: By text content - find container with "扫码" nearby
                qr_text = page.ele('xpath://div[contains(text(), "扫码")]', timeout=2)
                if qr_text:
                    # Try to find canvas or img near this text
                    parent = qr_text.parent()
                    qr_box = parent.ele('tag:canvas', timeout=1) or parent.ele('tag:img', timeout=1)
            
            print(f"[{self.user_id}] 🔍 QR element found: {qr_box}")
            
            if qr_box:
                # Capture only the QR code area
                base64_str = qr_box.get_screenshot(as_base64=True)
                return {"status": "waiting_scan", "qr_image": base64_str}
            else:
                raise Exception("QR code element not found")

        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR: {str(e)}")
            try:
                if page:
                    page.get_screenshot(path='.', name='error_qr.png')
                    with open('error_qr.html', 'w', encoding='utf-8') as f:
                        f.write(page.html)
            except:
                pass
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
