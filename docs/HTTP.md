# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

在同一请求中加入 `group`（也接受 `case`、`group_id`）可只复核一个业务分组；也可调用 `GET/PATCH /api/runs/<id>/groups/<group>` 或 `GET /api/runs/<id>/handoff`。分组结论包含 `READY`、`HELD`、`APPROVED`、`PENDING_REVIEW`、`releasable`、`reasons` 和中文 `conclusion`。同一记录号跨组冲突时，`cross_group_conflicts` 列出全部涉事组；存在无法识别业务组的坏行时 `global_hold=true`，所有未签发组均不可签发。

`POST /api/runs/<id>/source` 上传新版 CSV，会按记录号识别跨组移动，重算原组和新组，并把受影响的已签发组转为 `PENDING_REVIEW`。原运行仍可 `GET /api/runs/<id>` 或下载原证据；分组签发件通过 `GET /api/certificates/<certificate_id>/evidence` 查回。需要显式交接台时使用 `/api/boards` 与 `/api/boards/<board_id>/...`，未提供板号时使用 `default`。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。
