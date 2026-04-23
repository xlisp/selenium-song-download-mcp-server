"""
熊猫无损音乐网 (xmwsyy.com) MCP server.

复用 download_v8.py 的下载逻辑,封装为 MCP 工具供 Claude Desktop 调用。
- 搜索/榜单/分类/最新 等查询: 纯 curl + 正则,无浏览器开销
- 单曲/批量 下载: 通过 CDP (remote-debugging-port) 附着到一个独立启动的
  Chrome 实例。Chrome 由 macOS `open -na` 启动,脱离 Claude Desktop 的
  进程树/沙箱,所以不会被只读文件系统拦住,也不会因 MCP 重启而丢失登录态。
  user-data-dir 在项目目录里,登录态自动保留,不再需要 pickle cookies。
"""
import io
import os
import pickle
import re
import socket
import sys
import subprocess
import threading
import time
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from mcp.server.fastmcp import FastMCP

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# Claude Desktop 启动 MCP 时 cwd 可能是只读的 `/`,切到项目目录以防 download_v8
# 里的相对路径 (quark_cookies.pkl, error_screenshot.png) 写失败。
try:
    os.chdir(PROJECT_DIR)
except Exception:
    pass

# 把 stderr 同时写到文件,Claude Desktop 的日志只收实时 stderr,但 Chrome 启动
# 过程可能已在我们能写日志之前就把进程弄崩。落盘方便排错。
_log_file_path = PROJECT_DIR / "mcp_stderr.log"
try:
    _log_fp = open(_log_file_path, "a", buffering=1)
    _log_fp.write(f"\n--- MCP start @ {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} ---\n")
except Exception:
    _log_fp = None


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass
    if _log_fp is not None:
        try:
            _log_fp.write(line)
        except Exception:
            pass


import download_v8

mcp = FastMCP("xmwsyy-music")

BASE_URL = "https://www.xmwsyy.com"
CATEGORIES = {
    "douyin":     "/music/douyin.html",      # 抖音
    "neidi":      "/music/neidi.html",       # 内地
    "gangtai":    "/music/gangtai.html",     # 港台
    "rihan":      "/music/rihan.html",       # 日韩
    "oumei":      "/music/oumei.html",       # 欧美
    "chezaidj":   "/music/chezaidj.html",    # 车载DJ
    "chunyinyue": "/music/chunyinyue.html",  # 纯音乐
}
RECENT_PATH = "/recentlysong/index.html"
TREND_PATH = "/trendsong/wk.html"

_driver = None
_driver_lock = threading.Lock()
_driver_ready = threading.Event()
_driver_init_error: Optional[str] = None
_download_folder = str(PROJECT_DIR / "downloads")
_cookies_file = str(PROJECT_DIR / "quark_cookies.pkl")

CHROME_DEBUG_PORT = 9222
CHROME_USER_DATA_DIR = str(PROJECT_DIR / "chrome-profile")
CHROME_APP = "Google Chrome"


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def _wait_for_port(port: int, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open("127.0.0.1", port):
            return True
        time.sleep(0.5)
    return False


def _launch_detached_chrome():
    """Launch Chrome as an independent macOS app via `open -na`.

    Using `open` hands the process off to launchd, so Chrome is NOT a child
    of this MCP process and inherits no sandbox/cwd restrictions from
    Claude Desktop. A dedicated user-data-dir keeps cookies/session
    persistent across MCP restarts.
    """
    os.makedirs(CHROME_USER_DATA_DIR, exist_ok=True)
    os.makedirs(_download_folder, exist_ok=True)
    args = [
        "open", "-na", CHROME_APP, "--args",
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={CHROME_USER_DATA_DIR}",
        "--window-size=1920,1080",
        # 不走代理
        "--no-proxy-server",
        "--proxy-server=direct://",
        "--proxy-bypass-list=*",
        "https://pan.quark.cn/",
    ]
    _log(f"launching detached chrome: {' '.join(args)}")
    subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _connect_to_chrome():
    """Attach Selenium to the already-running Chrome via CDP."""
    chrome_options = Options()
    chrome_options.add_experimental_option(
        "debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}"
    )
    prefs = {"download.default_directory": os.path.abspath(_download_folder)}
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)


