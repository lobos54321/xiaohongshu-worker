import os
import time
import shutil
from DrissionPage import ChromiumPage, ChromiumOptions
from pyvirtualdisplay import Display
from .utils import download_video

class BrowserManager:
    """Manage Chromium browser instances for XHS operations"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        # === Enterprise Design: User Data Isolation ===
        # Each user's data is stored in a separate directory
        # In Zeabur, /app/data needs to be a mounted Volume
        # Use relative path to support both Docker (/app/data) and local dev
        self.user_data_dir = os.path.abspath(f"data/users/{user_id}")
        print(f"[{self.user_id}] 📁 Using user_data_dir: {self.user_data_dir}")
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

    def start_browser(self, proxy_url: str = None, user_agent: str = None, clear_data: bool = True):
        """Initialize browser session"""
        # Try to reuse existing page if it's alive
        if self.page:
            try:
                # Simple liveness check
                if self.page.url:
                    print(f"[{self.user_id}] ♻️ Reusing existing browser page")
                    return self.page
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Existing browser dead, restarting: {e}")
                self.page = None

        # Clean up user data directory before starting a new session (only if requested)
        if clear_data and os.path.exists(self.user_data_dir):
            print(f"[{self.user_id}] 🗑️ Cleaning up user data directory: {self.user_data_dir}")
            try:
                shutil.rmtree(self.user_data_dir)
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to clean user data directory: {e}")
        
        os.makedirs(self.user_data_dir, exist_ok=True) # Ensure directory exists

        # Start virtual display (Linux required) - MOVED TO __init__
        # We check if it's running, if not start it (safety check)
        import platform
        if platform.system() == 'Linux' and not self.display:
            try:
                self.display = Display(visible=0, size=(1920, 1080))
                self.display.start()
                print(f"[{self.user_id}] 🖥️ Started virtual display (lazy init)")
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to start virtual display: {e}")

        co = self._get_options(proxy_url, user_agent)
        print(f"[{self.user_id}] 🚀 Starting new browser instance (clear_data={clear_data})...")
        self.page = ChromiumPage(co)
        print(f"[{self.user_id}] ✅ Browser started successfully")
        return self.page

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Start browser and return QR code image (base64)
        Strategy: Main Site Login (www.xiaohongshu.com) -> Login Modal -> QR
        """
        try:
            # Always clear data for a fresh login attempt
            page = self.start_browser(proxy_url, user_agent, clear_data=True)
            
            # 2. Navigate to Main Site (Explore)
            target_url = "https://www.xiaohongshu.com/explore"
            if target_url not in page.url:
                print(f"[{self.user_id}] 🌐 Navigating to Main Site: {target_url}")
                page.get(target_url, timeout=30)
                page.wait.doc_loaded()
                time.sleep(2)
            
            # 3. Check if we need to click "Login"
            # Look for login button
            login_btn = page.ele('text:登录', timeout=2) or page.ele('.login-btn', timeout=2) or page.ele('css:div[class*="login-btn"]', timeout=2)
            
            if login_btn:
                print(f"[{self.user_id}] 🖱️ Found Login button, clicking...")
                login_btn.click()
                time.sleep(1) # Wait for modal
            else:
                print(f"[{self.user_id}] ⚠️ Login button not found (maybe already in modal or logged in?)")

            # 4. Wait for QR Code in Modal
            print(f"[{self.user_id}] 🔍 Waiting for QR code in modal...")
            qr_img = None
            
            # Polling for QR element
            for i in range(10):
                # Main site usually uses img with base64 or canvas
                # Try finding the QR container first
                if page.ele('tag:canvas', timeout=0.5):
                     qr_img = page.ele('tag:canvas').get_screenshot(as_base64=True)
                     print(f"[{self.user_id}] 📸 Captured QR code from canvas")
                     break
                
                # Try img with src containing 'qr' or base64
                imgs = page.eles('tag:img')
                for img in imgs:
                    src = img.attr('src')
                    if src and ('base64' in src or 'qr' in src):
                         # Check size to ensure it's the QR
                         if img.rect.width > 100:
                             qr_img = img.get_screenshot(as_base64=True)
                             print(f"[{self.user_id}] 📸 Captured QR code from img")
                             break
                if qr_img: break
                
                time.sleep(1)
            
            if not qr_img:
                print(f"[{self.user_id}] ⚠️ QR code element not found, capturing full page")
                qr_img = page.get_screenshot(as_base64=True)
                
            return {
                "status": "waiting", 
                "qr_image": qr_img, 
                "msg": "Please scan the QR code"
            }
            
        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR code: {e}")
            return {"status": "error", "msg": str(e)}


    def check_login_status(self):
        """
        Check if the current session has successfully logged in
        """
        if not self.page:
            return False
            
        try:
            # 1. Check URL (Fastest)
            if "creator/home" in self.page.url:
                return True
            
            # 2. Check for specific element (Fast)
            if self.page.ele('text:发布笔记', timeout=1):
                return True

            # 3. Check Cookies (Reliable)
            # If we have 'web_session', we are likely logged in
            cookies = self.page.cookies(as_dict=True)
            if 'web_session' in cookies:
                print(f"[{self.user_id}] 🍪 Found web_session cookie")
                
                # If we are on www.xiaohongshu.com, we need to go to creator platform
                if "creator.xiaohongshu.com" not in self.page.url:
                     print(f"[{self.user_id}] 🔄 Redirecting from Main Site to Creator Platform...")
                     try:
                        self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=15)
                        self.page.wait.doc_loaded()
                        time.sleep(2)
                     except:
                        pass

                # Double check after navigation
                if "creator/home" in self.page.url or self.page.ele('text:发布笔记', timeout=2):
                    return True
                
            return False
        except:
            return False
    
    def get_cookies(self):
        """
        Export cookies after successful login
        Returns list of cookie dicts or None
        """
        if not self.page:
            return None
        try:
            cookies = self.page.cookies()
            return cookies
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Failed to get cookies: {e}")
            return None

    def close(self):
        """Clean up resources"""
        if self.page:
            try:
                self.page.quit()
            except:
                pass
            self.page = None
        if self.display:
            try:
                self.display.stop()
            except:
                pass
            self.display = None

    def cleanup_user_data(self):
        """Delete the user data directory to ensure no cookies/data persist"""
        if os.path.exists(self.user_data_dir):
            print(f"[{self.user_id}] 🗑️ Final cleanup of user data directory: {self.user_data_dir}")
            try:
                shutil.rmtree(self.user_data_dir)
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to clean user data directory: {e}")

    def publish_content(self, cookies: str, publish_type: str, files: list, title: str, desc: str, proxy_url: str = None, user_agent: str = None):
        """
        Publish content (Video or Image) to Xiaohongshu
        publish_type: 'video' or 'image'
        files: list of local file paths
        """
        try:
            print(f"[{self.user_id}] 🚀 Starting publish task ({publish_type}) - v2 (Session Persistence Enabled)...")
            
            # 1. Start browser (reuse session data if available)
            page = self.start_browser(proxy_url, user_agent, clear_data=False)
            
            # 2. Inject/Update Cookie
            page.get("https://creator.xiaohongshu.com")
            
            if cookies:
                try:
                    # Parse cookies if string
                    if isinstance(cookies, str):
                        import json
                        cookies_obj = json.loads(cookies)
                    else:
                        cookies_obj = cookies
                    
                    print(f"[{self.user_id}] 🍪 Injecting {len(cookies_obj)} cookies...")
                    page.set.cookies(cookies_obj)
                    time.sleep(1)
                    page.refresh()
                    time.sleep(3)
                    
                    # Force navigation to home to ensure we are logged in
                    if "creator/home" not in page.url:
                        print(f"[{self.user_id}] 🔄 Navigating to Creator Home...")
                        page.get("https://creator.xiaohongshu.com/creator/home")
                        page.wait.load_start()
                        
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error setting cookies: {e}")

            # 3. Check login status
            if "login" in page.url:
                print(f"[{self.user_id}] ❌ Login check failed. URL: {page.url}")
                raise Exception("Cookie expired or not logged in")

            print(f"[{self.user_id}] 🔐 Login verified, entering publish page...")
            page.get('https://creator.xiaohongshu.com/publish/publish')
            
            # 4. Handle Tab Switching (Video vs Image)
            # Default is usually Video. If Image, need to switch tab.
            # Tab selectors: .tab-item
            if publish_type == 'image':
                print(f"[{self.user_id}] 🖼️ Switching to Image/Text tab...")
                try:
                    # Try to find the tab by text "图文"
                    image_tab = page.ele('text:图文', timeout=5)
                    if image_tab:
                        image_tab.click()
                        time.sleep(1)
                    else:
                        print(f"[{self.user_id}] ⚠️ Could not find Image tab by text, trying index...")
                        # Fallback: usually the second tab
                        tabs = page.eles('.tab-item')
                        if len(tabs) >= 2:
                            tabs[1].click()
                            time.sleep(1)
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error switching tab: {e}")

            # 5. Upload Files
            upload_input = page.ele('tag:input@type=file', timeout=10)
            if not upload_input:
                raise Exception("Upload input not found")
                
            print(f"[{self.user_id}] 📤 Uploading {len(files)} files...")
            # DrissionPage supports uploading multiple files by passing a list
            upload_input.input(files)
            
            # Wait for upload completion
            # For images, it might be faster. For video, wait for "Re-upload" text.
            if publish_type == 'video':
                page.wait.ele('text:重新上传', timeout=120)
            else:
                # For images, wait a bit for previews to appear
                time.sleep(5)
                
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
                debug_dir = os.getcwd()
                err_path = os.path.join(debug_dir, f'error_publish_{self.user_id}.png')
                print(f"[{self.user_id}] 📸 Saving publish error screenshot to {err_path}")
                self.page.get_screenshot(path=err_path)
            return False, str(e)
            
        finally:
            self.close()
            # Cleanup temp files
            for f in files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass
