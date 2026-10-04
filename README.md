# family-learning-space · 家庭学习空间

帮助家长陪伴一年级孩子复习与成长的工具集。每个能力是一个**技能**（`.trae/skills/<技能名>/`），
门户技能 `growth-home` 用本地服务器（`web/preview_server.py`，端口 8090）把兄弟技能的页面与数据
托管成一个入口，手机/平板/电脑同 WiFi 访问，看到的是同一份数据。

## 快速开始

```bash
python setup.py                 # 首次：先选数据区（data-root），再填孩子信息、课表、教材版本
python setup.py --start         # 直接启动网页服务
python setup.py --check         # 只体检：哪些技能缺配置（不改任何文件）
```

- 电脑访问 `http://localhost:8090/`
- 手机/平板与电脑同 WiFi，访问启动日志里打印的 `http://<电脑IP>:8090/`

## 代码与隐私是分开的

这是本仓库最重要的一条设计：**代码可以随便分发，个人数据一步都不出本机**。
数据落在**仓库之外**的独立目录 **data-root**（由仓库根 `local.json` 的 `data_root` 指定，
示例见 `local_example.json`），**仓库内不存在任何 `data/` 目录**。

| 分区 | 位置 | 是否公开 |
|---|---|---|
| 代码 / 页面 / 脚本 | `SKILL.md`、`skill.json`、`web/`、`tools/`、各技能 `data-templates/` | 公开、可分发 |
| 配置模板 | 各技能 `data-templates/config.json`（匿名示例） | 公开 |
| **个人数据** | **仓库之外的 data-root**：`<root>/web\|learn\|bag\|art\|lib\|comp\|textbooks\|personal/`（`personal/` 现只放隐私词表） | **只在你的电脑上** |

数据区布局与门户 URL 命名空间同构，路径解析统一走 `tools/data_paths.py`（落在仓库内会直接报错）；
页面不直接读本机文件，而是通过本地服务器的 `GET/POST /api/...` 读写，所以多设备天然同步。
完整约定见 [`.trae/rules/project_rules.md`](.trae/rules/project_rules.md)，其中第 8 节是「代码与隐私隔离」。

想换成自己的信息，只改配置就行：

| 技能 | 配置项（data-root 下的 `<命名空间>/data/config.json`） |
|---|---|
| `school-bag-organizer` | `childName` `school` `grade` `className` `semester` `morningCutoff` `textbooks{}` |
| `growth-home` | `childName` `school` `grade` `className` `semester` |
| `learning-growth-board` | `childName` `school` `grade` `className` `semester` |
| `home-library` | `childName` `libraryTitle` |
| `xiaoshan-art-archive` | `childName` `archiveTitle` |

已有数据想搬到仓库外？用迁移工具（两阶段，先复制、验收后再删）：

```bash
python tools/migrate_to_data_root.py --data-root D:\Shan_Learn-data            # dry-run 看计划
python tools/migrate_to_data_root.py --data-root D:\Shan_Learn-data --apply    # 阶段一：复制
python tools/migrate_to_data_root.py --data-root D:\Shan_Learn-data --cleanup  # 阶段二：删仓库内副本
```

## 加自己的功能：一个新需求 = 一个新页面/新技能

```bash
python tools/new_skill.py my-new-thing --title 我的新功能 --desc "当用户说……时调用"
python tools/portal_wire.py list                 # 先看门户现状
python tools/portal_wire.py add-page --id my-new-thing --name 我的新功能 \
    --src /my-new-thing/web/index.html --mount my-new-thing --skill my-new-thing
python tools/smoke_test.py                       # 起服务逐页点一遍验收
```

也可以什么都不敲，直接对 Trae/WorkBuddy 说「给成长家园加一个练琴打卡页」——`portal-builder` 技能
会问清需求、生成页面、接线、自己冒烟验收。它复用门户已有的组件（主题、打卡日历、语音、朗读、拼音、
反馈按钮），所以新页面天然就有跨设备同步和儿童友好的样子。

不要直接改别人的页面——私有逻辑写在私有技能里，公共页面才不会被改坏（`python tools/portal_wire.py undo`
可以撤销任何一次接线）。

## 目录

| 路径 | 说明 |
|---|---|
| `.trae/skills/<技能名>/SKILL.md` | 各技能完整说明（数据字段、首次引导、工作流程） |
| `.trae/skills/<技能名>/skill.json` | 声明技能的 URL 前缀 / 代码目录 / 数据目录（门户自动挂载，`tools/data_paths.py` 解析） |
| `.trae/skills/<技能名>/DATA.md` | 该技能的数据落在 data-root 的哪个位置 |
| `.trae/skills/<技能名>/data-templates/` | 匿名初始模板（data-root 里的 `data/` 由它生成，个人数据不入库） |
| `.trae/skills/growth-home/web/preview_server.py` | 门户本地服务器（8090）与全部 `/api/...` 路由 |
| `tools/data_paths.py` | 数据区路径解析唯一真源（data-root 必须在仓库之外） |
| `tools/` | 隐私守卫、打包器、新技能脚手架、数据迁移、教材下载管线（见 `tools/README.md`） |
| `<data-root>/textbooks/` | 教材页图与页码索引（在仓库之外；版权原因不随发布包分发，用 `tools/` 自行获取） |
| `dist/` | 打包产物（由 `tools/build_dist.py` 生成，不入库） |

## 分发 / 发布

```bash
python tools/privacy_guard.py --all              # 1. 自查：会不会把隐私带出去
python tools/build_dist.py                       # 2. 技能包（门户全套）
python tools/build_dist.py --bundle               # 或：整仓包（技能 + 网页框架 + 安装器 + 规则）
python tools/privacy_guard.py --dist dist/xxx.zip # 3. 复查包内（会解开 zip 扫每个文本成员）
```

打包器**白名单取件**：`data/` 根本不参与复制（不是"复制后删"），包内 `data/` 由 `data-templates/`
重建，出包后自动自检，命中隐私就删包中止。整仓包内置 `开始使用.md`，拿到的人 `python setup.py`
填完自己的信息就能起服务。

## 许可

[MIT License](LICENSE)。附注：`textbooks/` 内电子教材来自国家中小学智慧教育平台（官方公开资源），
版权归原作者与出版社所有，仅供家庭个人学习使用，请勿再分发或商用；`personal/`、data-root 里的各技能
`data/` 为使用者个人数据，不在版本库中，不适用本许可的再分发条款。
