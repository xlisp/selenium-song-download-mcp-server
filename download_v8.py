from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import pickle
import subprocess

# Ensure ChromeDriver (localhost) connections bypass any HTTP proxy
os.environ["no_proxy"] = os.environ.get("no_proxy", "") + ",127.0.0.1,localhost"
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost"
import re

def get_download_links_with_curl(detail_url):
    """
    从详情页获取下载链接 (新结构: /dls/<code>.html → JS 跳转到 quark/139)
    优先选 rmk (夸克 MP3),其次 rwk (夸克 WAV),再退到 rym/ryw (139.com)
    """
    try:
        from urllib.parse import urljoin

        # 抓详情页
        result = subprocess.run(
            ['curl', '-s', detail_url],
            capture_output=True, text=True
        )
        html = result.stdout

        # 找所有 /dls/ 链接
        dls_paths = re.findall(r'href="(/dls/[^"]+\.html)"', html)
        if not dls_paths:
            return []

        # 按偏好排序: rmk(夸克MP3) > rwk(夸克WAV) > 其它
        def rank(path):
            if 'rmk' in path: return 0
            if 'rwk' in path: return 1
            if 'rym' in path: return 2
            if 'ryw' in path: return 3
            return 4
        dls_paths.sort(key=rank)
        dls_url = urljoin(detail_url, dls_paths[0])

        # /dls/ 页是一段 JS 跳转,提取真实 URL
        result2 = subprocess.run(
            ['curl', '-s', dls_url],
            capture_output=True, text=True
        )
        m = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", result2.stdout)
        return [m.group(1)] if m else []

    except Exception as e:
        print(f"获取下载链接时出错: {e}")
        return []
## print(get_download_links_with_curl("https://www.xmwsyy.com/song/taylorswift-father-figure.html"))

def initialize_browser(download_folder="downloads"):
    """Initialize and return a Chrome browser with saved cookies if available"""
    # Create download directory if it doesn't exist
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
    
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    prefs = {"download.default_directory": os.path.abspath(download_folder)}
    chrome_options.add_experimental_option("prefs", prefs)
    
    # Initialize the Chrome driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Load cookies if they exist
    cookies_file = "quark_cookies.pkl"
    if os.path.exists(cookies_file):
        # First go to the domain
        driver.get("https://pan.quark.cn/")
        # Then add the cookies
        cookies = pickle.load(open(cookies_file, "rb"))
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"Could not load cookie: {e}")
        
        print("Loaded saved session. Refreshing page...")
        driver.refresh()
    else:
        # No saved session, need manual login
        driver.get("https://pan.quark.cn/")
        print("Please log in to your Quark account manually...")
        input("Press Enter once you've successfully logged in...")
        
        # Save cookies after login
        print("Saving your login session for future use...")
        pickle.dump(driver.get_cookies(), open(cookies_file, "wb"))
    
    return driver

def download_song(driver, song_name):
    """Download a single song using the existing browser session"""
    try:
        # 站点已改: /index/search/ 直接 GET 会 404,搜索框现在在首页上
        driver.get("https://www.xmwsyy.com/")

        # Wait for search input to load and enter song name
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "edtSearch"))
        )
        search_input.clear()
        search_input.send_keys(song_name)
        search_input.send_keys(Keys.RETURN)

        # 详情页 URL 已改为 /song/<slug>.html, 主结果包在 <article> 内
        result_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article a[href*='/song/']"))
        )
        
        link_url = result_link.get_attribute("href")
        print(f"Found song link: {link_url}")
        
        # Navigate to the link directly instead of clicking to avoid stale element issues
        driver.get(link_url)
        
        # On the detail page, find and click the "夸克MP3链接下载" button
        # Using a more robust selector that works with the actual page structure
        #quark_download_btn = WebDriverWait(driver, 10).until(
        #    EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, '/download/') and .//h2[contains(@style, 'background:#f7de0e')]]"))
        #)
        
        # Store the current window handle
        original_window = driver.current_window_handle
        
        # Get the href directly and navigate to it instead of clicking
        #download_url = quark_download_btn.get_attribute("href")
        download_url = get_download_links_with_curl(link_url)[0]
        print("下载MP3链接" + download_url)

        driver.execute_script(f"window.open('{download_url}', '_blank');")
        
        # Wait for the new window or tab
        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        
        # Switch to the new tab (Quark pan page)
        for window_handle in driver.window_handles:
            if window_handle != original_window:
                driver.switch_to.window(window_handle)
                break
        
        # Check if logged in properly (look for download button)
        try:
            # Using a more reliable wait and selector
            download_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.share-download"))
            )
            
            print("Found download button, clicking...")
            # Use JavaScript click for more reliability
            driver.execute_script("arguments[0].click();", download_btn)
            
            # Wait for download to start
            print(f"Downloading '{song_name}'...")
            time.sleep(5)
            
            # Close current tab and switch back to original
            driver.close()
            driver.switch_to.window(original_window)
            
            print(f"Song '{song_name}' has been queued for download")
            return True
            
        except Exception as e:
            print(f"Error finding download button. Login may have expired: {e}")
            # Take a screenshot for debugging
            driver.save_screenshot("error_screenshot.png")
            print("Screenshot saved as 'error_screenshot.png'")
            driver.close()
            driver.switch_to.window(original_window)
            return False
            
    except Exception as e:
        print(f"Error occurred while downloading '{song_name}': {e}")
        return False

