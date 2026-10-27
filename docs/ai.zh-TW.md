# 讓 AI 接入 Inspector(MCP)

支援 [Model Context Protocol](https://modelcontextprotocol.io) 的 AI 工具(Claude Desktop、Claude Code 等)可以連到電腦上正在執行的 Inspector,
用一般的話跟它合作:讀設計和執行的情況、幫你改設計、照顧執行。你不用打開原始碼;AI 用的是跟網頁一樣的方式,也經過一樣的檢查。

## 依權限,AI 能做的事

| 權限 | AI 可以做的事 | 工具數 |
|---|---|---|
| `read`(只能看) | 看所有東西:專案、來源、狀態、腳本、排程、操作面板、使用者設定、輸出(秘密會遮住);每台現在看到和決定的事、時間軸、紀錄、緊急事件(含影片)、即時畫面、錄好的畫面、錄影、訓練、腳本測試、儲存空間。說明規則為什麼觸發或沒觸發、整理報告、只檢查不存、在錄影上試狀態規則、重播腳本、跑腳本測試。 | 23 |
| `design`(可以改設計,預設) | 再加上修改設計:主腳本、子腳本、狀態、排程、使用者設定、變數、輸出、操作面板。每次修改都要寫理由、是一個新版本、記在 AI 活動紀錄,而且可以退回。 | 35 |
| `run`(可以控制執行) | 再加上開始 / 停止腳本執行、讓裝置停下來 / 暫停 / 繼續、把腳本部署成關閉或試跑、改執行設定和使用者設定的值,以及請人同意正式執行。 | 42 |

### 不管什麼權限,AI 都不會做的事

- **讓任何東西正式執行。** AI 存的主腳本,在原本不是正式執行的裝置上只會試跑。它只能**提出要求**(`request_live`):
  要求會出現在「執行」頁和首頁,也會發通知,由人按「同意」或「拒絕」;AI 不能自己同意。
- 立刻執行排程或子腳本、刪除錄影或模型、搬移資料、重新啟動 Inspector。
- 看到秘密:密碼、權杖、PIN、Webhook 網址、HTTP 標頭一律遮住;AI 存輸出時,被遮住或沒填的秘密會保留原本的值。
- 每分鐘超過 30 次修改。

## 怎麼連

「AI 接入」頁(這台電腦 › AI 接入)會幫你產生下面所有的設定。

### 在同一台電腦上(建議)

AI 工具會自己啟動 `python -m mcp_server`(stdio),不需要權杖。

```bash
cd <Inspector 資料夾>
claude mcp add inspector -- python -m mcp_server --level design
```

Claude Desktop:寫進 `claude_desktop_config.json`,再重新開啟 Claude:

```json
{"mcpServers": {"inspector": {"command": "python", "args": ["-m", "mcp_server", "--level", "design"], "cwd": "<Inspector 資料夾>"}}}
```

選項:`--url`(正在執行的 Inspector,預設 `http://127.0.0.1:8765`)、`--level read|design|run`、`--lang`(Inspector 回答用的語言)、
`--name`(AI 活動紀錄上怎麼稱呼這個工具)。

### 從別台電腦

在「AI 接入」頁建立**權杖**(名稱 + 權限;只顯示一次、只存雜湊、可以撤銷),AI 工具帶著它連到 Inspector 自己的 `/mcp` 位址:

```bash
claude mcp add --transport http inspector http://<Inspector 那台電腦>:8765/mcp --header "Authorization: Bearer <權杖>"
```

Inspector 預設只接受自己這台電腦的連線,要用 `--lan` 啟動別台才連得到。同一個網路裡權杖不會加密;要從外面連,請透過 Tailscale、VPN 等加密的通道。
沒有權杖一律連不上。

## 工作範本(prompts)

在 AI 工具裡選用(Claude Desktop:+ 選單;Claude Code:`/mcp__inspector__<名稱>`):

| 範本 | 權限 | AI 會做的事 |
|---|---|---|
| `daily_report` | read | 這段時間發生了什麼、哪些需要你處理,簡短好懂 |
| `diagnose` | read | 某台為什麼做了(或沒做)某件事:狀態、畫面、每條規則的條件、時間軸,再提出可以先檢查的修正 |
| `build_solution` | design | 從「要看什麼、要做什麼」做到腳本開始試跑:在錄影上驗證過的狀態、動作、重播過的主腳本 |
| `check_before_live` | run | 先在錄影和腳本測試上驗證,再請你同意讓它正式執行 |

也可以直接問:「現在怎麼樣?」「昨晚打氣機為什麼沒開?」「白鷺鷥的規則改成持續 5 秒,讓我看看昨天會怎麼做。」

## 追蹤 AI 做了什麼

- **AI 活動紀錄**(「AI 接入」頁,或 `get_ai_log`):每一筆修改和動作的時間、哪個工具(權杖名稱)、理由、改之前的樣子。改設計的可以**退回**。
- **版本**:腳本、子腳本、狀態每一版都留著(`list_versions`、`restore_version`);AI 的版本說明以「AI:」開頭。
- **要求**:AI 請人決定的事,在「執行」頁和「AI 接入」頁。

## 常見問題

- *「Inspector is not reachable」*:Inspector 要開著(AI 是跟它說話);檢查 `--url` 和連接埠。
- */mcp 回 401*:沒帶權杖、權杖錯誤或已撤銷,到「AI 接入」頁建一把新的。
- *少了某個工具*:這個工具的權限等級不包含它(`--level`,或權杖的權限)。
- *說明規則 / 看即時畫面時說「腳本執行沒有在跑」*:到「執行」頁開始執行(或在 run 權限用 `start_runner`)。
- 執行版(只能執行的版本)不能改設計,AI 也一樣。
