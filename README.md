# 门诊预约候补核对

门诊排班管理员可在工作台上传来源 CSV，对照规则判断差异，按业务分组签发已对账批次或记录暂缓意见。跨组记录冲突会同时锁定涉事组，来源更新导致记录跨组时自动重算并将受影响签发转待复核，原签发件仍可查回。

重放预约取消和候补进队，按优先级与入队顺序补位，隔离失效预约。

## 启动

```sh
docker compose up --build -d --wait
```

打开 <http://localhost:18328>。页面预览带异常样例。选中阶段查看计算证据，选择可签发样例并执行批次，然后提交复核意见。

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) · [规则与测试](docs/DEPTH.md)
