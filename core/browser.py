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
                
                # Strategy 4: Geometric Search relative to "短信登录" text
                if not switched:
                    try:
                        print(f"[{self.user_id}] 🔍 Strategy 4: Geometric search via '短信登录' text...")
                        # Find the "SMS Login" text
                        sms_text = page.ele('text:短信登录', timeout=1)
                        if sms_text:
                            # Go up to find the container (white box)
                            # Usually it's a few levels up. We look for a div with reasonable size.
                            container = sms_text.parent()
                            for _ in range(5):
                                if not container: break
                                rect = container.rect
                                w = rect.size[0] if hasattr(rect, 'size') else rect.width
                                h = rect.size[1] if hasattr(rect, 'size') else rect.height
                                # Login box is usually around 300-500px wide
                                if 200 < w < 600 and 200 < h < 600:
                                    break
                                container = container.parent()
                            
                            if container:
                                print(f"[{self.user_id}] 📦 Found container via text: {container}")
                                # Find all SVGs in this container
                                svgs = container.eles('tag:svg')
                                for svg in svgs:
                                    # Check if SVG is in top-right corner
                                    # We need relative position. 
                                    s_rect = svg.rect
                                    c_rect = container.rect
                                    
                                    sx = s_rect.location[0] if hasattr(s_rect, 'location') else (s_rect[0] if isinstance(s_rect, tuple) else s_rect.x)
                                    sy = s_rect.location[1] if hasattr(s_rect, 'location') else (s_rect[1] if isinstance(s_rect, tuple) else s_rect.y)
                                    
                                    cx = c_rect.location[0] if hasattr(c_rect, 'location') else (c_rect[0] if isinstance(c_rect, tuple) else c_rect.x)
                                    cy = c_rect.location[1] if hasattr(c_rect, 'location') else (c_rect[1] if isinstance(c_rect, tuple) else c_rect.y)
                                    
                                    rel_x = sx - cx
                                    rel_y = sy - cy
                                    
                                    # Container width
                                    cw = c_rect.size[0] if hasattr(c_rect, 'size') else c_rect.width
                                    
                                    # If in top-right 60x60 area (x > width - 60, y < 60)
                                    if (cw - 60) < rel_x < cw and 0 <= rel_y < 60:
                                        print(f"[{self.user_id}] 🎯 Found top-right corner SVG at ({rel_x}, {rel_y}), clicking...")
                                        svg.click()
                                        switched = True
                                        break
                                        
                            # Strategy 5: JS Click Top-Right Corner (Fallback)
                            if not qr_found:
                                print(f"[{self.user_id}] 🖱️ Strategy 5: JS Click Top-Right of Login Box...")
                                js_code = """
                                    var box = arguments[0];
                                    var rect = box.getBoundingClientRect();
                                    // Click 20px from top-right
                                    var x = rect.right - 20;
                                    var y = rect.top + 20;
                                    var el = document.elementFromPoint(x, y);
                                    if (el) el.click();
                                    return [x, y];
                                """
                                page.run_js(js_code, container)
                                if page.wait.ele('tag:canvas', timeout=2) or page.wait.ele('tag:img[src*="base64"]', timeout=2):
                                    print(f"[{self.user_id}] ✅ Switch successful (Strategy 5)")
                                    qr_found = True

                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ Geometric/JS strategy failed: {e}")
                
                # Strategy 6: Real Mouse Event Simulation
                if not qr_found:
                    try:
                        print(f"[{self.user_id}] 🖱️ Strategy 6: Simulating Real Mouse Events (JS)...")
                        # Find login container again if needed
                        sms_text = page.ele('text:短信登录', timeout=1)
                        if sms_text:
                            container = sms_text.parent()
                            for _ in range(5):
                                if not container: break
                                try:
                                    rect = container.rect
                                    # Check if rect is valid
                                    if not rect: continue
                                    w = rect.size[0] if hasattr(rect, 'size') else rect.width
                                    h = rect.size[1] if hasattr(rect, 'size') else rect.height
                                    if 200 < w < 600 and 200 < h < 600:
                                        break
                                except:
                                    pass
                                container = container.parent()
                            
                            if container:
                                rect = container.rect
                                cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
                                cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
                                cw = rect.size[0] if hasattr(rect, 'size') else rect.width
                                
                                target_x = cx + cw - 20
                                target_y = cy + 20
                                
                                js_mouse_event = f"""
                                    var el = document.elementFromPoint({target_x}, {target_y});
                                    if (el) {{
                                        ['mouseenter', 'mouseover', 'mousemove', 'mousedown', 'mouseup', 'click'].forEach(function(eventType) {{
                                            var event = new MouseEvent(eventType, {{
                                                bubbles: true,
                                                cancelable: true,
                                                view: window,
                                                clientX: {target_x},
                                                clientY: {target_y}
                                            }});
                                            el.dispatchEvent(event);
                                        }});
                                        return true;
                                    }}
                                    return false;
                                """
                                page.run_js(js_mouse_event)
                                if page.wait.ele('tag:canvas', timeout=2) or page.wait.ele('tag:img[src*="base64"]', timeout=2):
                                    print(f"[{self.user_id}] ✅ Switch successful (Strategy 6)")
                                    qr_found = True
                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ Real Mouse Event strategy failed: {e}")

                # Strategy 7: DrissionPage Actions API
                if not qr_found:
                    try:
                        print(f"[{self.user_id}] 🖱️ Strategy 7: DrissionPage Actions API...")
                        from DrissionPage.common import Actions
                        
                        # Find login box with robust traversal
                        sms_text = page.ele('text:短信登录', timeout=1)
                        container = None
                        if sms_text:
                            curr = sms_text.parent()
                            for _ in range(10): # Traverse up to 10 levels
                                if not curr: break
                                try:
                                    rect = curr.rect
                                    if rect and rect.size[0] > 200 and rect.size[1] > 200:
                                        container = curr
                                        print(f"[{self.user_id}] 📦 Found valid container: {curr.tag} ({rect.size})")
                                        break
                                except:
                                    pass
                                curr = curr.parent()
                                
                        if container:
                            rect = container.rect
                            cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
                            cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
                            cw = rect.size[0] if hasattr(rect, 'size') else rect.width
                            
                            # Target: Top-Right corner
                            target_x = cx + cw - 25
                            target_y = cy + 25
                            
                            ac = Actions(page)
                            ac.move_to((target_x, target_y)).click()
                            if page.wait.ele('tag:canvas', timeout=2) or page.wait.ele('tag:img[src*="base64"]', timeout=2):
                                print(f"[{self.user_id}] ✅ Switch successful (Strategy 7)")
                                qr_found = True
                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ Actions API strategy failed: {e}")

                # Strategy 8: Brute Force Icon Click (New)
                if not qr_found:
                    try:
                        print(f"[{self.user_id}] 🖱️ Strategy 8: Brute Force Icon Click...")
                        # Use the container found in Strategy 7 or find it again
                        if not container:
                             sms_text = page.ele('text:短信登录', timeout=1)
                             if sms_text:
                                curr = sms_text.parent()
                                for _ in range(10):
                                    if not curr: break
                                    try:
                                        rect = curr.rect
                                        if rect and rect.size[0] > 200 and rect.size[1] > 200:
                                            container = curr
                                            break
                                    except:
                                        pass
                                    curr = curr.parent()
                        
                        if container:
                            # Find all potential switch buttons (svg, img, div with icon class)
                            candidates = container.eles('tag:svg') + container.eles('tag:img')
                            print(f"[{self.user_id}] 🔍 Found {len(candidates)} candidates for brute force click")
                            
                            for i, cand in enumerate(candidates):
                                try:
                                    # Skip if too large (likely not an icon)
                                    if cand.rect.size[0] > 100 or cand.rect.size[1] > 100:
                                        continue
                                        
                                    print(f"[{self.user_id}] 🖱️ Clicking candidate {i+1}...")
                                    cand.click(by_js=True) # Try JS click first
                                    time.sleep(0.5)
                                    
                                    if page.wait.ele('tag:canvas', timeout=1) or page.wait.ele('tag:img[src*="base64"]', timeout=1):
                                        print(f"[{self.user_id}] ✅ Switch successful (Strategy 8 - Candidate {i+1})")
                                        qr_found = True
                                        break
                                        
                                    # Try regular click if JS failed to trigger
                                    cand.click()
                                    time.sleep(0.5)
                                    if page.wait.ele('tag:canvas', timeout=1) or page.wait.ele('tag:img[src*="base64"]', timeout=1):
                                        print(f"[{self.user_id}] ✅ Switch successful (Strategy 8 - Candidate {i+1})")
                                        qr_found = True
                                        break
                                except Exception as e:
                                    print(f"[{self.user_id}] ⚠️ Error clicking candidate {i}: {e}")
                    except Exception as e:
                         print(f"[{self.user_id}] ⚠️ Brute Force strategy failed: {e}")

                if not qr_found:
                     print(f"[{self.user_id}] ⚠️ All switch strategies failed or QR did not appear")
                     # Dump container HTML for debugging
                     if container:
                         print(f"[{self.user_id}] 🐛 Container HTML Dump: {container.html[:500]}...")

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
