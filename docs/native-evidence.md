# 原生工程与可视化证据接口 / Native evidence

本模块只读，不依赖任何私有工作台。配置中增加 `native_roots`（绝对路径列表），即可调用：

- `list_native_projects`：有界扫描 `gtree.dat`，返回候选工程，不声称已通过 SWB 验证。
- `inspect_native_project`：文件索引与工程树 SHA-256；不修改节点、不清理结果。
- `read_plt_dataset`：按文件 header 的数据集名称解析 ASCII DF-ISE PLT，分页读取完整记录。

例如在用户自己的配置中添加 `"native_roots": ["/absolute/path/to/native-projects"]`。
支持任意电极顺序、保留电流符号和原始字段名；未闭合文件末尾的未完成记录暂不返回。
不推断电流单位、面积归一化、偏压协议或物理验收。二进制 PLT/TDR 不在解析范围。
单次源文件读取上限32 MiB，数据分页最多2000行。

Python应用可直接复用 `EvidenceService`、`parse_plt` 和 `figure_spec`。
FigureSpec的身份包含数据/图像指纹和生成配方；不是数值或物理验收结果。
本模块未引入第三方项目代码、培训文档或材料库；pytaurus等仅作为设计参考。

## English

Add an operator-owned `native_roots` array of absolute directories to the config.
The three read-only tools discover project candidates, fingerprint native project
trees, and paginate complete ASCII DF-ISE records using declared dataset names.
They do not mutate SWB projects, normalize currents, validate physics, or parse TDR.
The standalone Python evidence API is shared by applications without importing
their private source or data. Existing batch execution tools remain unchanged.
