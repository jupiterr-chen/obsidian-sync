# 知识库 API 使用说明

核对日期：2026-10-07。适用于当前生产应用 `9d1b04f`。本文按实际接口编写，配套设计见 [接口契约](04-api-contract.md)。

现在可以通过 API 搜索已入库资料、取得正文与原文证据、获取公司研究背景包。下面的读取操作不调用 LLM；已有 GLM 单次分析试用不等于生产自动分析服务已启用。当前也没有 Swagger `/docs` 页面或面向用户的网页搜索界面。

## 1. 地址与连接方式

|用途|地址|说明|
|---|---|---|
|服务器上的知识库 API|`http://127.0.0.1:8766/api/kb/v1`|只监听服务器本机；包含全文检索和证据接口|
|Windows 通过下方隧道访问|`http://127.0.0.1:18766/api/kb/v1`|隧道运行期间可用|
|已有资料/原文服务|`http://192.168.1.150:8765`|library 服务，与知识库 API 不是同一组路由|

在 Windows 的第一个 PowerShell 窗口执行，并保持窗口打开：

```powershell
ssh -N -L 127.0.0.1:18766:127.0.0.1:8766 -o ExitOnForwardFailure=yes chen@192.168.1.150
```

没有输出通常表示隧道已建立。在这个窗口按 Ctrl+C 只会关闭隧道，不会停止服务器服务或 OCR。

以下命令在**第二个 PowerShell 窗口**按顺序执行：

```powershell
$kbOrigin = 'http://127.0.0.1:18766'
$kbBase = "$kbOrigin/api/kb/v1"
Invoke-RestMethod "$kbBase/health"
Invoke-RestMethod "$kbBase/ready"
```

`health.status = ok` 表示进程存活；`ready.ready = true` 表示已有可查询索引。它们不代表所有历史 OCR 已完成，也不代表每份财报的数字已经人工核对。这两个探针无需令牌。

## 2. 准备只读令牌

业务请求使用 `Authorization: Bearer <token>`，需要 `research.read` 权限。不要把真实令牌放进 URL、Git 或截图。

本机项目所有者可通过既有 SSH 权限，将服务器**已有的纯只读令牌直接读入当前 PowerShell 内存**。下面不会把令牌显示到终端，也不会创建新令牌或改生产配置：

```powershell
$kbReadTokenScript = @'
import json
from pathlib import Path
p = Path('/vol2/1000/10.Develop/obsidian-sync/releases/9d1b04f/deploy/config/knowledge.json')
c = json.loads(p.read_text())
tokens = c.get('api_tokens') or c.get('extra', {}).get('api_tokens', {})
for token, scopes in tokens.items():
    if set(scopes) == {'research.read'}:
        print(token)
        break
else:
    raise SystemExit('No read-only token found')
'@
$kbTokenLines = $kbReadTokenScript | ssh -o BatchMode=yes chen@192.168.1.150 python3 -
if ($LASTEXITCODE -ne 0) { throw '读取只读令牌失败' }
$kbToken = ($kbTokenLines -join '').Trim()
if (-not $kbToken) { throw '只读令牌为空' }
$kbHeaders = @{ Authorization = "Bearer $kbToken" }
```

这是当前发布目录；后续发布或令牌轮换后，应使用当时有效的私有配置。外部应用应通过自己的密钥存储注入令牌，不应依赖这段 SSH 获取方式。请勿单独执行远端 Python 脚本或输出 `$kbToken` / `$kbHeaders`。

## 3. 立即搜索：腾讯的现金流

```powershell
$kbSearch = @{
    query = '現金流'
    mode = 'keyword'
    filters = @{
        symbols = @('00700')
        sources = @('reports')
        collections = @('source_documents')
    }
    limit = 5
}
$kbBody = $kbSearch | ConvertTo-Json -Depth 8
$kbResult = Invoke-RestMethod -Method Post -Uri "$kbBase/search" `
    -Headers $kbHeaders -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($kbBody))
