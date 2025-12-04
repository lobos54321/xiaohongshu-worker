from DrissionPage import ChromiumPage, ChromiumOptions
import time
import base64
import os
import json

def setup_browser():
    co = ChromiumOptions()
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    # Use a distinct user data dir to avoid conflicts
    co.set_user_data_path('test_browser_data')
    return ChromiumPage(co)

def log(msg):
    print(f"[TEST] {msg}")

def test_strategy_1_url(page):
    log("--- Testing Strategy 1: Direct URL ---")
    urls = [
        'https://creator.xiaohongshu.com/login?type=qrcode',
        'https://creator.xiaohongshu.com/login#qrcode'
    ]
    
    success = False
    for url in urls:
        log(f"Navigating to {url}")
        page.get(url)
        time.sleep(5)
        
        # Check for QR
        if page.ele('tag:canvas') or page.ele('.qrcode-img'):
            log(f"✅ SUCCESS: QR code found with URL {url}")
            page.get_screenshot(path='test_results', name='strategy_1_success.png')
            success = True
            break
        else:
            log(f"❌ FAILED: QR code NOT found with URL {url}")
            page.get_screenshot(path='test_results', name=f'strategy_1_fail_{url.split("?")[-1]}.png')
            
    return success

def test_strategy_4_canvas_extraction(page):
    log("--- Testing Strategy 4: Canvas Data Extraction ---")
    # This requires QR to be present.
    if not (page.ele('tag:canvas') or page.ele('.qrcode-img')):
        log("⚠️ QR code not present, cannot test canvas extraction.")
        return False
        
    js = """
    var canvas = document.querySelector('canvas');
    if (canvas) {
        return canvas.toDataURL('image/png');
    }
    return null;
    """
    try:
        data = page.run_js(js)
        if data:
            log("✅ SUCCESS: Extracted canvas data via JS")
            # Save it
            try:
                b64 = data.split(',')[1]
                with open('test_results/strategy_4_canvas.png', 'wb') as f:
                    f.write(base64.b64decode(b64))
                log("Saved extracted QR to test_results/strategy_4_canvas.png")
                return True
            except Exception as e:
                log(f"Error saving canvas: {e}")
        else:
            log("❌ FAILED: JS returned null (maybe no canvas element?)")
    except Exception as e:
        log(f"❌ FAILED: JS execution error: {e}")
        
    return False

def test_strategy_2_switch(page):
    log("--- Testing Strategy 2: Switch Logic ---")
    # Navigate to clean login page
    page.get('https://creator.xiaohongshu.com/login')
    time.sleep(3)
    
    if page.ele('tag:canvas') or page.ele('.qrcode-img'):
        log("⚠️ Already in QR mode, cannot test switch logic properly.")
        # But we can try to switch to SMS and back? No, let's just skip.
        return

    log("Initial State: SMS Mode (assumed)")
    page.get_screenshot(path='test_results', name='strategy_2_initial.png')

    # Sub-strategy: Tab Key
    log("Attempting Tab Key...")
    page.run_js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab'}))")
    time.sleep(1)
    if page.ele('tag:canvas'):
        log("✅ SUCCESS: Switched via Tab Key")
        return

    # Sub-strategy: Top-Right Coordinate Click
    log("Attempting Top-Right Coordinate Click...")
    
    # Find container
    login_box = page.ele('css:div[class*="login-box"]') or \
                page.ele('css:div[class*="login-container"]') or \
                page.ele('text:登录', index=0).parent().parent()
                
    if login_box:
        # JS Click Top-Right
        js = """
        var box = arguments[0];
        if(!box) return null;
        var r = box.getBoundingClientRect();
        // Click top-right (right - 20, top + 20)
        var x = r.right - 20;
        var y = r.top + 20;
        var el = document.elementFromPoint(x, y);
        if(el) el.click();
        return [x, y];
        """
        res = page.run_js(js, login_box)
        log(f"Clicked at coordinates: {res}")
        time.sleep(2)
        
        if page.ele('tag:canvas'):
            log("✅ SUCCESS: Switched via Top-Right Coordinate Click")
            return
        else:
            log("❌ FAILED: Coordinate Click did not switch mode")
            page.get_screenshot(path='test_results', name='strategy_2_fail_click.png')
    else:
        log("❌ FAILED: Could not find login box to calculate coordinates")

