from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os
import re

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

        # Step 3: 在歌曲详情页面获取所有包含download的a标签
        # 等待页面加载完成
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        print("=== 进入歌曲详情页面，开始查找包含download的a标签 ===")
        
        # 等待myarticle元素加载完成
        print("等待myarticle元素加载...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "myarticle"))
        )
        print("myarticle元素已加载")
        
        # 获取myarticle元素的HTML内容
        page_html = driver.execute_script("return document.getElementById('myarticle').innerHTML")
        print("=== myarticle HTML获取成功，开始正则匹配 ===")
        print(f"HTML内容长度: {len(page_html)} 字符")
        
        # 使用正则表达式匹配所有包含download的a标签
        # 匹配 <a ...> 标签，其中包含download关键字（不区分大小写）
        download_pattern = r'<a[^>]*(?:href[^>]*download|download[^>]*href|class[^>]*download|download[^>]*class|id[^>]*download|download[^>]*id)[^>]*>.*?</a>'
        matches = re.findall(download_pattern, page_html, re.IGNORECASE | re.DOTALL)
        
        print(f"=== 正则匹配到 {len(matches)} 个包含download的a标签 ===")
        for i, match in enumerate(matches):
            print(f"Match {i+1}: {match}")
        
        # 提取href属性
        href_pattern = r'href=["\']([^"\']*)["\']'
        download_urls = []
        
        for match in matches:
            href_matches = re.findall(href_pattern, match, re.IGNORECASE)
            if href_matches:
                download_urls.extend(href_matches)
        
        # 如果上面的正则没匹配到，尝试更宽泛的匹配
        if not download_urls:
            print("=== 尝试更宽泛的正则匹配 ===")
            # 匹配所有a标签，然后检查是否包含download
            all_a_pattern = r'<a[^>]*>.*?</a>'
            all_matches = re.findall(all_a_pattern, page_html, re.IGNORECASE | re.DOTALL)
            
            print(f"找到 {len(all_matches)} 个a标签")
            for i, match in enumerate(all_matches):
                if 'download' in match.lower():
                    print(f"包含download的a标签 {i+1}: {match}")
                    href_matches = re.findall(href_pattern, match, re.IGNORECASE)
                    if href_matches:
                        download_urls.extend(href_matches)
        
        # 去重
        download_urls = list(set(download_urls))
        
        print(f"\n=== 提取到的URL列表 ===")
        for i, url in enumerate(download_urls):
            print(f"URL {i+1}: {url}")
        
        # 检查是否有足够的链接
        if len(download_urls) < 2:
            print(f"警告：只找到 {len(download_urls)} 个download链接，需要至少2个")
            if len(download_urls) == 0:
                # 如果还是没找到，打印部分HTML用于调试
                print("=== 调试信息：myarticle HTML片段 ===")
                print(page_html[:2000] + "..." if len(page_html) > 2000 else page_html)
                raise Exception("没有找到包含download的链接")
            # 如果只有一个链接，使用第一个
            selected_url = download_urls[0]
            print(f"使用第一个链接: {selected_url}")
        else:
            # 使用第二个URL链接
            selected_url = download_urls[1]
            print(f"使用第二个链接: {selected_url}")
        
        # 通过JavaScript直接跳转到选中的URL
        if selected_url.startswith('http'):
            print(f"直接跳转到: {selected_url}")
            driver.get(selected_url)
        else:
            # 相对链接，需要拼接完整URL
            current_url = driver.current_url
            base_url = current_url.split('?')[0].rsplit('/', 1)[0] + '/'
            full_url = base_url + selected_url.lstrip('/')
            print(f"拼接完整URL: {full_url}")
            driver.get(full_url)

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

