from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os

def download_mp3(song_name, download_folder="downloads"):
    """
    Downloads an MP3 from xmwsyy.com based on the song name.

    Args:
        song_name: The name of the song to search for
        download_folder: Folder to save the downloaded MP3
    """
    # Create download directory if it doesn't exist
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    # Setup Chrome options
    chrome_options = Options()
    prefs = {"download.default_directory": os.path.abspath(download_folder)}
    chrome_options.add_experimental_option("prefs", prefs)

    # Initialize the Chrome driver
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Step 1: Go to search page and input song name
        driver.get("https://www.xmwsyy.com/index/search/")

        # Wait for search input to load and enter song name
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "edtSearch"))
        )
        search_input.clear()
        search_input.send_keys(song_name)
        search_input.send_keys(Keys.RETURN)

        # Step 2: Wait for search results and click the first result
        # 修正：根据新的HTML结构，<a>标签包含<li>，而不是<li>包含<a>
        result_link = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul > a[href*='/mscdetail/']"))
        )

        link_url = result_link.get_attribute("href")
        print(f"Found song link: {link_url}")
        result_link.click()

        # Step 3: On the detail page, find and click the "夸克MP3链接下载" button using the exact HTML structure
        # Using the more precise CSS selector based on the HTML you provided
        quark_download_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href^='/download/'] h2.title[style*='background:#f7de0e']"))
        )

        # Click on the parent <a> element, not the h2
        parent_link = quark_download_btn.find_element(By.XPATH, "./..")
        parent_link.click()

        # Switch to the new tab (Quark pan page)
        # Wait a moment for the new tab to open
        time.sleep(2)
        driver.switch_to.window(driver.window_handles[-1])

        # Step 4: On the Quark pan page, find and click the download button
        download_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'download') or contains(text(), '下载')]"))
        )

        download_btn.click()

        # Wait for download to complete (this is a simple wait, could be improved)
        print("Waiting for download to complete...")
        time.sleep(10)

        print(f"Song '{song_name}' has been downloaded to {download_folder}")

    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        # Close the browser
        driver.quit()

if __name__ == "__main__":
    song_name = input("Enter the name of the song to download: ")
    download_mp3(song_name)
