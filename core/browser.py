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

    def _get_options(self, proxy_url: str = None, user_agent: str = None, headless: bool = False):
        co = ChromiumOptions()
        
        import platform
        if platform.system() == 'Linux':
            co.set_browser_path('/usr/bin/chromium')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-setuid-sandbox')  # 增加稳定性
            co.set_argument('--no-zygote')               # 增加稳定性
            
            if headless:
                co.set_argument('--headless=new')
            else:
                co.headless(False)
        else:
            # Mac/Windows local dev
            if headless:
                co.set_argument('--headless=new')
            else:
                # co.headless(False) # Local dev default
                pass
            
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
        """Initialize browser session with fallback"""
        
        # 1. 尝试加载保存的 UA
        ua_path = os.path.join(self.user_data_dir, "ua.txt")
        if os.path.exists(ua_path):
            try:
                with open(ua_path, "r") as f:
                    saved_ua = f.read().strip()
                    if saved_ua:
                        user_agent = saved_ua
                        print(f"[{self.user_id}] 🍪 Loaded saved User-Agent")
            except Exception as e:
                print(f"[{self.user_id}] ⚠️ Failed to load saved UA: {e}")

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
                    # 注意：如果我们要保留 cookie，可能不能完全删除 user_data_dir
                    # 但 DrissionPage 的 user_data_dir 包含很多缓存，
                    # 我们只需要保留 cookies.json 和 ua.txt
                    # 所以先备份它们，清理后再放回去
                    
                    # 备份
                    cookie_path = os.path.join(self.user_data_dir, "cookies.json")
                    backup_cookies = None
                    if os.path.exists(cookie_path):
                        with open(cookie_path, "r") as f:
                            backup_cookies = f.read()
                            
                    backup_ua = None
                    if os.path.exists(ua_path):
                        with open(ua_path, "r") as f:
                            backup_ua = f.read()

                    shutil.rmtree(self.user_data_dir)
                    os.makedirs(self.user_data_dir, exist_ok=True)
                    
                    # 还原
                    if backup_cookies:
                        with open(cookie_path, "w") as f:
                            f.write(backup_cookies)
                    if backup_ua:
                        with open(ua_path, "w") as f:
                            f.write(backup_ua)
                            
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
                time.sleep(1)  # 等待 Xvfb 完全启动
                print(f"[{self.user_id}] 🖥️ Started virtual display")
            else:
                print(f"[{self.user_id}] 🖥️ Using existing DISPLAY: {display_env}")

        # 尝试启动浏览器 - 首先尝试非 headless 模式 (更隐蔽)
        try:
            print(f"[{self.user_id}] 🚀 Starting new browser instance (Headless: False)...")
            co = self._get_options(proxy_url, user_agent, headless=False)
            self.page = ChromiumPage(co)
            
            # 2. 注入保存的 Cookie
            cookie_path = os.path.join(self.user_data_dir, "cookies.json")
            if os.path.exists(cookie_path):
                try:
                    import json
                    with open(cookie_path, "r") as f:
                        cookies = json.load(f)
                    
                    print(f"[{self.user_id}] 🍪 Injecting {len(cookies)} cookies...")
                    # 必须先访问域名才能注入 cookie
                    self.page.get("https://www.xiaohongshu.com", timeout=30)
                    
                    # DrissionPage set.cookies 接收 list 或 dict
                    self.page.set.cookies(cookies)
                    
                    self.page.refresh()
                    print(f"[{self.user_id}] ✅ Cookies injected successfully")
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Failed to inject cookies: {e}")
            
            self._inject_stealth_scripts()
            print(f"[{self.user_id}] ✅ Browser started successfully (Headless: False)")
            return self.page
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Failed to start visible browser: {e}")
            print(f"[{self.user_id}] 🔄 Falling back to headless mode...")
            
            # 失败回退到 headless 模式
            try:
                co = self._get_options(proxy_url, user_agent, headless=True)
                self.page = ChromiumPage(co)
                
                # 同样尝试注入 Cookie
                if os.path.exists(cookie_path):
                    try:
                        import json
                        with open(cookie_path, "r") as f:
                            cookies = json.load(f)
                        self.page.get("https://www.xiaohongshu.com", timeout=30)
                        self.page.set.cookies(cookies)
                        self.page.refresh()
                    except:
                        pass
                
                self._inject_stealth_scripts()
                print(f"[{self.user_id}] ✅ Browser started successfully (Headless: True)")
                return self.page
            except Exception as e2:
                print(f"[{self.user_id}] ❌ Failed to start browser in both modes: {e2}")
                raise e2

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

    def _debug_page_layout(self):
        """
        调试方法：输出页面布局信息
        这是定位问题的关键！
        """
        try:
            # 1. 获取视口尺寸
            viewport = self.page.run_js("""
                return {
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    scrollWidth: document.body.scrollWidth,
                    scrollHeight: document.body.scrollHeight
                };
            """)
            print(f"[{self.user_id}] 📐 Viewport: {viewport}")
            
            # 2. 查找"短信登录"文字的位置
            sms_info = self.page.run_js("""
                (function() {
                    var walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    var node;
                    while(node = walker.nextNode()) {
                        if (node.textContent.includes('短信登录')) {
                            var parent = node.parentElement;
                            var rect = parent.getBoundingClientRect();
                            return {
                                found: true,
                                text: '短信登录',
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            };
                        }
                    }
                    return {found: false};
                })();
            """)
            print(f"[{self.user_id}] 📍 '短信登录' 位置: {sms_info}")
            
            # 3. 查找登录框容器
            login_box = self.page.run_js("""
                (function() {
                    var walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    var node;
                    while(node = walker.nextNode()) {
                        if (node.textContent.includes('短信登录')) {
                            var parent = node.parentElement;
                            // 向上查找直到找到足够大的容器
                            for (var i = 0; i < 20 && parent; i++) {
                                var rect = parent.getBoundingClientRect();
                                if (rect.width > 300 && rect.height > 300 && rect.width < 800) {
                                    return {
                                        found: true,
                                        x: Math.round(rect.x),
                                        y: Math.round(rect.y),
                                        width: Math.round(rect.width),
                                        height: Math.round(rect.height),
                                        tag: parent.tagName,
                                        class: (parent.className || '').substring(0, 50)
                                    };
                                }
                                parent = parent.parentElement;
                            }
                        }
                    }
                    return {found: false};
                })();
            """)
            print(f"[{self.user_id}] 📦 登录框容器: {login_box}")
            
            # 4. 查找所有 SVG 的位置
            svgs = self.page.run_js("""
                (function() {
                    var svgs = document.querySelectorAll('svg');
                    var results = [];
                    for (var i = 0; i < svgs.length; i++) {
                        var rect = svgs[i].getBoundingClientRect();
                        if (rect.width > 5 && rect.height > 5) {
                            results.push({
                                index: i,
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            });
                        }
                    }
                    return results;
                })();
            """)
            print(f"[{self.user_id}] 🎨 SVG 元素列表:")
            for svg in svgs:
                print(f"[{self.user_id}]    SVG[{svg['index']}]: ({svg['x']}, {svg['y']}) {svg['width']}x{svg['height']}")
            
            return {
                'viewport': viewport,
                'sms_info': sms_info,
                'login_box': login_box,
                'svgs': svgs
            }
            
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Debug layout failed: {e}")
            return None

    def _find_qr_icon_position(self):
        """
        动态查找QR图标的正确位置
        基于登录框位置计算，而不是硬编码坐标
        """
        try:
            # 方法1: 基于登录框位置计算QR图标位置
            result = self.page.run_js("""
                (function() {
                    // 查找包含"短信登录"的元素，然后向上找登录框
                    var walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    var node;
                    var loginBox = null;
                    
                    while(node = walker.nextNode()) {
                        if (node.textContent.includes('短信登录')) {
                            var parent = node.parentElement;
                            for (var i = 0; i < 20 && parent; i++) {
                                var rect = parent.getBoundingClientRect();
                                // 登录框特征：宽度300-600，高度300-600
                                if (rect.width > 300 && rect.width < 700 && 
                                    rect.height > 300 && rect.height < 700) {
                                    loginBox = parent;
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                            break;
                        }
                    }
                    
                    if (!loginBox) {
                        return {found: false, reason: 'login_box_not_found'};
                    }
                    
                    var boxRect = loginBox.getBoundingClientRect();
                    
                    // QR图标在登录框右上角
                    // 计算右上角位置（向内偏移20-40像素）
                    var qrIconX = boxRect.right - 30;
                    var qrIconY = boxRect.top + 30;
                    
                    return {
                        found: true,
                        loginBox: {
                            x: Math.round(boxRect.x),
                            y: Math.round(boxRect.y),
                            width: Math.round(boxRect.width),
                            height: Math.round(boxRect.height),
                            right: Math.round(boxRect.right),
                            bottom: Math.round(boxRect.bottom)
                        },
                        qrIconPosition: {
                            x: Math.round(qrIconX),
                            y: Math.round(qrIconY)
                        }
                    };
                })();
            """)
            
            print(f"[{self.user_id}] 🎯 QR图标位置计算结果: {result}")
            return result
            
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Find QR icon position failed: {e}")
            return None

    def _click_at_position(self, x, y):
        """在指定位置点击"""
        try:
            result = self.page.run_js(f"""
                (function() {{
                    var elem = document.elementFromPoint({x}, {y});
                    if (elem) {{
                        // 创建并派发点击事件
                        var event = new MouseEvent('click', {{
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: {x},
                            clientY: {y}
                        }});
                        elem.dispatchEvent(event);
                        
                        return {{
                            clicked: true,
                            element: elem.tagName,
                            class: (elem.className || '').substring(0, 50)
                        }};
                    }}
                    return {{clicked: false, reason: 'no_element_at_position'}};
                }})();
            """)
            print(f"[{self.user_id}] 🖱️ Click at ({x}, {y}): {result}")
            return result
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Click failed: {e}")
            return None

    def _is_qr_mode(self):
        """检查是否已切换到QR码模式"""
        try:
            # 检查是否有 canvas（QR码用canvas渲染）
            result = self.page.run_js("""
                (function() {
                    var canvases = document.querySelectorAll('canvas');
                    for (var canvas of canvases) {
                        if (canvas.width > 100 && canvas.height > 100) {
                            var rect = canvas.getBoundingClientRect();
                            return {
                                found: true,
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: canvas.width,
                                height: canvas.height
                            };
                        }
                    }
                    return {found: false};
                })();
            """)
            
            if result and result.get('found'):
                print(f"[{self.user_id}] ✅ QR mode detected: canvas at {result}")
                return True
            
            # 检查是否有扫码相关文字
            has_scan_text = self.page.ele('text:打开小红书', timeout=1) or \
                           self.page.ele('text:扫一扫', timeout=1) or \
                           self.page.ele('text:扫码登录', timeout=1)
            
            if has_scan_text:
                print(f"[{self.user_id}] ✅ QR mode detected: found scan text")
                return True
                
            return False
        except:
            return False

    def _capture_qr_code(self):
        """捕获QR码图片"""
        try:
            # 方法1: 从 canvas 获取
            qr_data = self.page.run_js("""
                (function() {
                    var canvases = document.querySelectorAll('canvas');
                    for (var canvas of canvases) {
                        if (canvas.width > 100 && canvas.height > 100) {
                            try {
                                return canvas.toDataURL('image/png').split('base64,')[1];
                            } catch(e) {
                                // canvas可能被污染
                            }
                        }
                    }
                    return null;
                })();
            """)
            
            if qr_data:
                print(f"[{self.user_id}] ✅ Captured QR from canvas via JS")
                return qr_data
            
            # 方法2: 截取 canvas 元素
            canvases = self.page.eles('tag:canvas')
            for canvas in canvases:
                try:
                    size = canvas.rect.size
                    if size[0] > 100 and size[1] > 100:
                        qr_data = canvas.get_screenshot(as_base64=True)
                        if qr_data:
                            print(f"[{self.user_id}] ✅ Captured QR from canvas element")
                            return qr_data
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Canvas capture failed: {e}")
            
            # 方法3: 查找 base64 图片
            imgs = self.page.eles('tag:img')
            for img in imgs:
                try:
                    src = img.attr('src') or ''
                    if 'base64' in src:
                        size = img.rect.size
                        if size[0] > 80 and size[1] > 80:
                            return src.split('base64,')[1]
                except:
                    continue
            
            return None
            
        except Exception as e:
            print(f"[{self.user_id}] ⚠️ Capture QR failed: {e}")
            return None

    def get_login_qrcode(self, proxy_url: str = None, user_agent: str = None):
        """
        获取登录二维码
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
            
            # 等待关键元素出现 - 更鲁棒的等待策略
            print(f"[{self.user_id}] 🔍 Waiting for login elements to render...")
            time.sleep(5)  # 首先等待5秒让JS初始化
            
            # 尝试等待"短信登录"文字出现，最多重试3次
            login_element_found = False
            for attempt in range(3):
                try:
                    # 检查是否有"短信登录"或"验证码登录"文字
                    sms_login = page.ele('text:短信登录', timeout=5) or page.ele('text:验证码登录', timeout=5)
                    if sms_login:
                        print(f"[{self.user_id}] ✅ Login element found!")
                        login_element_found = True
                        break
                except:
                    if attempt < 2:
                        print(f"[{self.user_id}] ⚠️  Login element not found, retrying... (attempt {attempt+1}/3)")
                        time.sleep(3)
                    else:
                        print(f"[{self.user_id}] ⚠️  Login element still not found after 3 attempts")
            
            # 额外等待确保页面完全渲染
            time.sleep(2)
            
            self._inject_stealth_scripts()
            
            print(f"[{self.user_id}] 📍 Current URL: {page.url}")
            
            # ========== 关键步骤：调试页面布局 ==========
            print(f"[{self.user_id}] 🔍 Analyzing page layout...")
            layout_info = self._debug_page_layout()
            
            # ========== 动态计算QR图标位置 ==========
            print(f"[{self.user_id}] 🎯 Finding QR icon position...")
            qr_position = self._find_qr_icon_position()
            
            if not qr_position or not qr_position.get('found'):
                print(f"[{self.user_id}] ❌ Could not find login box, trying fallback...")
                # 备选方案：基于视口尺寸估算
                viewport = layout_info.get('viewport', {}) if layout_info else {}
                width = viewport.get('innerWidth', 1920)
                
                # 假设登录框在右侧 40% 区域
                # 登录框宽度约 400px，右边距约 100px
                estimated_x = width - 100 - 30  # 右边距-图标偏移
                estimated_y = 200  # 假设距顶部 200px
                
                print(f"[{self.user_id}] 📐 Using estimated position: ({estimated_x}, {estimated_y})")
                qr_position = {
                    'found': True,
                    'qrIconPosition': {'x': estimated_x, 'y': estimated_y}
                }
            
            
            # ========== 点击QR图标 (使用 Actions API 模拟真实鼠标) ==========
            if qr_position and qr_position.get('found'):
                click_x = qr_position['qrIconPosition']['x']
                click_y = qr_position['qrIconPosition']['y']
                
                print(f"[{self.user_id}] 🖱️  Using Actions API to click QR icon at ({click_x}, {click_y})...")
                
                # 使用 Actions API 进行类人操作
                from DrissionPage.common import Actions
                ac = Actions(page)
                
                # 尝试多个偏移位置，使用真实的鼠标移动和点击
                offsets = [(0, 0), (-10, 0), (-5, -5), (5, 5), (-10, -10)]
                
                for dx, dy in offsets:
                    target_x = click_x + dx
                    target_y = click_y + dy
                    
                    print(f"[{self.user_id}] 🎯 Attempting click at ({target_x}, {target_y})...")
                    
                    # 模拟真实鼠标移动：先移到附近，再移到目标
                    ac.move_to((target_x - 50, target_y - 50))  # 移动到附近
                    time.sleep(0.3)  # 短暂停顿
                    ac.move_to((target_x, target_y))  # 移动到目标
                    time.sleep(0.2)  # 短暂停顿
                    ac.click()  # 点击
                    
                    time.sleep(2)  # 等待2秒让页面响应
                    
                    # 检查是否成功切换
                    if self._is_qr_mode():
                        print(f"[{self.user_id}] ✅ Successfully switched to QR mode with Actions API!")
                        break
                    else:
                        print(f"[{self.user_id}] ⚠️  QR mode not detected, trying next offset...")
            
            # ========== 等待QR码渲染 ==========
            time.sleep(3)  # 增加等待时间确保二维码完全加载
                
            # ========== 捕获QR码 ==========
            if self._is_qr_mode():
                qr_image = self._capture_qr_code()
                if qr_image:
                    print(f"[{self.user_id}] ✅ QR code captured successfully")
                    return {"status": "waiting_scan", "qr_image": qr_image}
            
            # 备选：返回全页面截图
            print(f"[{self.user_id}] ⚠️ QR not found, returning full page screenshot")
            
            # 截取视口（而不是整个页面）
            base64_str = page.get_screenshot(as_base64=True, full_page=False)
            return {
                "status": "waiting_scan",
                "qr_image": base64_str,
                "note": "full_page_fallback",
                "debug_info": {
                    "layout": layout_info,
                    "qr_position": qr_position
                }
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
            
            # 只有 web_session 才是真正的登录凭证
            if 'web_session' in cookies_dict:
                print(f"[{self.user_id}] 🍪 Found web_session cookie, verifying validity...")
                # 不要直接返回 True，而是去访问页面验证
                try:
                    if "creator" not in self.page.url:
                        self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=15)
                    
                    # 检查是否被重定向回登录页
                    if "login" in self.page.url:
                        print(f"[{self.user_id}] ❌ Cookie invalid: Redirected to login page")
                        return False
                        
                    if "creator" in self.page.url:
                        print(f"[{self.user_id}] ✅ Verified login via URL check")
                        return True
                except Exception as e:
                    print(f"[{self.user_id}] ⚠️ Verification navigation failed: {e}")
                    return False
            
            # 如果只有 a1，尝试验证是否真的登录了
            if 'a1' in cookies_dict:
                try:
                    # 只有在当前不在 creator 页面时才跳转，避免刷新页面
                    if "creator" not in self.page.url:
                        self.page.get("https://creator.xiaohongshu.com/creator/home", timeout=15)
                    
                    if "creator" in self.page.url and "login" not in self.page.url:
                        print(f"[{self.user_id}] ✅ Verified login via URL check")
                        return True
                except:
                    pass
                # 如果跳转失败或 URL 不对，说明只有 a1 但没登录
            
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
