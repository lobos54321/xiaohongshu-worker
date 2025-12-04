from DrissionPage import ChromiumPage, ChromiumOptions
import platform
import os

print(f"OS: {platform.system()}")

co = ChromiumOptions()
if platform.system() == 'Linux':
    print("Configuring for Linux...")
    co.set_browser_path('/usr/bin/chromium')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.headless(True)
else:
    print("Configuring for Mac/Windows...")
    # Try native headless
    co.set_argument('--headless=new')

co.auto_port()
print("Options set. Starting browser...")

try:
    page = ChromiumPage(co)
    print("Browser started successfully!")
    page.quit()
except Exception as e:
    print(f"Error starting browser: {e}")