def has_qr(page):
    # Check for canvas
    if page.ele('tag:canvas'):
        return True
    # Check for base64 img
    imgs = page.eles('tag:img')
    for img in imgs:
        src = img.attr('src')
        if src and 'data:image/png;base64' in src:
            # Optional: Check size
            return True
    return False

def test_strategy_6_real_mouse(page):
    log("--- Testing Strategy 6: Real Mouse Events (JS) ---")
    # Navigate to clean login page
    page.get('https://creator.xiaohongshu.com/login')
    time.sleep(3)
    
    if has_qr(page):
        log("⚠️ Already in QR mode.")
        return

    # Find container
    login_box = page.ele('css:div[class*="login-box"]') or \
                page.ele('css:div[class*="login-container"]') or \
                page.ele('text:登录', index=0).parent().parent()
                
    if login_box:
        rect = login_box.rect
        # Target: Top-Right corner (right - 20, top + 20)
        cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
        cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
        cw = rect.size[0] if hasattr(rect, 'size') else rect.width
        
        target_x = cx + cw - 20
        target_y = cy + 20
        
        log(f"Simulating mouse events at ({target_x}, {target_y})")
        
        js = f"""
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
        page.run_js(js)
        time.sleep(2)
        
        if has_qr(page):
            log("✅ SUCCESS: Switched via Real Mouse Events")
            return True
        else:
            log("❌ FAILED: Real Mouse Events did not switch mode")
            page.get_screenshot(path='test_results', name='strategy_6_fail.png')
            return False
    return False

def test_strategy_7_actions(page):
    log("--- Testing Strategy 7: Actions API ---")
    from DrissionPage.common import Actions
    
    # Navigate to clean login page
    page.get('https://creator.xiaohongshu.com/login')
    time.sleep(3)
    
    if has_qr(page):
        log("⚠️ Already in QR mode.")
        return

    # Find container
    login_box = page.ele('css:div[class*="login-box"]') or \
                page.ele('css:div[class*="login-container"]') or \
                page.ele('text:登录', index=0).parent().parent()
                
    if login_box:
        rect = login_box.rect
        cx = rect.location[0] if hasattr(rect, 'location') else (rect[0] if isinstance(rect, tuple) else rect.x)
        cy = rect.location[1] if hasattr(rect, 'location') else (rect[1] if isinstance(rect, tuple) else rect.y)
        cw = rect.size[0] if hasattr(rect, 'size') else rect.width
        
        target_x = cx + cw - 25
        target_y = cy + 25
        
        log(f"Actions API move and click at ({target_x}, {target_y})")
        
        ac = Actions(page)
        ac.move_to((target_x, target_y)).click()
        time.sleep(2)
        
        if has_qr(page):
            log("✅ SUCCESS: Switched via Actions API")
            # Save screenshot of success
            page.get_screenshot(path='test_results', name='strategy_7_success.png')
            return True
        else:
            log("❌ FAILED: Actions API did not switch mode")
            page.get_screenshot(path='test_results', name='strategy_7_fail.png')
            
            # Dump HTML for debugging
            with open('test_results/login_box.html', 'w', encoding='utf-8') as f:
                f.write(login_box.html)
            log("Saved login box HTML to test_results/login_box.html")
            
            return False
    return False

if __name__ == "__main__":
    if not os.path.exists('test_results'):
        os.makedirs('test_results')
        
    page = setup_browser()
    try:
        # 1. Test URL Strategy
        s1 = test_strategy_1_url(page)
        
        # 2. Test Canvas Extraction (if s1 worked, we have QR)
        if s1:
            test_strategy_4_canvas_extraction(page)
        else:
            # 3. If URL failed to give QR, test Switch Strategy
            test_strategy_2_switch(page)
            
            # 4. Test Strategy 6 (Real Mouse)
            if not has_qr(page):
                test_strategy_6_real_mouse(page)
                
            # 5. Test Strategy 7 (Actions)
            if not has_qr(page):
                test_strategy_7_actions(page)
                
            # If switch worked, test Canvas Extraction
            if has_qr(page):
                test_strategy_4_canvas_extraction(page)
                
    except Exception as e:
        log(f"CRITICAL ERROR: {e}")
    finally:
        page.quit()
