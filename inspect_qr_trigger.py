#!/usr/bin/env python3
"""
Script to identify the QR icon/button that needs to be clicked
"""
import time
from DrissionPage import ChromiumPage, ChromiumOptions

def find_qr_trigger():
    options = ChromiumOptions()
    options.set_argument('--headless=new')
    options.set_argument('--disable-gpu')
    options.set_argument('--no-sandbox')
    
    page = ChromiumPage(addr_or_opts=options)
    
    try:
        print("🌐 Navigating to login page...")
        page.get('https://creator.xiaohongshu.com/login', timeout=30)
        page.wait.doc_loaded(timeout=20)
        time.sleep(3)
        
        print(f"✅ Page loaded. URL: {page.url}\n")
        
        # Take initial screenshot
        page.get_screenshot(path='qr_trigger_before.png', full_page=False)
        print("📸 Saved qr_trigger_before.png\n")
        
        # Find all clickable elements in the login area
        result = page.run_js("""
            (function() {
                var results = [];
                
                // Find all elements with cursor: pointer or onclick
                var allElements = document.querySelectorAll('*');
                
                for (var el of allElements) {
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    
                    // Filter for elements in the top-right area (x > 800, y < 400)
                    if (rect.x > 700 && rect.y < 500 && 
                        (style.cursor === 'pointer' || el.onclick || el.classList.contains('clickable'))) {
                        
                        results.push({
                            tag: el.tagName.toLowerCase(),
                            class: el.className.substring(0, 100),
                            id: el.id || '',
                            cursor: style.cursor,
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            centerX: Math.round(rect.x + rect.width/2),
                            centerY: Math.round(rect.y + rect.height/2),
                            html: el.outerHTML.substring(0, 200)
                        });
                    }
                }
                
                return results;
            })();
        """)
        
        print("🎯 Clickable elements in top-right area:")
        if result:
            for i, el in enumerate(result):
                print(f"\n[{i+1}] <{el['tag']}>")
                if el['class']:
                    print(f"    class: {el['class']}")
                if el['id']:
                    print(f"    id: {el['id']}")
                print(f"    position: ({el['x']}, {el['y']})")
                print(f"    size: {el['width']}x{el['height']}")
                print(f"    center: ({el['centerX']}, {el['centerY']})")
                print(f"    html: {el['html'][:100]}...")
        else:
            print("   ❌ No clickable elements found!")
        
        # Try to find SVG or icon elements that might be the QR trigger
        print("\n🔍 Looking for SVG/icon elements...")
        svgs = page.run_js("""
            (function() {
                var svgs = document.querySelectorAll('svg');
                var results = [];
                
                for (var svg of svgs) {
                    var rect = svg.getBoundingClientRect();
                    if (rect.x > 700 && rect.y < 500) {
                        results.push({
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            centerX: Math.round(rect.x + rect.width/2),
                            centerY: Math.round(rect.y + rect.height/2),
                            parent: svg.parentElement.tagName,
                            parentClass: svg.parentElement.className.substring(0, 100)
                        });
                    }
                }
                
                return results;
            })();
        """)
        
        if svgs:
            for i, svg in enumerate(svgs):
                print(f"\n   SVG {i+1}:")
                print(f"      position: ({svg['x']}, {svg['y']})")
                print(f"      size: {svg['width']}x{svg['height']}")
                print(f"      center: ({svg['centerX']}, {svg['centerY']})")
                print(f"      parent: <{svg['parent']}> class={svg['parentClass']}")
        
        # Look for elements with QR-related classes or text
        print("\n🔍 Looking for QR-related elements...")
        qr_elements = page.run_js("""
            (function() {
                var results = [];
                var searchTerms = ['qr', 'code', '扫码', '二维码', 'scan'];
                
                var walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_ELEMENT,
                    null,
                    false
                );
                
                var node;
                while(node = walker.nextNode()) {
                    var className = node.className || '';
                    var id = node.id || '';
                    var text = node.textContent || '';
                    
                    for (var term of searchTerms) {
                        if (className.toLowerCase().includes(term) || 
                            id.toLowerCase().includes(term) ||
                            text.includes(term)) {
                            
                            var rect = node.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                results.push({
                                    tag: node.tagName.toLowerCase(),
                                    class: className.substring(0, 100),
                                    id: id,
                                    x: Math.round(rect.x),
                                    y: Math.round(rect.y),
                                    width: Math.round(rect.width),
                                    height: Math.round(rect.height),
                                    text: text.substring(0, 50)
                                });
                                break;
                            }
                        }
                    }
                }
                
                return results.slice(0, 10); // Limit to 10 results
            })();
        """)
        
        if qr_elements:
            for i, el in enumerate(qr_elements):
                print(f"\n   Element {i+1}:")
                print(f"      tag: <{el['tag']}>")
                if el['class']:
                    print(f"      class: {el['class']}")
                print(f"      position: ({el['x']}, {el['y']})")
                print(f"      size: {el['width']}x{el['height']}")
                if el['text'].strip():
                    print(f"      text: {el['text'].strip()}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        page.quit()

if __name__ == "__main__":
    find_qr_trigger()