$kbResult.hits | Select-Object source, doc_id, locator, quality, snippet
```

腾讯在当前目录中的代码是 **`00700`**；公司过滤按已登记代码精确匹配，`0700` 或 `0700.HK` 不会自动转成 `00700`。中文关键词可分别尝试简体“现金流”和繁体“現金流”；当前词法检索不保证同义词、简繁体自动互通。

一次命中是一个**正文块**，不是一整份文档；同一文档出现多条结果正常。`snippet` 是预览，`text` 是命中块正文；`locator` 给出 PDF 页码等位置，`quality` 给出提取质量状态，`score` 只用于相关性排序，不是结论置信度。搜索结果本身不包含标题，可按下一节读取元数据。

当前搜索集合为 `source_documents`，不是整个本地 Obsidian 仓库。人工笔记、旧导出副本及仅写入 Vault 的试用分析稿不会因为存在于文件夹中就自动进入这个检索集合。

### 常用筛选与分页

|参数|实际含义|
|---|---|
|`query`|非空关键词，最长 2,000 字符|
|`filters.sources`|如 `['reports']` 或 `['discord']`，以实际接入来源为准|
|`filters.symbols`|公司代码数组；按元数据精确匹配，英文不区分大小写|
|`filters.doc_types`|已登记文档类型数组；先读取文档元数据确认取值|
|`filters.date_from` / `date_to`|日期范围；依次采用 `report_date`、`published_at` 的日期、`filing_date`、`first_seen_at` 的日期；**不等于财报覆盖期 `report_period`**|
|`filters.as_of`|历史截止时间，建议显式带时区，如 `2026-09-30T15:59:59Z`|
|`filters.as_of_mode`|`system`：按系统可见时间；`public`：按版本绑定的公开时间。做历史公开时点查询须同时传 `as_of`；未知公开时间不能当作已经公开|
|`limit`|每页默认 20，允许 1–100|
|`cursor`|上一页的 `next_cursor`；保持查询、模式和筛选不变，原样传回|

```powershell
if ($kbResult.next_cursor) {
    $kbSearch.cursor = $kbResult.next_cursor
    $kbBody = $kbSearch | ConvertTo-Json -Depth 8
    $kbNextPage = Invoke-RestMethod -Method Post -Uri "$kbBase/search" `
        -Headers $kbHeaders -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($kbBody))
    $kbNextPage.hits | Select-Object doc_id, locator, snippet
}
```

索引换代或元数据变化可能返回 `409 cursor_expired`，应从第一页重新查，不能拼接两代结果。历史修复期间会分批发布新索引，这是可能发生的情况。搜索有 1,000 的内部结果窗口上限（包含用于判断下一页的预取项），超限应缩小查询范围，不能作为全库导出接口。

## 4. 从结果打开证据、完整正文和原始 PDF

接着使用上面的 `$kbResult`：

```powershell
if (-not $kbResult.hits) { throw '没有命中，请先调整关键词或筛选' }
$kbHit = $kbResult.hits[0]

# 文档标题、报告期、版本列表
$kbDoc = Invoke-RestMethod `
    -Uri "$kbBase/documents/$($kbHit.source)/$($kbHit.doc_id)" -Headers $kbHeaders
$kbDoc | Select-Object display_title, title, symbol, report_period

# 固定证据块，以及前后各一个块的上下文
$kbEvidence = Invoke-RestMethod -Uri ($kbOrigin + $kbHit.evidence_url) -Headers $kbHeaders
$kbEvidence.evidence.text
$kbEvidence.context

# 同一个提取版本的全部正文，分批读取
$kbBlocks = @()
$kbBlocksCursor = $null
do {
    $kbBlocksUrl = "$kbBase/extractions/$($kbHit.extraction_id)/blocks?limit=100"
    if ($kbBlocksCursor) {
        $kbBlocksUrl += '&cursor=' + [Uri]::EscapeDataString($kbBlocksCursor)
    }
    $kbPage = Invoke-RestMethod -Uri $kbBlocksUrl -Headers $kbHeaders
    $kbBlocks += @($kbPage.blocks)
    $kbBlocksCursor = $kbPage.next_cursor
} while ($kbBlocksCursor)
$kbBlocks | Select-Object locator, text

# 取得该次搜索对应的固定原文版本
$kbVersion = Invoke-RestMethod -Uri ($kbOrigin + $kbHit.source_version_url) -Headers $kbHeaders
$kbVersion.version | Select-Object version_id, media_type, snapshot_state, snapshot_url
```

返回的 `evidence_url`、`source_version_url`、`snapshot_url` 都是从 `/api/kb/v1/...` 开始的相对路径，应拼接 **`$kbOrigin`**，不能再拼到已经带 `/api/kb/v1` 的 `$kbBase` 后面。

如果原文为 PDF 且 `snapshot_url` 存在，可下载后用 PDF 阅读器打开（在目标文件不存在时执行）：

```powershell
if ($kbVersion.version.media_type -ne 'application/pdf' -or -not $kbVersion.version.snapshot_url) {
    throw '当前版本没有可下载的 PDF 快照'
}
$kbPdfPath = Join-Path $env:TEMP ("kb-" + [Guid]::NewGuid().ToString('N') + '.pdf')
Invoke-WebRequest -UseBasicParsing -Uri ($kbOrigin + $kbVersion.version.snapshot_url) `
    -Headers $kbHeaders -OutFile $kbPdfPath
Start-Process -FilePath $kbPdfPath
```

直接在浏览器或 Obsidian 点 API 链接不会自动带 Bearer 令牌，可能收到 401；这与文件损坏是两回事。查看财务表格时，应结合 `locator` 回到原文核对单位、列对应和脚注。

为了复现一次研究，保留命中的 `source`、`doc_id`、`source_version`、`source_sha256`、`extraction_id`、`block_id`、`locator` 和查询的 `generation_id`。不要用以后查到的“最新提取”替换当时引用的提取版本。

## 5. 给投资框架取得公司背景包

```powershell
$kbBackgroundBody = @{
    entity_type = 'company'
    entity_id = '00700'
    filters = @{ as_of_mode = 'system' }
    limit = 10
} | ConvertTo-Json -Depth 8
$kbPackage = Invoke-RestMethod -Method Post -Uri "$kbBase/background-package" `
    -Headers $kbHeaders -ContentType 'application/json; charset=utf-8' `
    -Body ([Text.Encoding]::UTF8.GetBytes($kbBackgroundBody))
$kbPackage | Select-Object entity, generation, cutoff_note, result_digest
$kbPackage.sources
$kbPackage.claims
$kbPackage.missing_information
```

返回 `researchkb.background/1`：资料与证据 `sources`、已存储研究判断 `claims`、受质疑判断 `risks_and_counter`、缺口提示，以及结果摘要 hash。它是读取已有知识的背景包，**不会在这次请求中调用模型生成公司总结**；`claims` 为空表示没有对应的已存储判断。

历史查询在 `filters` 中同时传 `as_of` 和 `as_of_mode='public'`；不传截止时间得到的是当前系统视图。`entity_type='topic'` 时，`entity_id` 按文档标题关键词匹配，不等于全文语义主题发现。`limit` 限制返回资料数量，包内资料不能直接视为该公司的完整历史；目前没有背景包分页游标。

当前 `missing_information` 中有固定实现提示，包括人工质量标注未运行、分析模型关闭；不要将这些字符串当作实时模型配置探针。业务程序应保存请求参数、返回包、版本引用及 `result_digest`，再交给研究/投资应用使用。目前尚未完成目标投资应用的正式接入。

## 6. 接口速查与当前边界

下列路径均相对于 `/api/kb/v1`。

|方法与路径|用途|权限/当前状态|
|---|---|---|
|`GET /health`、`GET /ready`|服务与索引探针|无令牌；读取响应字段判断状态|
|`POST /search`|关键词检索|`research.read`；当前用 `keyword`。`hybrid` 依赖 embedding，当前未启用|
|`GET /documents/{source}/{doc_id}`|元数据与版本列表|`research.read`|
|`GET /documents/{source}/{doc_id}/versions/{version_id}`|固定版本与快照入口|`research.read`|
|`GET /snapshots/{source}/{doc_id}/{version_id}`|下载原文二进制|`research.read`；读取时核验内容 hash；当前不支持 Range 分段请求|
|`GET /evidence/{block_id}`|证据与相邻上下文|`research.read`|
|`GET /extractions/{id}/blocks?limit=100&cursor=...`|完整提取版本分页|`research.read`；默认每页 50，上限 200|
|`POST /background-package`|公司/主题研究背景包|`research.read`；读取已有内容，不执行模型|
|`GET /claims`、`GET /claims/{id}`|已存储研究判断|`research.read`；没有判断时不会自动生成|
|`GET /changes?limit=100&cursor=...`|增量事件查询|`research.read`；客户端按 `event_id` 去重|
|`POST /analysis-runs`、`GET /analysis-runs/{id}`|创建/读取模型分析任务|需要 `analysis.run`；当前生产模型服务未启用，不作为只读测试接口|
|`POST /claims/{id}/review`|审核研究判断|同时需要 `research.read` 和 `memory.review`；会写入|
|`POST /memory-proposals/{id}/review`|审核记忆候选|需要 `memory.review`；会写入|

`changes` 当前仅在事件满页时返回 `next_cursor`。消费到尾页后再次轮询，可保留最后一个非空请求游标并按 `event_id` 去重；不要把空游标当作已经持久化的新检查点。它没有实现旧设计中的“保留期过期返回 410”保证。正式持续增量客户端还需处理断线、重复投递和源变化/解析完成是不同事件的情况。

仓库已有 [搜索 Python 示例](../scripts/kb-client-example.py) 和 [背景包 Python 示例](../scripts/kb-background-client.py)。后者的 `--as-of-mode published` 是旧参数名，当前服务实际接受 **`public`**；历史公开时点查询请使用本文直接 HTTP 示例，不照抄旧脚本的 `published` 参数。示例脚本的 `--token` 会进入命令行参数；长期集成应改用进程内密钥注入。

## 7. 常见问题

|现象|处理|
|---|---|
|连接拒绝/超时|确认 SSH 隧道仍运行、本机端口是 18766；不要把 Windows 的 8766 当服务器的 8766|
|401|检查 Bearer 令牌是否正确、是否已轮换；普通浏览器打开受保护链接也会发生|
|403|权限或集合不匹配；只读令牌不能调用分析/审核接口|
|404|检查源、文档/版本/证据 ID；不要拿本地 Markdown 文件名当文档 ID|
|409 `cursor_expired`|索引/元数据或查询条件变化，从第一页重新请求|
|422 `mode_unavailable`|当前未启用混合检索，使用 `keyword`|
|422 `task_disabled`|模型分析未启用；缺少分析权限时会先返回 403|
|422 `result_window_exceeded`|缩小关键词、公司或日期范围|
|503 `not_ready`|尚无可用索引，检查 `ready`，不要立即全库重跑|
|搜索为空|检查公司代码、来源、简繁关键词、日期含义，以及对应正文是否已经处理并进入当前索引|

错误响应形状为 `{"error":{"code":"...","message":"...","request_id":"...","retryable":false}}`。记录请求 ID 与错误码即可，不记录 Authorization 头。

## 8. 本次验证记录

2026-10-07 对现网做只读验证：`health` / `ready`、腾讯“現金流”检索及第二页、命中文档/固定版本、证据、正文分页、公司背景包、事件查询均返回 200。检索每页取得 3 个块；背景包限定 3 份资料，返回 3 个来源、0 条研究判断；命中原文版本的 `snapshot_state=verified`。

验证通过现有 SSH 在服务器本机请求 API；Windows 示例的 8 段 PowerShell 已通过语法解析检查。本次没有完成 Windows 临时隧道端到端实测，不把语法检查算作连接验收。

本次仅补使用说明和文档入口，不改生产、不调用模型、不干预服务器历史修复任务。上述结果证明这些接口当前可调用，不代表全库正文或全部投资研究结论已经验收完成。
