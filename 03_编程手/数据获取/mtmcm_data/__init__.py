"""MTMCM B 题数据获取工具。

设计目标：
- 可复现：每个请求都进 manifest，带 URL、时间、状态、sha256；
- 合规：遵守 robots、限速、不绕过登录/反爬；
- 可扩展：新增来源只改 config/sources.json 和一个小 parser；
- 证据化：TPDC 元数据、补充 API、背景文章分开存，方便论文引用。
"""

__version__ = "0.1.0"
