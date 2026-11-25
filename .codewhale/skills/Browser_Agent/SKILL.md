# Browser_Agent

FAM 驱动电脑上可见 Chrome 办事：比价、看地图、找图、任意网站。只查不买。设计：[spec](../../../docs/superpowers/specs/2026-11-25-browser-agent-design.md)。

## 用

```bash
pip install playwright        # 不需 playwright install：用本机 Chrome
python .codewhale/skills/Browser_Agent/cli.py browser-login --member <名字>   # 每成员一次，手动登录各网站后关窗
```

旋钮：`config.json` `browser`（键义见其 `_comment`）。改代码后 `/build` + `/run-daemon` 才生效。

## 实测（Chrome 156，playwright 1.65.2，2026-11-25）

- VPN 注入 DLL 不影响 Playwright 驱动（uv 会崩，这个不会）。
- 起 Chrome 到端口应答 0.05–0.5 s；`connect_over_cdp` 0.2–0.3 s；视口截图 0.13–0.18 s。
- `navigator.webdriver` = false（普通进程启动 + 挂端口，无自动化旗标）。
- 端到端（deepseek-flash，未登录 profile）：

| 任务 | 用时 | 模型调用 | tokens 入/出 |
|---|---|---|---|
| 打开 example.com，截图，报标题 | 8.5 s | 4 | 7.3k / 0.3k |
| Bing 图片找螳螂存原图 | 36.5 s | 12 | 58k / 1.2k |
| Amazon 搜商品，点 Buy Now | 29 s | 8 | 44k / 1.0k |

- Amazon 中文界面按钮是「现在购买」，最初的拦截表没有：真页面验证过才补上。新平台上线前先看其按钮原文。

## 坑

- 窗口最小化：`page.screenshot` 卡到超时；页级 CDP `Page.captureScreenshot` 会把 Playwright 连接搞断。驱动截图前先 `Browser.setWindowBounds` 恢复 normal。最小化时导航照常。
- 同步 API 只在 Playwright 调用期间派发事件：`time.sleep` 期间新标签、弹窗都看不到。驱动内等待一律 `page.wait_for_timeout`。
- 同步 API 对象绑定创建线程：驱动只在任务线程里建、用。
- Chrome 136+ 默认 profile 不开调试端口：必须独立 `--user-data-dir`（每成员 `data/<成员>/browser_profile/`，不入备份）。
- `browser-login` 开的窗口就是 FAM 的 Chrome（带端口），不关也能直接接任务；空闲 `idle_close_min` 后自动关。
- 付款闸门按整句匹配按钮文字：漏网措辞可能有。成员 profile 里别存银行卡。
