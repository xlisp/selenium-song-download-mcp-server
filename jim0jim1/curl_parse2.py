import subprocess
import re

def get_download_links_with_curl(detail_url):
    """
    使用curl从详情页获取下载链接
    """
    try:
        # 使用curl获取详情页内容并提取下载链接
        cmd = f'curl -s "{detail_url}" | grep download | grep mp3'
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        # 提取href中的链接
        matches = re.findall(r'href="(https://[^"]+)"', result.stdout)
        
        return matches
        
    except Exception as e:
        print(f"获取下载链接时出错: {e}")
        return []

print(get_download_links_with_curl("https://www.xmwsyy.com/mscdetail/133187.html"))