def _background_init():
    """Runs once at module load in a daemon thread."""
    global _driver, _driver_init_error
    try:
        if not _port_open("127.0.0.1", CHROME_DEBUG_PORT):
            _launch_detached_chrome()
            if not _wait_for_port(CHROME_DEBUG_PORT, timeout=45):
                _driver_init_error = (
                    f"Chrome 调试端口 {CHROME_DEBUG_PORT} 在 45s 内未就绪。"
                    f"请检查 Chrome 是否安装在 /Applications/Google Chrome.app,"
                    f"或手动执行: open -na 'Google Chrome' --args "
                    f"--remote-debugging-port={CHROME_DEBUG_PORT} "
                    f"--user-data-dir={CHROME_USER_DATA_DIR}"
                )
                _log(_driver_init_error)
                return
        else:
            _log(f"port {CHROME_DEBUG_PORT} already open, reusing existing Chrome")

        driver = _connect_to_chrome()
        with _driver_lock:
            _driver = driver
        _log("selenium attached to chrome successfully")
        # 首次启动时 Chrome 可能停在 chrome://intro/, 导航到夸克网盘方便用户登录
        try:
            cur = driver.current_url or ""
            if not cur.startswith("https://pan.quark.cn"):
                driver.get("https://pan.quark.cn/")
                _log("navigated to pan.quark.cn")
        except Exception as e:
            _log(f"navigate to quark failed (non-fatal): {e}")
    except Exception as e:
        _driver_init_error = f"{type(e).__name__}: {e}"
        _log(f"background init failed: {_driver_init_error}")
    finally:
        _driver_ready.set()


def _curl_get(url: str, timeout: int = 15) -> str:
    """GET a URL via curl, return body text. Raises on failure."""
    result = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _curl_post(url: str, data: str, timeout: int = 15) -> str:
    """POST form data to URL via curl, return body text."""
    result = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "-X", "POST", "--data", data, url],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


_SONG_RE = re.compile(
    r'<a\s+href="(/song/[^"]+\.html)"[^>]*title="([^"]+)"',
    re.IGNORECASE,
)


def _parse_song_list(html: str, limit: int) -> List[dict]:
    """Extract de-duplicated song entries from any list/category/search page."""
    seen = set()
    out = []
    for href, title in _SONG_RE.findall(html):
        if href in seen:
            continue
        seen.add(href)
        out.append({"title": title.strip(), "url": urljoin(BASE_URL, href)})
        if len(out) >= limit:
            break
    return out


def _format_song_list(songs: List[dict], header: str) -> str:
    if not songs:
        return f"{header}\n(无结果)"
    lines = [header, "-" * 60]
    for i, s in enumerate(songs, 1):
        lines.append(f"{i:>3}. {s['title']}")
        lines.append(f"     {s['url']}")
    return "\n".join(lines)


def _get_driver(wait_timeout: int = 90):
    """Return the selenium driver, waiting for background init if needed.

    If init failed, retries inline: re-launches Chrome (if port closed) and
    re-attaches. Never calls input().
    """
    global _driver, _driver_init_error
    if not _driver_ready.wait(timeout=wait_timeout):
        raise RuntimeError(
            f"浏览器初始化超时 (>{wait_timeout}s)。"
            f"如果你在第一次使用,请确认 /Applications/Google Chrome.app 存在,"
            f"也可以查看日志: {_log_file_path}"
        )
    with _driver_lock:
        if _driver is not None:
            return _driver
        # 后台初始化失败,重试
        if not _port_open("127.0.0.1", CHROME_DEBUG_PORT):
            _launch_detached_chrome()
            if not _wait_for_port(CHROME_DEBUG_PORT, timeout=30):
                raise RuntimeError(
                    f"Chrome 调试端口 {CHROME_DEBUG_PORT} 未就绪。先前错误: {_driver_init_error}"
                )
        _driver = _connect_to_chrome()
        _driver_init_error = None
        return _driver