def read_song_list_from_file(filename):
    """Read a list of songs from a text file, one song name per line"""
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            # Strip whitespace and filter out empty lines
            songs = [line.strip() for line in file.readlines() if line.strip()]
        return songs
    except Exception as e:
        print(f"Error reading song list file: {e}")
        return []

def batch_download_from_file(driver, filename):
    """Download multiple songs from a file list"""
    songs = read_song_list_from_file(filename)
    
    if not songs:
        print(f"No songs found in file '{filename}' or file could not be read.")
        return
    
    print(f"Found {len(songs)} songs in the list. Starting batch download...")
    
    successful = 0
    failed = []
    
    for index, song_name in enumerate(songs, 1):
        print(f"\n[{index}/{len(songs)}] Processing: {song_name}")
        
        success = download_song(driver, song_name)
        
        if success:
            successful += 1
        else:
            failed.append(song_name)
            
            # Check if we need to re-login
            if index < len(songs):  # Don't ask at the end of the list
                retry = "n" #input("Do you need to log in again? (y/n): ")
                if retry.lower() == 'y':
                    print("Please log in to Quark manually...")
                    driver.get("https://pan.quark.cn/")
                    input("Press Enter once you've successfully logged in...")
                    
                    # Save new cookies
                    pickle.dump(driver.get_cookies(), open("quark_cookies.pkl", "wb"))
                    print("Login session updated!")
    
    # Print summary
    print("\n===== DOWNLOAD SUMMARY =====")
    print(f"Total songs: {len(songs)}")
    print(f"Successfully downloaded: {successful}")
    print(f"Failed: {len(failed)}")
    
    if failed:
        print("\nFailed songs:")
        for song in failed:
            print(f"- {song}")
        
        # Option to save failed songs to retry later
        save_failed = input("\nDo you want to save the failed songs to a file for later retry? (y/n): ")
        if save_failed.lower() == 'y':
            failed_file = f"failed_songs_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            try:
                with open(failed_file, 'w', encoding='utf-8') as file:
                    for song in failed:
                        file.write(f"{song}\n")
                print(f"Failed songs saved to '{failed_file}'")
            except Exception as e:
                print(f"Error saving failed songs: {e}")

def main():
    download_folder = input("Enter download folder path (default is 'downloads'): ") or "downloads"
    
    # Initialize browser with session handling
    driver = initialize_browser(download_folder)
    
    try:
        while True:
            print("\n===== DOWNLOAD MODE =====")
            print("1. Single song download")
            print("2. Batch download from file")
            print("3. Exit")
            
            choice = input("Enter your choice (1-3): ")
            
            if choice == '1':
                # Single song download mode
                while True:
                    song_name = input("\nEnter the name of the song to download (or 'back' to return to menu): ")
                    if song_name.lower() == 'back':
                        break
                        
                    success = download_song(driver, song_name)
                    
                    if not success:
                        print("There was a problem downloading this song.")
                        
                        # Check if we need to re-login
                        retry = input("Do you need to log in again? (y/n): ")
                        if retry.lower() == 'y':
                            print("Please log in to Quark manually...")
                            driver.get("https://pan.quark.cn/")
                            input("Press Enter once you've successfully logged in...")
                            
                            # Save new cookies
                            pickle.dump(driver.get_cookies(), open("quark_cookies.pkl", "wb"))
                            print("Login session updated!")
                            
            elif choice == '2':
                # Batch download mode
                file_path = input("\nEnter the path to the file containing song names (one per line): ")
                if os.path.exists(file_path):
                    batch_download_from_file(driver, file_path)
                else:
                    print(f"File not found: {file_path}")
                    
            elif choice == '3':
                # Exit
                break
                
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")
    finally:
        # Don't close the driver automatically - ask user
        close = input("\nDo you want to close the browser? (y/n): ")
        if close.lower() == 'y':
            driver.quit()
            print("Browser closed.")
        else:
            print("Browser left open. You can close it manually when done.")

if __name__ == "__main__":
    main()
