# selenium-mp3-download

熊猫无损音乐网 (xmwsyy.com) 音乐下载器,支持命令行批量下载,以及作为 MCP server 接入 Claude Desktop 用自然语言操控。

下载链接走夸克网盘 (主) / 139.com (备),首次使用需要在弹出的浏览器里手动登录夸克并保存 cookie。

## 环境

```bash
pip install selenium mcp
```

需本机已装 Chrome + chromedriver。

## 命令行用法 (download_v8.py)

```bash
python ./download_v8.py
```

交互菜单:
1. **单曲下载** — 输入歌名搜索并下载
2. **批量下载** — 从文本文件读歌名 (每行一首),例如 `new_dj.txt`
3. **退出**

首次运行会弹出 Chrome,手动登录夸克网盘后回车,cookie 保存在 `quark_cookies.pkl`,后续复用。

下载产物默认进 `downloads/`,可在启动时改路径。

## MCP server 用法 (xmwsyy_mcp.py)

把整套下载能力封装成 MCP 工具,供 Claude Desktop / 其它 MCP 客户端调用。可以直接用自然语言: "搜一下泰勒斯威夫特 Father Figure 然后下载", "给我排行榜前 20", "把 new_dj.txt 里这批歌全下了"。

### Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "xmwsyy-music": {
      "command": "/opt/anaconda3/bin/python",
      "args": ["/Users/xlisp/PyPro/selenium-mp3-download/xmwsyy_mcp.py"]
    }
  }
}
```

python 路径按你的环境改。重启 Claude Desktop 即可。

### 工具清单

**查询类 (纯 curl,快,无浏览器开销):**

| 工具 | 说明 |
| --- | --- |
| `search_songs(keyword, limit)` | 关键词搜索歌曲 |
| `list_recent_songs(limit)` | 最近更新歌曲 (`/recentlysong/`) |
| `list_top_songs(limit)` | 热门排行榜 (`/trendsong/wk.html`) |
| `list_category_songs(category, limit)` | 按分类浏览 |
| `recommend_songs(limit)` | 首页推荐 (混合最新+热门) |
| `get_song_download_url(name_or_url)` | 只解析真实网盘链接,不下载 |

可用 `category`: `douyin`(抖音) / `neidi`(内地) / `gangtai`(港台) / `rihan`(日韩) / `oumei`(欧美) / `chezaidj`(车载DJ) / `chunyinyue`(纯音乐)

**下载类 (selenium,首次会弹浏览器登录夸克):**

| 工具 | 说明 |
| --- | --- |
| `download_song(song_name)` | 按歌名下载单曲 |
| `download_song_by_url(detail_url)` | 直接给详情页 URL 下载 |
| `batch_download(song_names)` | 列表批量下载 |
| `batch_download_from_file(file_path)` | 从文件批量下载 |
| `close_browser()` | 关闭浏览器实例 |

**目录管理:**

| 工具 | 说明 |
| --- | --- |
| `set_download_folder(path)` | 设置下载目录 |
| `get_download_folder()` | 查询当前目录 |
| `list_downloaded_files(limit)` | 列出已下载文件 |

### 设计要点

- **浏览器单例 + 懒加载**: 首次调用下载工具时才启动 Chrome,后续复用,夸克登录态不丢。
- **stdout 重定向**: 复用的 `download_v8` 函数会 `print()`,在 MCP stdio 模式下会破坏协议,统一用 `contextlib.redirect_stdout` 隔离。
- **查询走 curl,下载走 selenium**: 浏览器只在必须点"下载"按钮触发夸克网盘时使用,搜索/榜单这些纯页面抓取不开浏览器。

## 站点结构 (2026-04 校准)

xmwsyy.com 的关键 URL,做参考:

- 首页 (含搜索框): `https://www.xmwsyy.com/`
- 搜索: POST `/index/search/` form `action=1&keyword=...` (GET 会跳 404)
- 歌曲详情: `/song/<slug>.html`
- 下载中转: `/dls/<code>.html` → JS 跳转到真实网盘
  - `rmk*` → 夸克 MP3
  - `rwk*` → 夸克 WAV
  - `rym*` → 139.com MP3 (不限速)
  - `ryw*` → 139.com WAV (不限速)
- 最近更新: `/recentlysong/index.html`
- 排行榜: `/trendsong/wk.html`
- 分类: `/music/{douyin,neidi,gangtai,rihan,oumei,chezaidj,chunyinyue}.html`

## 文件

- `download_v8.py` — 命令行批量下载脚本,包含核心 selenium / 链接解析逻辑
- `xmwsyy_mcp.py` — MCP server,封装上面所有能力
- `quark_cookies.pkl` — 夸克网盘登录 cookie (首次登录后自动生成)
- `new_dj.txt` — 批量下载歌单示例
- `downloads/` — 默认下载目录
- `remove_dict_song.py` / `remove_repeat_file.py` — 整理已下载文件的辅助脚本

## 英文歌补充资源

`www.hydr0.org` 模板示例:

```
https://juicy-j-feat-kevin-gates-future-and-sage-the-gemini-payback.hydr0.org/
```
