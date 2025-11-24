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
            try:
                page.get("https://creator.xiaohongshu.com/login", timeout=15)
                page.wait.load_start()
            except Exception as load_err:
                print(f"[{self.user_id}] ⚠️  Page load timeout/error: {str(load_err)}")
                # Continue anyway - page might be partially loaded
                time.sleep(3)
            
            # Check if we are already logged in
            if "creator/home" in page.url:
                return {"status": "logged_in", "msg": "Already logged in"}

            # === Switch to QR Code Mode ===
            # Look for the QR code image first
            qr_img = page.ele('.qrcode-img', timeout=2)
            
            if not qr_img:
                print(f"[{self.user_id}] 👀 SMS mode detected, switching to QR...")
                
                # Aggressive strategy: Try multiple approaches to click the switch button
                switched = False
                
                # Approach 1: Use JavaScript to find and click ALL small SVG/IMG elements
                try:
                    js_click_script = """
                    (async function() {
                        const allIcons = [...document.querySelectorAll('svg'), ...document.querySelectorAll('img')];
                        let clickedCount = 0;
                        
                        for (let icon of allIcons) {
                            const rect = icon.getBoundingClientRect();
                            // Look for small icons (10-80px) - click ALL of them
                            if (rect.width > 10 && rect.width < 80 && rect.height > 10 && rect.height < 80) {
                                try {
                                    icon.click();
                                    clickedCount++;
                                    console.log('Clicked icon:', rect.width, 'x', rect.height);
                                    // Small delay between clicks
                                    await new Promise(r => setTimeout(r, 200));
                                } catch(e) {
                                    console.log('Failed to click:', e);
                                }
                            }
                        }
                        return clickedCount;
                    })();
                    """
                    result = page.run_js(js_click_script)
                    print(f"[{self.user_id}] 🎯 Clicked {result} icons with JavaScript")
                    time.sleep(3)
                    
                    # Check if switched
                    if "扫码登录" in page.html or "扫码" in page.html:
                        switched = True
                        print(f"[{self.user_id}] ✅ Successfully switched using JavaScript")
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ JavaScript approach failed: {e}")
                
                # Approach 2: DrissionPage element-based approach (if JS failed)
                if not switched:
                    try:
                        login_area = page.ele('css:div[class*="login"]', timeout=2)
                        if login_area:
                            icons = login_area.eles('tag:svg') + login_area.eles('tag:img')
                            print(f"[{self.user_id}] 🔍 Found {len(icons)} icons in login area")
                            for icon in icons:
                                try:
                                    # Get bounding box - use size property instead of rect
                                    rect = icon.rect
                                    # rect has properties: width, height, x, y - but access them as tuple indices
                                    w = rect.size[0] if hasattr(rect, 'size') else rect.width
                                    h = rect.size[1] if hasattr(rect, 'size') else rect.height
                                    
                                    if 10 < w < 80 and 10 < h < 80:
                                        print(f"[{self.user_id}] 🖱️ Clicking icon: {w}x{h}")
                                        page.run_js("arguments[0].click()", icon)
                                        time.sleep(2)
                                        if "扫码登录" in page.html or "扫码" in page.html:
                                            switched = True
                                            print(f"[{self.user_id}] ✅ Successfully switched")
                                            break
                                except Exception as e:
                                    print(f"[{self.user_id}] ⚠️ Failed to check/click icon: {e}")
                                    continue
                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ DrissionPage approach failed: {e}")
                
                
                # Log final status
                if not switched:
                    print(f"[{self.user_id}] ⚠️ Could not switch to QR mode - will try to capture anyway")
                else:
                    print(f"[{self.user_id}] ✅ Switch to QR mode completed")

            # Re-check for QR code after potential switch
            # Try multiple strategies for finding the QR code
            qr_box = None
            print(f"[{self.user_id}] 🔍 Starting QR detection loop...")
            
            def is_valid_qr(ele):
                if not ele: return False
                try:
                    # Check size - QR code should be reasonably large (e.g. > 100px)
                    rect = ele.rect
                    # Handle different rect attribute access methods
                    if hasattr(rect, 'size'):
                        return rect.size[0] > 100 and rect.size[1] > 100
                    elif hasattr(rect, 'width'):
                        return rect.width > 100 and rect.height > 100
                    else:
                        # Try as dict/tuple
                        return rect[0] > 100 and rect[1] > 100
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error checking element size: {e}")
                    return False

            # Strategy 1: Look for canvas element (most common for QR codes)
            print(f"[{self.user_id}] 🔍 Strategy 1: Checking canvas elements...")
            canvases = page.eles('tag:canvas')
            print(f"[{self.user_id}] 🔍 Found {len(canvases)} canvases")
            for canvas in canvases:
                if is_valid_qr(canvas):
                    qr_box = canvas
                    print(f"[{self.user_id}] ✅ QR found in canvas")
                    break
            
            if not qr_box:
                # Strategy 2: Look for div containing "qrcode" or "qr" in class name
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
            # Check URL
            if "creator/home" in self.page.url:
                return True
            
            # Check for specific element
            if self.page.ele('text:发布笔记', timeout=1):
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
