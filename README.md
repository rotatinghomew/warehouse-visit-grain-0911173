# 研学到访明细与分场馆事实集市

这是一个处理本地数据交换的仓湖项目。示例使用虚构机构和匿名合成记录，不连接业务平台。

## 数据契约

当前材料是学校、日期与可到访场馆范围的声明，入仓数据均为匿名个体到访明细。visit_id表示一次真实到访，重复键必须语义相同。people按匿名人标识去重，visits按到访事件计数，跨馆人数不可直接相加。摘录为不可变的当时查询结果。

## 代码职责

- `visitgrain/materials.py`：材料声明的学校、日期和场馆范围。
- `visitgrain/attendance.py`：匿名到访明细去重与来源关联。
- `visitgrain/cubes.py`：不同粒度的人次人数与固定摘录。
- `visitgrain/storage.py`：本地事务、内容摘要和查询工具。

## 安装与运行

使用 Python 3.11（兼容该系列补丁版本，独立容器镜像以 SHA256 摘要固定）。构建工具和运行依赖均按精确版本登记。先执行 `python3 -m pip install -r requirements-build.txt -r requirements.txt`；依赖仅在准备环境时安装，运行与测试均可断网。

```sh
python3 -m compileall -q visitgrain tests
python3 -m build --wheel --no-isolation
python3 -m unittest discover -s tests -v
python3 -m visitgrain
```

默认示例在独立临时目录执行，结束后删除目录。需要检查持久文件时可执行 `python3 -m visitgrain --root state`。测试自己创建临时目录，不依赖固定端口、外部服务或其他用例顺序。

## 容器

```sh
docker build -t visit-grain:local .
docker run --rm --network none visit-grain:local
docker run --rm --network none visit-grain:local python3 -m visitgrain
```

容器构建负责预装锁定依赖，启动不下载包。示例输出是真实接入、查询和发布的数据，不读取预制输出。测试及示例可分别运行，退出码非零表示失败。

## 交换口径

进一步的字段含义、范围及兼容边界见 `docs/data-contract.md`。
