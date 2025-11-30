import os
import time
import shutil
from DrissionPage import ChromiumPage, ChromiumOptions
from pyvirtualdisplay import Display
from .utils import download_video, clean_all_user_data, clean_all_chromium_data

# Constants for QR code icon detection
QR_ICON_MIN_X_POSITION = 300  # Minimum X position for QR icon (right side of login box)
LOGIN_BOX_CORNER_OFFSET = 40  # Offset from corner for coordinate-based clicking

# Stealth JavaScript to bypass browser detection
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
"""

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
        
        # Add isolation parameters to prevent session leakage between users
        co.set_argument('--disable-background-networking')
        co.set_argument('--disable-default-apps')
        co.set_argument('--disable-extensions')
        co.set_argument('--disable-sync')
        co.set_argument('--disable-translate')
        co.set_argument('--no-first-run')
        co.set_argument('--disable-features=TranslateUI')
        
        # Disable all caches
        co.set_argument('--disable-application-cache')
        co.set_argument('--disable-cache')
        co.set_argument('--disk-cache-size=0')
        co.set_argument('--media-cache-size=0')
        
        # Anti-detection: Disable webdriver detection
        co.set_argument('--disable-blink-features=AutomationControlled')
        
        # Set fixed window size
        co.set_argument('--window-size=1920,1080')
        
        # Session crashed bubble
        co.set_argument('--disable-session-crashed-bubble')
        
        return co

    def start_browser(self, proxy_url: str = None, user_agent: str = None, clear_data: bool = True):
        """Initialize browser session"""
        
        # If clear_data is True, we must close the existing browser and clean up first
        if clear_data:
            # Close existing page if it exists
            if self.page:
                print(f"[{self.user_id}] 🔒 Closing existing browser for fresh start...")
                try:
                    self.page.quit()
                except:
                    pass
                self.page = None
            
            # Stop virtual display
            if self.display:
                try:
                    self.display.stop()
                except:
                    pass
                self.display = None
            
            # Clean up user data directory
            if os.path.exists(self.user_data_dir):
                print(f"[{self.user_id}] 🗑️ Cleaning up user data directory: {self.user_data_dir}")
                try:
                    shutil.rmtree(self.user_data_dir)
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Failed to clean user data directory: {e}")
        else:
            # Only try to reuse existing page if clear_data is False
            if self.page:
                try:
                    # Simple liveness check
                    if self.page.url:
                        print(f"[{self.user_id}] ♻️ Reusing existing browser page")
                        return self.page
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Existing browser dead, restarting: {e}")
                    self.page = None
        
        os.makedirs(self.user_data_dir, exist_ok=True) # Ensure directory exists

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
        print(f"[{self.user_id}] 🚀 Starting new browser instance (clear_data={clear_data})...")
        self.page = ChromiumPage(co)
        print(f"[{self.user_id}] ✅ Browser started successfully")
        return self.page

    def _get_cookies_dict(self):
        """Get cookies as a dictionary {name: value}"""
        if not self.page:
            return {}
        try:
            cookies_list = self.page.cookies()
            return {c['name']: c['value'] for c in cookies_list} if cookies_list else {}
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Failed to get cookies: {e}")
            return {}

    def _is_valid_qr_size(self, element, min_size=80):
        """Check if element is large enough (likely a QR code)"""
        try:
            rect = element.rect
            if hasattr(rect, 'size'):
                return rect.size[0] > min_size and rect.size[1] > min_size
            elif hasattr(rect, 'width'):
                return rect.width > min_size and rect.height > min_size
            return False
        except Exception:
            return False

    def _inject_stealth_scripts(self):
        """Inject anti-detection scripts to bypass browser detection"""
        if not self.page:
            return
        try:
            self.page.run_js(STEALTH_JS)
            print(f"[{self.user_id}] 🛡️ Stealth scripts injected")
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Failed to inject stealth scripts: {e}")

    def _wait_for_page_ready(self, timeout=20):
        """Wait for page to be fully rendered (including JavaScript execution)"""
        if not self.page:
            return False
        
        print(f"[{self.user_id}] ⏳ Waiting for page to be ready...")
        ready_indicators = ['短信登录', '扫码登录', '手机号', '登录']
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                for indicator in ready_indicators:
                    if self.page.ele(f'text:{indicator}', timeout=1):
                        print(f"[{self.user_id}] ✅ Page ready, found: {indicator}")
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        
        print(f"[{self.user_id}] ⚠️ Page ready timeout, continuing anyway")
        return False

    def _switch_to_qr_mode(self):
        """Switch from SMS login to QR code login with multiple strategies"""
        if not self.page:
            return False
        
        print(f"[{self.user_id}] 🔍 Looking for QR code switch icon in top-right corner...")
        
        # Strategy 1: JavaScript click on right-side SVG icon
        try:
            result = self.page.run_js('''
                var svgs = document.querySelectorAll('svg');
                for (var i = 0; i < svgs.length; i++) {
                    var rect = svgs[i].getBoundingClientRect();
                    if (rect.x > 300 && rect.width > 10 && rect.width < 50) {
                        svgs[i].click();
                        return 'clicked';
                    }
                }
                return 'not_found';
            ''')
            if result == 'clicked':
                print(f"[{self.user_id}] ✅ Strategy 1 (JS SVG click) succeeded")
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 1 failed: {e}")
        
        # Strategy 2: Find the rightmost SVG and click it
        try:
            svgs = self.page.eles('tag:svg')
            rightmost_svg = None
            max_x = 0
            for svg in svgs:
                try:
                    rect = svg.rect
                    if hasattr(rect, 'x') and rect.x > max_x:
                        max_x = rect.x
                        rightmost_svg = svg
                except Exception:
                    continue
            
            if rightmost_svg and max_x > QR_ICON_MIN_X_POSITION:
                print(f"[{self.user_id}] 🖱️ Strategy 2: clicking rightmost SVG at x={max_x}")
                rightmost_svg.click()
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 2 failed: {e}")
        
        # Strategy 3: Fixed position click based on viewport
        try:
            # Click at fixed position in top-right corner of login box
            result = self.page.run_js('''
                var loginBox = document.querySelector('[class*="login"], [class*="form"], [class*="container"]');
                if (loginBox) {
                    var rect = loginBox.getBoundingClientRect();
                    var clickX = rect.right - 30;
                    var clickY = rect.top + 30;
                    var elem = document.elementFromPoint(clickX, clickY);
                    if (elem) {
                        elem.click();
                        return 'clicked';
                    }
                }
                return 'not_found';
            ''')
            if result == 'clicked':
                print(f"[{self.user_id}] ✅ Strategy 3 (fixed position) succeeded")
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 3 failed: {e}")
        
        # Strategy 4: SVG path pattern matching
        try:
            result = self.page.run_js('''
                var svgs = document.querySelectorAll('svg');
                for (var i = 0; i < svgs.length; i++) {
                    var paths = svgs[i].querySelectorAll('path');
                    if (paths.length > 0) {
                        var d = paths[0].getAttribute('d') || '';
                        // QR code icon usually has specific path patterns
                        if (d.length > 50 && d.length < 500) {
                            var rect = svgs[i].getBoundingClientRect();
                            if (rect.x > 200) {
                                svgs[i].click();
                                return 'clicked';
                            }
                        }
                    }
                }
                return 'not_found';
            ''')
            if result == 'clicked':
                print(f"[{self.user_id}] ✅ Strategy 4 (path pattern) succeeded")
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 4 failed: {e}")
        
        # Strategy 5: XPath search
        try:
            # Try to find "扫码登录" text element
            scan_text = self.page.ele('text:扫码登录', timeout=3)
            if scan_text:
                print(f"[{self.user_id}] 🖱️ Strategy 5: Found '扫码登录' text, clicking...")
                scan_text.click()
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 5 failed: {e}")
        
        # Strategy 6: Find elements with qr-related class names
        try:
            qr_icons = self.page.eles('css:[class*="qr"], css:[class*="scan"], css:[class*="code"]')
            for icon in qr_icons:
                try:
                    print(f"[{self.user_id}] 🖱️ Strategy 6: Found QR-related element, clicking...")
                    icon.click()
                    time.sleep(2)
                    return True
                except Exception:
                    continue
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Strategy 6 failed: {e}")
        
        print(f"[{self.user_id}] ⚠️ Could not switch to QR mode, will try to capture anyway")
        return False

    def _capture_qr_code(self):
        """Capture QR code with multiple strategies"""
        if not self.page:
            return None
        
        print(f"[{self.user_id}] 🔍 Trying to capture QR code...")
        
        # Strategy 1: Canvas element
        try:
            canvases = self.page.eles('tag:canvas')
            for canvas in canvases:
                if self._is_valid_qr_size(canvas):
                    print(f"[{self.user_id}] ✅ Found QR in canvas")
                    return canvas.get_screenshot(as_base64=True)
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Canvas strategy failed: {e}")
        
        # Strategy 2: Base64 image
        try:
            imgs = self.page.eles('tag:img')
            for img in imgs:
                src = img.attr('src') or ''
                if 'data:image' in src and 'base64' in src:
                    if self._is_valid_qr_size(img):
                        print(f"[{self.user_id}] ✅ Found QR in img (base64)")
                        try:
                            base64_str = src.split('base64,')[1]
                            return base64_str
                        except Exception:
                            return img.get_screenshot(as_base64=True)
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Base64 image strategy failed: {e}")
        
        # Strategy 3: Div with qrcode class
        try:
            qr_divs = self.page.eles('css:[class*="qrcode"], css:[class*="qr-"], css:[class*="QRCode"]')
            for div in qr_divs:
                if self._is_valid_qr_size(div):
                    print(f"[{self.user_id}] ✅ Found QR in div")
                    return div.get_screenshot(as_base64=True)
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ QR div strategy failed: {e}")
        
        # Strategy 4: JavaScript to extract canvas data
        try:
            result = self.page.run_js('''
                var canvases = document.querySelectorAll('canvas');
                for (var i = 0; i < canvases.length; i++) {
                    var canvas = canvases[i];
                    if (canvas.width > 80 && canvas.height > 80) {
                        try {
                            return canvas.toDataURL('image/png').split('base64,')[1];
                        } catch (e) {
                            continue;
                        }
                    }
                }
                return null;
            ''')
            if result:
                print(f"[{self.user_id}] ✅ Found QR via JS canvas extraction")
                return result
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ JS canvas extraction failed: {e}")
        
        return None

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Start browser and return QR code image (base64)
        Directly navigates to creator.xiaohongshu.com/login
        """
        try:
            # Clean ALL Chromium data storage locations (global config, cache, temp files)
            clean_all_chromium_data(self.user_id)
            
            # Clean ALL old user data directories to ensure fresh login
            users_base_dir = os.path.dirname(self.user_data_dir)  # data/users/
            clean_all_user_data(users_base_dir, self.user_id)
            
            # Always clear data for a fresh login attempt
            page = self.start_browser(proxy_url, user_agent, clear_data=True)
            
            # Inject stealth scripts to bypass browser detection
            self._inject_stealth_scripts()
            
            # 🔥 Navigate directly to login page, without going through root path first
            print(f"[{self.user_id}] 🌐 Navigating directly to creator.xiaohongshu.com/login...")
            page.get('https://creator.xiaohongshu.com/login', timeout=60)
            
            # Wait for page to load
            print(f"[{self.user_id}] ⏳ Waiting for page to load...")
            page.wait.doc_loaded(timeout=30)
            
            # Inject stealth scripts again after navigation
            self._inject_stealth_scripts()
            
            # Wait for page to be fully ready
            self._wait_for_page_ready(timeout=20)
            
            print(f"[{self.user_id}] 📍 Current URL: {page.url}")
            
            # 🔥 Key step: Click the QR code icon in top-right corner to switch to QR login
            # Default is SMS login mode, need to click the QR code icon in top-right corner
            qr_switch_success = self._switch_to_qr_mode()
            
            if qr_switch_success:
                print(f"[{self.user_id}] ✅ Switched to QR code login mode")
            
            # Wait for QR code to render
            print(f"[{self.user_id}] ⏳ Waiting for QR code to render...")
            time.sleep(3)
            
            # Try to capture QR code using the improved method
            qr_base64 = self._capture_qr_code()
            
            if qr_base64:
                return {"status": "waiting_scan", "qr_image": qr_base64}
            else:
                # Fallback: capture entire page so user can see what happened
                print(f"[{self.user_id}] ⚠️ QR not found, capturing full page...")
                base64_str = page.get_screenshot(as_base64=True)
                return {"status": "waiting_scan", "qr_image": base64_str, "note": "full_page_fallback"}
                
        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR: {e}")
            if self.page:
                try:
                    print(f"[{self.user_id}] 📸 Taking emergency screenshot...")
                    base64_str = self.page.get_screenshot(as_base64=True)
                    return {"status": "waiting_scan", "qr_image": base64_str, "note": "emergency_fallback"}
                except Exception:
                    pass
            return {"status": "error", "msg": str(e)}

    def check_login_status(self):
        """
        Check if the current session has successfully logged in.
        After successful login on main site, navigates to creator platform to verify access.
        """
        if not self.page:
            return False
            
        try:
            # Check cookies for login indicators
            cookies_dict = self._get_cookies_dict()
            
            # Main site login success indicators
            if 'web_session' in cookies_dict or 'a1' in cookies_dict:
                print(f"[{self.user_id}] 🍪 Found login cookies!")
                
                # Navigate to creator platform to verify access
                try:
                    print(f"[{self.user_id}] 🔄 Navigating to creator platform...")
                    self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=15)
                    
                    if "creator" in self.page.url and "login" not in self.page.url:
                        print(f"[{self.user_id}] ✅ Creator platform access confirmed!")
                        return True
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Creator navigation failed: {e}")
                
                # Cookie exists means login is successful
                return True
            
            # Check URL
            if "creator/home" in self.page.url:
                return True
            
            # Check for specific element
            if self.page.ele('text:发布笔记', timeout=1):
                return True
                
            return False
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Check login error: {e}")
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
