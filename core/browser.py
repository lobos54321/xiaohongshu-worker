import os
import time
import shutil
from DrissionPage import ChromiumPage, ChromiumOptions
from pyvirtualdisplay import Display
from .utils import download_video, clean_all_user_data, clean_all_chromium_data

class BrowserManager:
    """Manage Chromium browser instances for XHS operations"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.user_data_dir = os.path.abspath(f"data/users/{user_id}")
        print(f"[{self.user_id}] 📁 Using user_data_dir: {self.user_data_dir}")
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.page = None
        self.display = None

    def _get_options(self, proxy_url: str = None, user_agent: str = None):
        co = ChromiumOptions()
        
        import platform
        if platform.system() == 'Linux':
            co.set_browser_path('/usr/bin/chromium')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.headless(True)
        else:
            co.set_argument('--headless=new')
            
        if proxy_url:
            co.set_proxy(proxy_url)
            
        if user_agent:
            co.set_user_agent(user_agent)
        else:
            co.set_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        co.set_user_data_path(self.user_data_dir)
        co.auto_port()
        
        co.set_argument('--disable-background-networking')
        co.set_argument('--disable-default-apps')
        co.set_argument('--disable-extensions')
        co.set_argument('--disable-sync')
        co.set_argument('--disable-translate')
        co.set_argument('--no-first-run')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--window-size=1920,1080')
        
        return co

    def start_browser(self, proxy_url: str = None, user_agent: str = None, clear_data: bool = True):
        """Initialize browser session"""
        
        if clear_data:
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
            
            if os.path.exists(self.user_data_dir):
                try:
                    shutil.rmtree(self.user_data_dir)
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Failed to clean user data directory: {e}")
        else:
            if self.page:
                try:
                    if self.page.url:
                        return self.page
                except:
                    self.page = None
        
        os.makedirs(self.user_data_dir, exist_ok=True)

        import platform
        if platform.system() == 'Linux':
            display_env = os.environ.get('DISPLAY')
            if not display_env:
                try:
                    if self.display:
                        self.display.stop()
                except:
                    pass
                self.display = Display(visible=0, size=(1920, 1080))
                self.display.start()
                print(f"[{self.user_id}] 🖥️ Started virtual display")
            else:
                print(f"[{self.user_id}] 🖥️ Using existing DISPLAY: {display_env}")

        co = self._get_options(proxy_url, user_agent)
        print(f"[{self.user_id}] 🚀 Starting new browser instance...")
        self.page = ChromiumPage(co)
        
        self._inject_stealth_scripts()
        
        print(f"[{self.user_id}] ✅ Browser started successfully")
        return self.page

    def _inject_stealth_scripts(self):
        """注入反检测脚本"""
        if not self.page:
            return
        
        try:
            self.page.run_js("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = {runtime: {}};
            """)
            print(f"[{self.user_id}] 🛡️ Stealth scripts injected")
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Failed to inject stealth scripts: {e}")

    def _get_cookies_dict(self):
        if not self.page:
            return {}
        try:
            cookies_list = self.page.cookies()
            return {c['name']: c['value'] for c in cookies_list} if cookies_list else {}
        except:
            return {}

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        获取登录二维码
        
        核心策略变更：
        1. 先尝试访问页面
        2. 使用JavaScript强制切换到扫码模式
        3. 等待并捕获QR码
        """
        try:
            clean_all_chromium_data(self.user_id)
            users_base_dir = os.path.dirname(self.user_data_dir)
            clean_all_user_data(users_base_dir, self.user_id)
            
            page = self.start_browser(proxy_url, user_agent, clear_data=True)
            
            # 导航到登录页
            print(f"[{self.user_id}] 🌐 Navigating to login page...")
            page.get('https://creator.xiaohongshu.com/login', timeout=60)
            
            print(f"[{self.user_id}] ⏳ Waiting for page to load...")
            page.wait.doc_loaded(timeout=30)
            time.sleep(3)
            
            self._inject_stealth_scripts()
            
            print(f"[{self.user_id}] 📍 Current URL: {page.url}")
            
            # ========== 关键步骤：强制切换到扫码模式 ==========
            print(f"[{self.user_id}] 🔄 Attempting to switch to QR mode...")
            
            # 策略：遍历所有可能的点击目标
            switch_success = False
            
            # 方法1: 使用 DrissionPage 查找并点击 SVG
            try:
                # 获取所有页面元素的详细信息
                all_info = page.run_js("""
                    (function() {
                        var info = [];
                        var all = document.querySelectorAll('*');
                        for (var i = 0; i < all.length; i++) {
                            var el = all[i];
                            var rect = el.getBoundingClientRect();
                            if (rect.x > 450 && rect.y < 250 && rect.width > 10 && rect.width < 80) {
                                info.push({
                                    tag: el.tagName,
                                    class: el.className,
                                    x: rect.x,
                                    y: rect.y,
                                    w: rect.width,
                                    h: rect.height
                                });
                            }
                        }
                        return info;
                    })();
                """)
                print(f"[{self.user_id}] 📊 Found {len(all_info) if all_info else 0} potential click targets in top-right")
                if all_info:
                    for item in all_info[:5]:
                        print(f"[{self.user_id}]    - {item}")
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Element scan failed: {e}")
            
            # 方法2: 直接用坐标点击
            try:
                # 点击右上角区域的多个位置
                click_positions = [
                    (550, 180), (560, 190), (540, 170),
                    (570, 200), (530, 160), (580, 210)
                ]
                
                for x, y in click_positions:
                    print(f"[{self.user_id}] 🖱️ Clicking at ({x}, {y})...")
                    
                    # 使用 JavaScript 点击
                    page.run_js(f"""
                        (function() {{
                            var elem = document.elementFromPoint({x}, {y});
                            if (elem) {{
                                console.log('Clicking:', elem.tagName, elem.className);
                                elem.click();
                                
                                // 也尝试触发 MouseEvent
                                var event = new MouseEvent('click', {{
                                    bubbles: true,
                                    cancelable: true,
                                    view: window,
                                    clientX: {x},
                                    clientY: {y}
                                }});
                                elem.dispatchEvent(event);
                            }}
                        }})();
                    """)
                    
                    time.sleep(1)
                    
                    # 检查是否有 canvas 出现
                    canvases = page.eles('tag:canvas')
                    for canvas in canvases:
                        try:
                            size = canvas.rect.size
                            if size[0] > 100 and size[1] > 100:
                                print(f"[{self.user_id}] ✅ Found QR canvas after clicking ({x}, {y})")
                                switch_success = True
                                break
                        except:
                            continue
                    
                    if switch_success:
                        break
                        
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Position click failed: {e}")
            
            # 方法3: 查找并点击包含特定属性的元素
            if not switch_success:
                try:
                    # 查找所有可能是切换按钮的元素
                    js_find_and_click = """
                    (function() {
                        // 查找右上角的可点击元素
                        var elements = document.querySelectorAll('svg, img, div, span, button, a');
                        for (var el of elements) {
                            var rect = el.getBoundingClientRect();
                            // 在登录框右上角区域
                            if (rect.x > 450 && rect.x < 650 && rect.y > 100 && rect.y < 300) {
                                if (rect.width > 10 && rect.width < 80 && rect.height > 10 && rect.height < 80) {
                                    el.click();
                                    return 'clicked: ' + el.tagName + ' at ' + rect.x + ',' + rect.y;
                                }
                            }
                        }
                        return 'no element found';
                    })();
                    """
                    result = page.run_js(js_find_and_click)
                    print(f"[{self.user_id}] 📍 Method 3 result: {result}")
                    time.sleep(2)
                    
                    # 再次检查 canvas
                    canvases = page.eles('tag:canvas')
                    for canvas in canvases:
                        try:
                            size = canvas.rect.size
                            if size[0] > 100 and size[1] > 100:
                                switch_success = True
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Method 3 failed: {e}")
            
            # 等待QR码渲染
            if switch_success:
                print(f"[{self.user_id}] ✅ Successfully switched to QR mode")
            else:
                print(f"[{self.user_id}] ⚠️ Could not confirm QR mode switch")
            
            print(f"[{self.user_id}] ⏳ Waiting for QR code to render...")
            time.sleep(3)
            
            # ========== 捕获QR码 ==========
            qr_image = None
            
            # 策略1: 从 canvas 获取
            try:
                canvases = page.eles('tag:canvas')
                print(f"[{self.user_id}] 🔍 Found {len(canvases)} canvas elements")
                
                for i, canvas in enumerate(canvases):
                    try:
                        size = canvas.rect.size
                        print(f"[{self.user_id}]    Canvas {i}: size={size}")
                        
                        if size[0] > 100 and size[1] > 100:
                            # 尝试直接截图
                            qr_image = canvas.get_screenshot(as_base64=True)
                            if qr_image:
                                print(f"[{self.user_id}] ✅ Captured QR from canvas {i}")
                                break
                    except Exception as e:
                        print(f"[{self.user_id}] ⚠️ Canvas {i} capture failed: {e}")
                        continue
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Canvas strategy failed: {e}")
            
            # 策略2: 使用 JS 提取 canvas 数据
            if not qr_image:
                try:
                    qr_image = page.run_js("""
                        (function() {
                            var canvases = document.querySelectorAll('canvas');
                            for (var canvas of canvases) {
                                if (canvas.width > 100 && canvas.height > 100) {
                                    try {
                                        return canvas.toDataURL('image/png').split('base64,')[1];
                                    } catch(e) {}
                                }
                            }
                            return null;
                        })();
                    """)
                    if qr_image:
                        print(f"[{self.user_id}] ✅ Captured QR via JS extraction")
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ JS extraction failed: {e}")
            
            # 策略3: 查找 base64 图片
            if not qr_image:
                try:
                    imgs = page.eles('tag:img')
                    for img in imgs:
                        src = img.attr('src') or ''
                        if 'base64' in src:
                            try:
                                size = img.rect.size
                                if size[0] > 80 and size[1] > 80:
                                    qr_image = src.split('base64,')[1]
                                    print(f"[{self.user_id}] ✅ Found QR in base64 img")
                                    break
                            except:
                                continue
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Base64 img search failed: {e}")
            
            # 返回结果
            if qr_image:
                return {"status": "waiting_scan", "qr_image": qr_image}
            else:
                print(f"[{self.user_id}] ⚠️ QR not found, returning full page screenshot")
                base64_str = page.get_screenshot(as_base64=True)
                return {
                    "status": "waiting_scan",
                    "qr_image": base64_str,
                    "note": "full_page_fallback"
                }
                
        except Exception as e:
            print(f"[{self.user_id}] ❌ Error getting QR: {e}")
            import traceback
            traceback.print_exc()
            
            if self.page:
                try:
                    base64_str = self.page.get_screenshot(as_base64=True)
                    return {"status": "waiting_scan", "qr_image": base64_str, "note": "error_fallback"}
                except:
                    pass
            return {"status": "error", "msg": str(e)}

    def check_login_status(self):
        """检查登录状态"""
        if not self.page:
            return False
            
        try:
            cookies_dict = self._get_cookies_dict()
            
            if 'web_session' in cookies_dict or 'a1' in cookies_dict:
                print(f"[{self.user_id}] 🍪 Found login cookies!")
                try:
                    self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=15)
                    if "creator" in self.page.url and "login" not in self.page.url:
                        return True
                except:
                    pass
                return True
            
            if "creator/home" in self.page.url:
                return True
            
            if self.page.ele('text:发布笔记', timeout=1):
                return True
                
            return False
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Check login error: {e}")
            return False
    
    def get_cookies(self):
        if not self.page:
            return None
        try:
            return self.page.cookies()
        except:
            return None

    def close(self):
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
        if os.path.exists(self.user_data_dir):
            try:
                shutil.rmtree(self.user_data_dir)
            except:
                pass

    def publish_content(self, cookies: str, publish_type: str, files: list, title: str, desc: str, proxy_url: str = None, user_agent: str = None):
        """发布内容"""
        try:
            page = self.start_browser(proxy_url, user_agent, clear_data=False)
            page.get("https://creator.xiaohongshu.com")
            
            if cookies:
                try:
                    if isinstance(cookies, str):
                        import json
                        cookies_obj = json.loads(cookies)
                    else:
                        cookies_obj = cookies
                    
                    page.set.cookies(cookies_obj)
                    time.sleep(1)
                    page.refresh()
                    time.sleep(3)
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Error setting cookies: {e}")

            if "login" in page.url:
                raise Exception("Cookie expired or not logged in")

            page.get('https://creator.xiaohongshu.com/publish/publish')
            
            if publish_type == 'image':
                try:
                    image_tab = self.page.ele('text:图文', timeout=5)
                    if image_tab:
                        image_tab.click()
                        time.sleep(1)
                except:
                    pass

            upload_input = page.ele('tag:input@type=file', timeout=10)
            if not upload_input:
                raise Exception("Upload input not found")
                
            upload_input.input(files)
            
            if publish_type == 'video':
                page.wait.ele('text:重新上传', timeout=120)
            else:
                time.sleep(5)

            ele_title = page.ele('@@placeholder=填写标题')
            if ele_title: ele_title.input(title)
            
            ele_desc = page.ele('.ql-editor')
            if ele_desc: ele_desc.input(desc)

            btn_publish = page.ele('text:发布', index=1)
            if btn_publish:
                btn_publish.click()
                page.wait(3)
            
            return True, "Publish successful"

        except Exception as e:
            return False, str(e)
            
        finally:
            self.close()
            for f in files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass
