# family-learning-space · 家庭学习空间

帮助家长陪伴一年级孩子复习与成长的工具集。首个公开技能：**书包整理助手（school-bag-organizer）**。

## 当前内容

`.trae/skills/school-bag-organizer/` —— 根据课表和每门课的用具要求，结合班级群通知，生成第二天的书包整理清单。清单为儿童友好的交互式 HTML：大复选框、拼音标注、语音朗读，适合 6 岁孩子自己打勾。

## 快速开始

启动本地服务器（首次会引导填写孩子信息、课表与各科用具要求）：

```bash
python .trae/skills/school-bag-organizer/web/preview_server.py
```

- 电脑访问 `http://localhost:8090/`
- 手机与电脑同 WiFi 时访问 `http://<电脑IP>:8090/`

生成离线单文件版（内嵌数据，可直接发到手机浏览器打开）：

```bash
node .trae/skills/school-bag-organizer/web/build_standalone.js
```

## 目录

| 路径 | 说明 |
|---|---|
| `.trae/skills/school-bag-organizer/SKILL.md` | 技能完整说明（数据字段、首次引导、工作流程、反馈通道） |
| `.trae/skills/school-bag-organizer/data-templates/` | 匿名初始模板（`data/` 由它生成，个人数据不入库） |
| `.trae/skills/school-bag-organizer/web/` | 交互式清单页、本地服务器与反馈后端 |
| `.trae/skills/school-bag-organizer/web/vendor/feedback.js` | 页内「提建议」反馈组件 |

## 隐私

- **个人数据**：`data/` 目录存放孩子姓名、学校、课表等，已被 `.gitignore` 排除，不会进入仓库。模板为匿名示例数据。
- **反馈组件**：`vendor/feedback.js` 是本项目自带的「提建议」组件，不是第三方追踪脚本。它只把用户主动提交的反馈（正文 + 可选截图）和浏览器基础调试信息（页面地址、UA、屏幕、匿名安装 ID）发往**部署者自己的**中转服务；`relay.url` 默认留空，未配置时反馈**只保存在本机、绝不外发**。详见 `SKILL.md` 的「用户反馈通道」一节。

## 许可

[MIT License](LICENSE)。更多技能与内容将陆续加入。
