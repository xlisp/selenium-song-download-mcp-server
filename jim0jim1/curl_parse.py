import subprocess
import re

# 要执行的命令
cmd = 'curl https://www.xmwsyy.com/mscdetail/133187.html | grep download | grep mp3音乐'

# 执行命令并获取输出
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

# 提取 href 中的链接
matches = re.findall(r'href="(https://[^"]+)"', result.stdout)

# 打印提取到的链接
for url in matches:
    print(url)

