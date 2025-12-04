#!/usr/bin/env python3
"""
Debug script to inspect XHS login page and find the QR code trigger
"""
import time
from DrissionPage import ChromiumPage, ChromiumOptions

def inspect_login_page():
    # Setup browser
    options = ChromiumOptions()
    options.set_argument('--headless=new')
    options.set_argument('--disable-gpu')
    options.set_argument('--no-sandbox')
    
    page = ChromiumPage(addr_or_opts=options)
    
    try:
        print("🌐 Navigating to login page...")
        page.get('https://creator.xiaohongshu.com/login', timeout=30)
        
        print("⏳ Waiting for page load...")
        page.wait.doc_loaded(timeout=20)
        time.sleep(3)
        
        print(f"✅ Page loaded. URL: {page.url}")
        
        # Get page structure
        print("\n" + "="*60)
        print("📊 Analyzing page structure...")
        print("="*60)
        
        result = page.run_js("""
            (function() {
                // Find all clickable elements in the login box area
                var results = {
                    foundElements: [],
                    loginBoxInfo: null
                };
                
                // 1. Find the login box
                var walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );
                
                var node;
                var loginBox = null;
                
                while(node = walker.nextNode()) {
                    if (node.textContent.includes('短信登录') || 
                        node.textContent.includes('验证码登录')) {
                        var parent = node.parentElement;
                        for (var i = 0; i < 20 && parent; i++) {
                            var rect = parent.getBoundingClientRect();
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
                
                if (loginBox) {
                    var boxRect = loginBox.getBoundingClientRect();
                    results.loginBoxInfo = {
                        x: Math.round(boxRect.x),
                        y: Math.round(boxRect.y),
                        width: Math.round(boxRect.width),
                        height: Math.round(boxRect.height),
                        right: Math.round(boxRect.right),
                        bottom: Math.round(boxRect.bottom)
                    };
                    
                    // 2. Find all clickable elements in top-right area of login box
                    var topRightX = boxRect.right - 100; // right edge - 100px
                    var topRightY = boxRect.top + 100;   // top edge + 100px
                    
                    var allElements = loginBox.querySelectorAll('*');
                    allElements.forEach(function(el) {
                        var rect = el.getBoundingClientRect();
                        
                        // Check if element is in top-right corner
                        if (rect.right > topRightX && rect.top < topRightY) {
                            var tagName = el.tagName.toLowerCase();
                            var className = el.className || '';
                            var id = el.id || '';
                            var onclick = el.onclick ? 'yes' : 'no';
                            var cursor = window.getComputedStyle(el).cursor;
                            
                            results.foundElements.push({
                                tag: tagName,
                                class: String(className).substring(0, 100),
                                id: id,
                                hasOnClick: onclick,
                                cursor: cursor,
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height),
                                centerX: Math.round(rect.x + rect.width/2),
                                centerY: Math.round(rect.y + rect.height/2),
                                text: el.textContent.substring(0, 50)
                            });
                        }
                    });
                }
                
                return results;
            })();
        """)
        
        if result:
            print("\n📦 Login Box Info:")
            if result.get('loginBoxInfo'):
                box = result['loginBoxInfo']
                print(f"   Position: ({box['x']}, {box['y']})")
                print(f"   Size: {box['width']}x{box['height']}")
                print(f"   Right edge: {box['right']}")
                print(f"   Bottom edge: {box['bottom']}")
            else:
                print("   ❌ Login box not found!")
            
            print("\n🎯 Clickable Elements in Top-Right Corner:")
            elements = result.get('foundElements', [])
            if elements:
                for i, el in enumerate(elements):
                    print(f"\n   [{i+1}] <{el['tag']}>")
                    if el['class']:
                        print(f"       class: {el['class']}")
                    if el['id']:
                        print(f"       id: {el['id']}")
                    print(f"       cursor: {el['cursor']}")
                    print(f"       position: ({el['x']}, {el['y']})")
                    print(f"       size: {el['width']}x{el['height']}")
                    print(f"       center: ({el['centerX']}, {el['centerY']})")
                    if el['text'].strip():
                        print(f"       text: {el['text'].strip()}")
            else:
                print("   ❌ No elements found in top-right corner!")
        
        # Take a screenshot
        print("\n📸 Taking screenshot...")
        screenshot_path = "login_page_debug.png"
        page.get_screenshot(path=screenshot_path, full_page=False)
        print(f"✅ Screenshot saved to: {screenshot_path}")
        
        # Check for existing QR code elements
        print("\n🔍 Looking for QR code related elements...")
        canvases = page.eles('tag:canvas')
        print(f"   Found {len(canvases)} canvas elements")
        
        qr_texts = page.eles('text:扫码') or page.eles('text:二维码') or page.eles('text:QR')
        print(f"   Found {len(qr_texts)} elements with QR-related text")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        page.quit()

if __name__ == "__main__":
    inspect_login_page()
