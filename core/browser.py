import os
import time
import shutil
import platform
from DrissionPage import ChromiumPage, ChromiumOptions

# Try to import pyvirtualdisplay for headless environments (Linux/Zeabur)
try:
    from pyvirtualdisplay import Display
    HAS_DISPLAY = True
except ImportError:
    HAS_DISPLAY = False

from .utils import download_video

class BrowserManager:
    """Manage Chromium browser instances for XHS operations"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.page = None
        self.display = None
        
        # Start virtual display if on Linux and available
        # This is crucial for Zeabur deployment to mimic a real screen
        if HAS_DISPLAY and platform.system() == 'Linux':
            try:
                print(f"[{self.user_id}] 🖥️ Starting virtual display...")
                self.display = Display(visible=0, size=(1920, 1080))
                self.display.start()
                print(f"[{self.user_id}] 🖥️ Virtual display started.")
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to start virtual display: {e}")

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

    def start_browser(self, proxy_url: str = None, user_agent: str = None):
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

        # Clean up user data directory before starting a new session (only if cold start)
        # This ensures a fresh state for each login attempt or session
        if os.path.exists(self.user_data_dir):
            print(f"[{self.user_id}] 🗑️ Cleaning up user data directory: {self.user_data_dir}")
            try:
                shutil.rmtree(self.user_data_dir)
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to clean user data directory: {e}")
        os.makedirs(self.user_data_dir, exist_ok=True) # Recreate the directory

        # Start virtual display (Linux required)
        import platform
        if platform.system() == 'Linux':
            try:
                if self.display:
                    self.display.stop()
            except:
                pass
            self.display = Display(visible=0, size=(1920, 1080))
            self.display.start()
            print(f"[{self.user_id}] 🖥️ Started virtual display")

        co = self._get_options(proxy_url, user_agent)
        print(f"[{self.user_id}] 🚀 Starting new browser instance...")
        self.page = ChromiumPage(co)
        print(f"[{self.user_id}] ✅ Browser started successfully")
        return self.page

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Open login page, switch to QR mode, and return Base64 image
        """
    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Start browser and return QR code image (base64)
        Optimized for speed: checks for QR immediately
        """
        try:
            start_time = time.time()
            page = self.start_browser(proxy_url, user_agent)
            print(f"[{self.user_id}] ⏱️ Browser start/reuse took {time.time() - start_time:.2f}s")
            
            # 1. Quick Check: Are we already on login page with a QR code?
            if "creator.xiaohongshu.com/login" in page.url:
                print(f"[{self.user_id}] ⚡ Already on login page, checking for QR immediately...")
                # Fast check for canvas or img
                if page.ele('tag:canvas', timeout=0.5) or page.ele('.qrcode-img', timeout=0.5):
                    print(f"[{self.user_id}] ✅ QR code already present, skipping navigation/refresh")

            print(f"[{self.user_id}] 🚀 Starting Main Site Login Flow...")
            
            # Helper function for QR validation
            def is_valid_qr(ele):
                if not ele: return False
                try:
                    rect = ele.rect
                    if hasattr(rect, 'size'):
                        return rect.size[0] > 50 and rect.size[1] > 50
                    elif hasattr(rect, 'width'):
                        return rect.width > 50 and rect.height > 50
                    else:
                        return rect[0] > 50 and rect[1] > 50
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error checking element size: {e}")
                    return False
            
            # 1. Navigate to Main Site (More stable UI)
            target_url = "https://www.xiaohongshu.com/explore"
            if target_url not in page.url:
                print(f"[{self.user_id}] 🌐 Navigating to {target_url}...")
                page.get(target_url)
                page.wait.doc_loaded()
            
            # Check if already logged in (web_session cookie)
            # Safe way to get cookies as dict
            cookies_list = page.cookies()
            cookies = {c['name']: c['value'] for c in cookies_list}
            
            if 'web_session' in cookies:
                print(f"[{self.user_id}] 🍪 Found web_session cookie on Main Site, already logged in!")
                return {"status": "logged_in", "msg": "Already logged in on Main Site"}
            
            # 2. Click Login Button
            # 2. Click Login Button
            # Try multiple selectors for the login button on main site
            print(f"[{self.user_id}] 🖱️ Looking for Login button...")
            login_btn = page.ele('text:登录', timeout=3) or \
                        page.ele('.login-btn', timeout=1) or \
                        page.ele('css:div[class*="login"]', timeout=1)
            
            debug_dir = os.getcwd()
            
            if login_btn:
                print(f"[{self.user_id}] 🖱️ Clicking Login button: {login_btn.tag} {login_btn.text}")
                login_btn.click()
                time.sleep(2) # Wait longer for modal
            else:
                print(f"[{self.user_id}] ⚠️ Login button not found. Dumping page text...")
                try:
                    print(f"[{self.user_id}] Page Title: {page.title}")
                    # print(f"[{self.user_id}] Page Text: {page.text[:200]}...") 
                except: pass
            
            # Debug: Save screenshot to see if modal opened
            shot_path = os.path.join(debug_dir, f'debug_after_click_{self.user_id}.png')
            print(f"[{self.user_id}] 📸 Saving debug screenshot to {shot_path}")
            page.get_screenshot(path=shot_path)

            # 3. Detect QR Code (Prioritize Canvas)
            print(f"[{self.user_id}] 🔍 Looking for QR code in modal...")
            qr_box = None
            
            # Wait for QR container to appear
            for i in range(10): # Poll for 5 seconds
                # Check for Canvas (Dynamic QR)
                canvas = page.ele('tag:canvas', timeout=0.5)
                if is_valid_qr(canvas):
                    qr_box = canvas
                    print(f"[{self.user_id}] ✅ QR found in canvas")
                    break
                
                # Check for Img (Static QR - Main site might use img)
                img = page.ele('css:img[src*="qr"]', timeout=0.1)
                if is_valid_qr(img):
                    qr_box = img
                    print(f"[{self.user_id}] ✅ QR found in img")
                    break
                
                # Fallback: Check for switch button (if QR not shown by default)
                if not qr_box:
                    switch_btn = page.ele('.login-switch', timeout=0.1) or page.ele('.auth-page-qrcode-switch', timeout=0.1)
                    if switch_btn:
                        print(f"[{self.user_id}] 🖱️ Found switch button, clicking...")
                        switch_btn.click()
                        time.sleep(1)
                    
                time.sleep(0.5)
            
            if qr_box:
                base64_str = qr_box.get_screenshot(as_base64=True)
                return {"status": "waiting_scan", "qr_image": base64_str}
            else:
                print(f"[{self.user_id}] ❌ QR code not found in modal.")
                if self.page:
                    # Capture screenshot for debugging
                    base64_str = self.page.get_screenshot(as_base64=True)
                    # Save to disk for agent to view
                    err_path = os.path.join(debug_dir, f'debug_error_{self.user_id}.png')
                    print(f"[{self.user_id}] 📸 Saving error screenshot to {err_path}")
                    self.page.get_screenshot(path=err_path)
                    return {"status": "error", "msg": "QR code not found", "debug_image": base64_str}
                return {"status": "error", "msg": "QR code not found"}

        except Exception as e:
            print(f"[{self.user_id}] ❌ Error in Main Site Login: {str(e)}")
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
            # Safe way to get cookies as dict
            cookies_list = self.page.cookies()
            cookies = {c['name']: c['value'] for c in cookies_list}
            
            if 'web_session' in cookies:
                print(f"[{self.user_id}] 🍪 Found web_session cookie, forcing navigation to home...")
                try:
                    self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=10)
                    # Double check after navigation
                    if "creator/home" in self.page.url:
                        return True
                except:
                    pass
                
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
            print(f"[{self.user_id}] 🚀 Starting publish task ({publish_type})...")
            
            # 1. Start browser (if not already started)
            page = self.start_browser(proxy_url, user_agent)
            
            # 2. Inject/Update Cookie
            page.get("https://creator.xiaohongshu.com")
            
            if cookies:
                page.set.cookies(cookies)
                page.refresh()
                time.sleep(3)

            # 3. Check login status
            if "login" in page.url:
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
                self.page.get_screenshot(path='/tmp', name=f'error_{self.user_id}.png')
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