def _run_capturing(fn, *args, **kwargs):
    """Run a function while capturing stdout/stderr (download_v8 prints a lot)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


# ---------- 查询类工具 (纯 curl) ----------

@mcp.tool()
async def search_songs(keyword: str, limit: int = 10) -> str:
    """在熊猫无损音乐网搜索歌曲,返回标题和详情页 URL 列表。

    Args:
        keyword: 歌曲名或歌手名
        limit: 返回结果数上限 (默认 10)
    """
    if not keyword.strip():
        return "Error: 关键词不能为空"
    try:
        html = _curl_post(f"{BASE_URL}/index/search/", f"action=1&keyword={keyword}")
    except Exception as e:
        return f"Error: 搜索请求失败: {e}"
    songs = _parse_song_list(html, limit)
    return _format_song_list(songs, f"搜索 '{keyword}' 的结果 (前 {limit} 条):")


@mcp.tool()
async def list_recent_songs(limit: int = 20) -> str:
    """获取最近更新的歌曲列表。

    Args:
        limit: 返回数量上限 (默认 20)
    """
    try:
        html = _curl_get(BASE_URL + RECENT_PATH)
    except Exception as e:
        return f"Error: 请求失败: {e}"
    songs = _parse_song_list(html, limit)
    return _format_song_list(songs, f"最近更新歌曲 (前 {limit} 条):")


@mcp.tool()
async def list_top_songs(limit: int = 20) -> str:
    """获取热门排行榜歌曲。

    Args:
        limit: 返回数量上限 (默认 20)
    """
    try:
        html = _curl_get(BASE_URL + TREND_PATH)
    except Exception as e:
        return f"Error: 请求失败: {e}"
    songs = _parse_song_list(html, limit)
    return _format_song_list(songs, f"热门排行榜 (前 {limit} 条):")


@mcp.tool()
async def list_category_songs(category: str, limit: int = 20) -> str:
    """按分类浏览歌曲。

    Args:
        category: 分类标识。可选: douyin(抖音)/neidi(内地)/gangtai(港台)/rihan(日韩)/oumei(欧美)/chezaidj(车载DJ)/chunyinyue(纯音乐)
        limit: 返回数量上限 (默认 20)
    """
    path = CATEGORIES.get(category.lower())
    if not path:
        return f"Error: 未知分类 '{category}'。可选: {', '.join(CATEGORIES.keys())}"
    try:
        html = _curl_get(BASE_URL + path)
    except Exception as e:
        return f"Error: 请求失败: {e}"
    songs = _parse_song_list(html, limit)
    return _format_song_list(songs, f"分类 [{category}] 的歌曲 (前 {limit} 条):")


@mcp.tool()
async def recommend_songs(limit: int = 15) -> str:
    """从首页抓取推荐歌曲 (混合最新+热门+排行)。

    Args:
        limit: 返回数量上限 (默认 15)
    """
    try:
        html = _curl_get(BASE_URL + "/")
    except Exception as e:
        return f"Error: 请求失败: {e}"
    songs = _parse_song_list(html, limit)
    return _format_song_list(songs, f"首页推荐歌曲 (前 {limit} 条):")


@mcp.tool()
async def get_song_download_url(song_url_or_keyword: str) -> str:
    """解析一首歌的真实网盘下载链接 (夸克 MP3 优先) 而不实际下载。

    Args:
        song_url_or_keyword: 歌曲详情页 URL (https://www.xmwsyy.com/song/xxx.html) 或歌曲名
    """
    detail_url = song_url_or_keyword.strip()
    if not detail_url.startswith("http"):
        try:
            html = _curl_post(f"{BASE_URL}/index/search/", f"action=1&keyword={detail_url}")
        except Exception as e:
            return f"Error: 搜索失败: {e}"
        songs = _parse_song_list(html, 1)
        if not songs:
            return f"Error: 没找到与 '{song_url_or_keyword}' 匹配的歌曲"
        detail_url = songs[0]["url"]
    links = download_v8.get_download_links_with_curl(detail_url)
    if not links:
        return f"Error: 无法从 {detail_url} 提取下载链接"
    return f"详情页: {detail_url}\n下载链接: {links[0]}"


# ---------- 下载类工具 (selenium) ----------

@mcp.tool()
async def set_download_folder(folder_path: str) -> str:
    """设置下载保存目录。会在下次浏览器初始化时生效。

    Args:
        folder_path: 绝对或相对路径
    """
    global _download_folder, _driver
    abs_path = str(Path(folder_path).expanduser().resolve())
    Path(abs_path).mkdir(parents=True, exist_ok=True)
    _download_folder = abs_path
    note = ""
    if _driver is not None:
        note = "\n注意: 浏览器已启动,新设置仅影响下次启动。需立即生效请先调用 close_browser。"
    return f"下载目录已设为: {abs_path}{note}"


@mcp.tool()
async def get_download_folder() -> str:
    """查询当前下载目录及其中已有文件数量。"""
    p = Path(_download_folder)
    n = sum(1 for _ in p.glob("*")) if p.exists() else 0
    return f"下载目录: {_download_folder}\n已有文件数: {n}"


@mcp.tool()
async def list_downloaded_files(limit: int = 50) -> str:
    """列出当前下载目录中的文件 (按修改时间倒序)。

    Args:
        limit: 返回数量上限 (默认 50)
    """
    p = Path(_download_folder)
    if not p.exists():
        return f"下载目录不存在: {_download_folder}"
    files = sorted(
        (f for f in p.iterdir() if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]
    if not files:
        return f"下载目录为空: {_download_folder}"
    lines = [f"下载目录: {_download_folder}", "-" * 60]
    for f in files:
        lines.append(f"{f.stat().st_size:>12,} bytes  {f.name}")
    return "\n".join(lines)


@mcp.tool()
async def download_song(song_name: str) -> str:
    """按歌名下载单首歌曲 (会调用浏览器,需要夸克网盘已登录)。

    Args:
        song_name: 歌曲名或 '歌曲名-歌手' 形式
    """
    try:
        driver = _get_driver()
    except Exception as e:
        return f"Error: 浏览器初始化失败: {e}"
    success, log = _run_capturing(download_v8.download_song, driver, song_name)
    status = "成功" if success else "失败"
    return f"[{status}] 下载 '{song_name}'\n--- 日志 ---\n{log.strip()}"


@mcp.tool()
async def download_song_by_url(detail_url: str) -> str:
    """通过歌曲详情页 URL 直接下载 (跳过搜索步骤)。

    Args:
        detail_url: 形如 https://www.xmwsyy.com/song/xxx.html
    """
    if not detail_url.startswith("http"):
        return "Error: 必须是完整 URL"
    try:
        driver = _get_driver()
    except Exception as e:
        return f"Error: 浏览器初始化失败: {e}"
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By

            driver.get(detail_url)
            original = driver.current_window_handle
            links = download_v8.get_download_links_with_curl(detail_url)
            if not links:
                return f"Error: 未能从详情页提取下载链接\n日志:\n{buf.getvalue().strip()}"
            download_url = links[0]
            driver.execute_script(f"window.open('{download_url}', '_blank');")
            WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
            for handle in driver.window_handles:
                if handle != original:
                    driver.switch_to.window(handle)
                    break
            btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.share-download"))
            )
            driver.execute_script("arguments[0].click();", btn)
            import time
            time.sleep(5)
            driver.close()
            driver.switch_to.window(original)
    except Exception as e:
        return f"Error: 下载失败: {e}\n日志:\n{buf.getvalue().strip()}"
    return f"[成功] 下载已触发: {detail_url}\n日志:\n{buf.getvalue().strip()}"


@mcp.tool()
async def batch_download(song_names: List[str]) -> str:
    """批量下载一组歌曲。

    Args:
        song_names: 歌曲名列表
    """
    if not song_names:
        return "Error: 列表为空"
    try:
        driver = _get_driver()
    except Exception as e:
        return f"Error: 浏览器初始化失败: {e}"
    successes, failures = [], []
    log_lines = []
    for i, name in enumerate(song_names, 1):
        log_lines.append(f"[{i}/{len(song_names)}] {name}")
        ok, log = _run_capturing(download_v8.download_song, driver, name)
        log_lines.append("  " + ("成功" if ok else "失败"))
        (successes if ok else failures).append(name)
    summary = (
        f"批量下载完成: 共 {len(song_names)} 首,成功 {len(successes)},失败 {len(failures)}\n"
        f"成功: {successes}\n失败: {failures}\n"
        f"--- 详细 ---\n" + "\n".join(log_lines)
    )
    return summary


@mcp.tool()
async def batch_download_from_file(file_path: str) -> str:
    """从文本文件批量下载 (每行一首歌名)。

    Args:
        file_path: 包含歌名的文本文件路径
    """
    p = Path(file_path).expanduser()
    if not p.exists():
        return f"Error: 文件不存在: {file_path}"
    songs = download_v8.read_song_list_from_file(str(p))
    if not songs:
        return f"Error: 文件中没有可读的歌名: {file_path}"
    return await batch_download(songs)


@mcp.tool()
async def close_browser() -> str:
    """断开 selenium 与 Chrome 的连接 (不会关闭 Chrome 窗口本身,登录态保留)。"""
    global _driver
    with _driver_lock:
        if _driver is None:
            return "selenium 未连接到 Chrome"
        try:
            _driver.quit()
        except Exception as e:
            _driver = None
            return f"断开时异常: {e}"
        _driver = None
        _driver_ready.clear()
        return "selenium 已断开 (Chrome 窗口仍在运行,可再次调用其它工具触发重连)"


@mcp.tool()
async def browser_status() -> str:
    """查询 Chrome / selenium 当前状态。首次使用前确认已在 Chrome 里登录夸克。"""
    port_up = _port_open("127.0.0.1", CHROME_DEBUG_PORT)
    ready = _driver_ready.is_set()
    lines = [
        f"Chrome 调试端口 ({CHROME_DEBUG_PORT}): {'已开放' if port_up else '未开放'}",
        f"后台初始化: {'已完成' if ready else '进行中'}",
    ]
    if _driver_init_error:
        lines.append(f"初始化错误: {_driver_init_error}")
    with _driver_lock:
        if _driver is None:
            lines.append("Selenium 未附着")
        else:
            try:
                lines.append(f"当前页: {_driver.title}")
                lines.append(f"URL: {_driver.current_url}")
            except Exception as e:
                lines.append(f"Selenium 连接已失效: {e}")
    lines.append(f"用户数据目录: {CHROME_USER_DATA_DIR}")
    lines.append(f"日志文件: {_log_file_path}")
    return "\n".join(lines)


@mcp.tool()
async def relaunch_chrome() -> str:
    """如果 Chrome 没起来,手动触发一次启动 (独立进程,脱离 MCP 沙箱)。"""
    global _driver, _driver_init_error
    if _port_open("127.0.0.1", CHROME_DEBUG_PORT):
        return f"Chrome 调试端口已开放,无需重启。调 browser_status 查看详情。"
    try:
        _launch_detached_chrome()
    except Exception as e:
        return f"启动 Chrome 失败: {e}"
    if not _wait_for_port(CHROME_DEBUG_PORT, timeout=30):
        return f"已发出启动命令,但 30s 内端口 {CHROME_DEBUG_PORT} 仍未就绪。请查看日志 {_log_file_path}"
    with _driver_lock:
        _driver = _connect_to_chrome()
        _driver_init_error = None
        _driver_ready.set()
    return f"Chrome 已启动并附着成功 (user-data-dir={CHROME_USER_DATA_DIR})"


@mcp.tool()
async def save_quark_cookies() -> str:
    """保存 Chrome 当前的 cookies 到 pkl 文件 (可选,user-data-dir 本身已持久化登录态)。"""
    if not _driver_ready.is_set():
        return "浏览器尚未就绪"
    with _driver_lock:
        if _driver is None:
            return "浏览器未启动"
        try:
            cookies = _driver.get_cookies()
            pickle.dump(cookies, open(_cookies_file, "wb"))
        except Exception as e:
            return f"保存 cookies 失败: {e}"
    return f"已保存 {len(cookies)} 条 cookies 到 {_cookies_file}"


# 启动时立刻在后台线程打开独立的 Chrome,不阻塞 MCP 主循环
threading.Thread(target=_background_init, name="browser-init", daemon=True).start()


if __name__ == "__main__":
    mcp.run(transport="stdio")
