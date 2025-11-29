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

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        Start browser and return QR code image (base64)
        Optimized for speed: checks for QR immediately
        """
        try:
            # Always clear data for a fresh login attempt
            page = self.start_browser(proxy_url, user_agent, clear_data=True)
            
            # 1. Quick Check: Are we already on login page with a QR code?
            if "creator.xiaohongshu.com/login" in page.url:
                print(f"[{self.user_id}] ⚡ Already on login page, checking for QR immediately...")
                # Fast check for canvas or img
                if page.ele('tag:canvas', timeout=0.5) or page.ele('.qrcode-img', timeout=0.5):
                    print(f"[{self.user_id}] ✅ QR code already present, skipping navigation/refresh")
                    # Jump straight to detection
                    pass 
                else:
                    # Not found immediately, try reload
                    print(f"[{self.user_id}] 🔄 QR not found, reloading page...")
                    page.run_js('location.reload()')
                    page.wait.load_start()
            else:
                # Full navigation
                print(f"[{self.user_id}] 🌐 Navigating to login page...")
                page.get('https://creator.xiaohongshu.com/login', timeout=30)

            # 2. Check if already logged in
            if "creator/home" in page.url:
                return {"status": "logged_in", "msg": "Already logged in"}

            # 3. Switch to QR Code Mode (if needed)
            # Wait briefly for page to settle
            page.wait.doc_loaded(timeout=5)
            
            # Check if we need to switch (look for SMS input or missing QR)
            qr_present = page.ele('tag:canvas', timeout=1) or page.ele('.qrcode-img', timeout=1)
            
            if not qr_present:
                print(f"[{self.user_id}] 👀 SMS mode detected (QR not found), attempting to switch...")
                
                # Try to find the switch button using multiple strategies
                switched = False
                qr_found = False # Initialize to prevent UnboundLocalError
                
                # Strategy: Smart Switch (Consolidated)
                if not switched:
                    try:
                        print(f"[{self.user_id}] 🖱️ Strategy: Smart Switch (Traversing containers)...")
                        from DrissionPage.common import Actions
                        
                        # Find "SMS Login" text as anchor
                        sms_text = page.ele('text:短信登录', timeout=2)
                        
                        if sms_text:
                            curr = sms_text.parent()
                            # Traverse up to find the best container
                            found_container = False
                            for i in range(5): 
                                if not curr: break
                                try:
                                    rect = curr.rect
                                    if not rect: 
                                        curr = curr.parent()
                                        continue
                                        
                                    w = rect.size[0] if hasattr(rect, 'size') else rect.width
                                    h = rect.size[1] if hasattr(rect, 'size') else rect.height
                                    
                                    # Check if this looks like a login box (at least 300x300)
                                    if w > 300 and h > 300:
                                        print(f"[{self.user_id}] 📦 Found login container: {curr.tag} ({w}x{h})")
                                        found_container = True
                                        
                                        # 1. Try to find an SVG switch button in corners
                                        svgs = curr.eles('tag:svg')
                                        target_btn = None
                                        
                                        for svg in svgs:
                                            try:
                                                # Skip tiny SVGs
                                                s_rect = svg.rect
                                                if not s_rect: continue
                                                
                                                # Relative position
                                                sx = s_rect.location[0] if hasattr(s_rect, 'location') else (s_rect[0] if isinstance(s_rect, tuple) else s_rect.x)
                                                sy = s_rect.location[1] if hasattr(s_rect, 'location') else (s_rect[1] if isinstance(s_rect, tuple) else s_rect.y)
                                                
                                                cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
                                                cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
                                                
                                                rel_x = sx - cx
                                                rel_y = sy - cy
                                                
                                                # Check Top-Left (common for "Back" or "Switch")
                                                if 0 <= rel_x < 80 and 0 <= rel_y < 80:
                                                    print(f"[{self.user_id}] 🎯 Found Top-Left SVG")
                                                    target_btn = svg
                                                    break
                                                
                                                # Check Top-Right (common for "QR/PC Switch")
                                                if (w - 80) < rel_x < w and 0 <= rel_y < 80:
                                                    print(f"[{self.user_id}] 🎯 Found Top-Right SVG")
                                                    target_btn = svg
                                                    break
                                            except:
                                                continue
                                        
                                        # Action: Click Button or Coordinate
                                        if target_btn:
                                            print(f"[{self.user_id}] 🖱️ Clicking found SVG button...")
                                            target_btn.click()
                                        else:
                                            print(f"[{self.user_id}] 🖱️ No SVG found, clicking Top-Right coordinate (Fallback)...")
                                            # Click 25px from top-right
                                            cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
                                            cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
                                            target_x = cx + w - 25
                                            target_y = cy + 25
                                            
                                            ac = Actions(page)
                                            ac.move_to((target_x, target_y)).click()
                                        
                                        # Wait for QR to render (Crucial for avoiding placeholder)
                                        print(f"[{self.user_id}] ⏳ Waiting 2s for QR render...")
                                        time.sleep(2)
                                        
                                        # Check if successful
                                        if page.ele('tag:canvas', timeout=1) or page.ele('tag:img[src*="base64"]', timeout=1):
                                            print(f"[{self.user_id}] ✅ Switch successful!")
                                            qr_found = True
                                            switched = True
                                        
                                        break # Stop traversing once we found and clicked the container
                                        
                                except Exception as e:
                                    print(f"[{self.user_id}] ⚠️ Error checking container: {e}")
                                
                                curr = curr.parent()
                                
                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ Smart Switch strategy failed: {e}")

                if not qr_found:
                     print(f"[{self.user_id}] ⚠️ Switch failed. Dumping page structure...")

                     print(f"[{self.user_id}] ⚠️ Switch failed. Dumping page structure...")
                     try:
                         print(f"[{self.user_id}] Page Title: {page.title}")
                     except: pass

            # 4. QR Detection (Proceed to existing detection logic)
            print(f"[{self.user_id}] 🔍 Starting QR detection loop...")
            
            qr_box = None  # Initialize to prevent UnboundLocalError
            
            def is_valid_qr(ele):
                if not ele: return False
                try:
                    # Check size - QR code should be reasonably large
                    # Relaxed check to > 50px to avoid false negatives
                    rect = ele.rect
                    # Handle different rect attribute access methods
                    if hasattr(rect, 'size'):
                        return rect.size[0] > 50 and rect.size[1] > 50
                    elif hasattr(rect, 'width'):
                        return rect.width > 50 and rect.height > 50
                    else:
                        # Try as dict/tuple
                        return rect[0] > 50 and rect[1] > 50
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error checking element size: {e}")
                    return False

            # Strategy 1: Look for img element with base64 src (Found in analysis)
            print(f"[{self.user_id}] 🔍 Strategy 1: Checking img elements with base64 src...")
            imgs = page.eles('tag:img')
            for img in imgs:
                src = img.attr('src')
                if src and 'data:image' in src and 'base64' in src:
                    # Check size
                    if is_valid_qr(img):
                        print(f"[{self.user_id}] ✅ QR found in img tag (base64)")
                        # Extract base64 directly
                        try:
                            base64_str = src.split('base64,')[1]
                            return {"status": "waiting_scan", "qr_image": base64_str}
                        except IndexError:
                            print(f"[{self.user_id}] ⚠️ Failed to parse base64 src")
            
            if not qr_box:
                # Strategy 2: Look for canvas element
                print(f"[{self.user_id}] 🔍 Strategy 2: Checking canvas elements...")
                canvases = page.eles('tag:canvas')
                for canvas in canvases:
                    if is_valid_qr(canvas):
                        qr_box = canvas
                        print(f"[{self.user_id}] ✅ QR found in canvas")
                        break
            
            if not qr_box:
                # Strategy 3: Look for div containing "qrcode" or "qr" in class name
                print(f"[{self.user_id}] 🔍 Strategy 2: Checking div elements...")
                divs = page.eles('css:div[class*="qrcode"], css:div[class*="qr-"]')
                print(f"[{self.user_id}] 🔍 Found {len(divs)} divs")
                for div in divs:
                    if is_valid_qr(div):
                        qr_box = div
                        print(f"[{self.user_id}] ✅ QR found in div")
                        break
            
            if not qr_box:
                # Strategy 3: Look for img with qr in src or alt
                print(f"[{self.user_id}] 🔍 Strategy 3: Checking img elements...")
                imgs = page.eles('css:img[alt*="qr"], css:img[src*="qrcode"], css:img[alt*="scan"]')
                print(f"[{self.user_id}] 🔍 Found {len(imgs)} imgs")
                for img in imgs:
                    if is_valid_qr(img):
                        qr_box = img
                        print(f"[{self.user_id}] ✅ QR found in img")
                        break
            
            if not qr_box:
                # Strategy 4: By text content - find container with "扫码" nearby
                print(f"[{self.user_id}] 🔍 Strategy 4: Checking text context...")
                qr_text = page.ele('xpath://div[contains(text(), "扫码")]', timeout=2)
                if qr_text:
                    # Try to find canvas or img near this text
                    parent = qr_text.parent()
                    candidates = parent.eles('tag:canvas') + parent.eles('tag:img')
                    print(f"[{self.user_id}] 🔍 Found {len(candidates)} candidates near text")
                    for cand in candidates:
                        if is_valid_qr(cand):
                            qr_box = cand
                            print(f"[{self.user_id}] ✅ QR found near text")
                            break
            
            print(f"[{self.user_id}] 🔍 QR detection finished. Result: {qr_box}")
            
            if qr_box:
                # Capture only the QR code area
                base64_str = qr_box.get_screenshot(as_base64=True)
                return {"status": "waiting_scan", "qr_image": base64_str}
            else:
                print(f"[{self.user_id}] ⚠️ QR element not found, falling back to full screenshot")
                # Fallback: Capture the login box or full page
                # Try to find the login container again to at least crop to that
                login_box = page.ele('css:div[class*="login-box"]', timeout=1)
                if not login_box:
                     # Try finding by text anchor "扫码登录" parent
                     anchor = page.ele('text:扫码登录', timeout=1)
                     if anchor:
                         # Go up 3 levels to find container
                         try:
                            login_box = anchor.parent().parent().parent()
                         except:
                            pass
                
                if login_box:
                    print(f"[{self.user_id}] 📸 Capturing login box as fallback")
                    base64_str = login_box.get_screenshot(as_base64=True)
                else:
                    print(f"[{self.user_id}] 📸 Capturing full page as fallback")
                    base64_str = page.get_screenshot(as_base64=True)
                
                return {"status": "waiting_scan", "qr_image": base64_str}

        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR: {str(e)}")
            
            # Emergency fallback: try to capture whatever is on screen
            try:
                if self.page:
                    print(f"[{self.user_id}] 🚨 Emergency fallback: capturing current page state")
                    base64_str = self.page.get_screenshot(as_base64=True)
                    # Save for debugging
                    with open(f"error_qr_{self.user_id}.png", "wb") as f:
                        import base64
                        f.write(base64.b64decode(base64_str))
                    return {"status": "waiting_scan", "qr_image": base64_str, "note": "emergency_fallback"}
            except Exception as fallback_error:
                print(f"[{self.user_id}] ❌ Emergency fallback also failed: {str(fallback_error)}")
            
            # Original error handling for debugging
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
                print(f"[{self.user_id}] 🍪 Found web_session cookie - Login successful!")
                # Try to navigate to creator platform, but don't fail if navigation times out
                # The cookie existence is the definitive proof of login success
                try:
                    if "creator.xiaohongshu.com" not in self.page.url:
                        print(f"[{self.user_id}] 🔄 Attempting navigation to Creator Platform...")
                        self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=10)
                        if "creator/home" in self.page.url:
                            print(f"[{self.user_id}] ✅ Navigation successful")
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Navigation failed: {e}, but login is valid (cookie exists)")
                
                # Return True regardless of navigation result, cookie is proof of login
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
