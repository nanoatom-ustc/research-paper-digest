# 📬 Research Paper Digest / 文献每日摘要

这是一个运行在 GitHub Actions 上的多来源论文监控工具。它按关注主题查询近期的 arXiv 预印本，以及 APS、Nature Portfolio、Science/AAAS 和 Optica Publishing Group 期刊论文，合并、去重后通过邮件发送每日摘要。

期刊数据来自 Crossref 公共 API：APS 使用 DOI 前缀 `10.1103`，Nature Portfolio 使用 `10.1038`，Science/AAAS 使用 `10.1126`，Optica Publishing Group 使用 `10.1364`。

## 默认检索范围

- 关注主题：tweezer array、neutral atom / neutral atoms、PIC、microring、nanofiber、surface force。
- arXiv：可通过 `SEARCH_CATEGORIES` 限制分区。
- APS：全部 APS 期刊，但默认排除 Physical Review B 和 Physical Review D。
- Nature：仅配置的 Nature Portfolio 期刊。
- Science：仅 Science 和 Science Advances。
- Optica：由 `OPTICA_JOURNALS` 精确控制。

API 只负责召回候选论文。程序会再次检查标题和摘要，只有完整主题词或受支持的常见写法实际出现时才发送，避免仅凭 `optical` 等部分词命中。匹配不区分大小写，并兼容连字符、空格和常见单复数；`tweezer array` 也会匹配 atom array(s)、atomic array(s)、neutral atom array(s)、Rydberg array(s)、array(s) of (optical) tweezers 等常见表达；`PIC` 也会匹配 photonic integrated circuit(s) 和 integrated photonic circuit(s)。

## GitHub 配置

在 `Settings → Secrets and variables → Actions` 中配置。

### Secrets（必填）

| Name | 说明 |
|---|---|
| `EMAIL_SENDER` | 发件邮箱（当前支持 QQ 邮箱、163 邮箱） |
| `EMAIL_PASSWORD` | SMTP 授权码，不是邮箱登录密码 |
| `RECIPIENT_EMAIL` | 收件邮箱 |

### Variables

| Name | 默认值 | 说明 |
|---|---|---|
| `SEARCH_KEYWORDS` | `tweezer array,neutral atom,neutral atoms,PIC,microring,nanofiber,surface force` | 英文逗号分隔，作用于所有数据源 |
| `SEARCH_SOURCES` | `arxiv,aps,nature,science,optica` | 启用的数据源 |
| `SEARCH_CATEGORIES` | 空 | arXiv 分区代码，仅影响 arXiv |
| `APS_JOURNALS` | 空 | APS 期刊允许列表 |
| `APS_EXCLUDE_JOURNALS` | `Physical Review B,Physical Review D,PRB,PRD` | APS 期刊排除列表 |
| `NATURE_JOURNALS` | 6 本指定期刊 | Nature 期刊允许列表 |
| `SCIENCE_JOURNALS` | `Science,Science Advances` | Science 期刊允许列表 |
| `OPTICA_JOURNALS` | `Optica,Optics Express` | Optica Publishing Group 期刊允许列表 |
| `FETCH_DAYS` | `2` | 查询最近几天；`0` 表示不添加日期限制 |
| `MAX_RESULTS` | `20` | 合并所有数据源后最多保留的论文数 |
| `CROSSREF_MAILTO` | 空 | 可选联系邮箱 |

示例：

```ini
SEARCH_KEYWORDS=tweezer array,neutral atom,neutral atoms,PIC,microring,nanofiber,surface force
SEARCH_SOURCES=arxiv,aps,nature,science,optica
SEARCH_CATEGORIES=physics.atom-ph,quant-ph,physics.optics
APS_EXCLUDE_JOURNALS=Physical Review B,Physical Review D,PRB,PRD
OPTICA_JOURNALS=Optica
FETCH_DAYS=3
MAX_RESULTS=30
```

## 手动运行和测试

进入仓库 `Actions` 页面，选择 **Daily Research Paper Digest**，点击 **Run workflow**。

```bash
pip install -r requirements.txt
python main.py
python -m unittest discover -s tests -v
```

测试使用模拟响应，不访问外部网络。

## 项目结构

```text
research-paper-digest/
├── .github/workflows/arxiv_daily.yml
├── main.py
├── arxiv_fetcher.py
├── crossref_fetcher.py
├── aps_fetcher.py
├── nature_fetcher.py
├── science_fetcher.py
├── optica_fetcher.py
├── paper_utils.py
├── email_sender.py
├── config.py
├── tests/test_aps_fetcher.py
├── tests/test_keyword_matching.py
└── requirements.txt
```

## 数据说明

- 覆盖范围取决于各出版商在 Crossref 中登记的元数据及 DOI 前缀。
- 如果 Crossref 没有提供摘要，严格过滤只能根据标题判断。
- arXiv 请求间隔至少 3 秒；遇到 429、部分临时 5xx 或连接超时，最多尝试 4 次，默认退避 30/60/120 秒，并尊重 `Retry-After`（秒数或 HTTP 日期）。每页重试等待总预算为 300 秒；服务器要求更久时直接报错，不提前重试。
- arXiv 最终查询失败会继续处理其他数据源，但邮件会标为「数据不完整」，任务以非零状态退出，不再误报「今日无新论文 / 系统运行正常」。成功的空查询仍发送原有空摘要。其他出版商的内部错误处理不在本次修复范围。
- 测试 CI 仅运行模拟测试，不使用 SMTP 凭据或发送邮件；每日摘要仍只由定时/手动工作流运行。
- 本修复不会自动补发过去失败窗口的论文。需要补查时，请临时扩大 Actions 变量 `FETCH_DAYS` 后手动运行，再恢复原值；补查可能重复发送窗口内的论文。
- 不同数据源的结果会按 DOI/ID 去重，并共同应用 `MAX_RESULTS` 限制。

## License

MIT
