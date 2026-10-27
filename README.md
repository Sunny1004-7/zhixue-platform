# 知学智教系统源码

本仓库包含“知学智教——大模型驱动的个性化教学平台”的前端、后端和配套测试代码。系统围绕高校课程组织教学材料与学习记录，并为教师和学生提供知识图谱、习题、视频推荐、智能辅导及教学资源推送服务。

## 系统功能

### 用户与课程

- 支持学生和教师登录、退出及角色权限控制。
- 课程数据按课程分别管理，用户只能访问自己有权查看的课程。
- 学生可以选择课程、查看课程概览和个人学习情况。
- 教师可以查看课程概览，并进入各项教学功能。

### 学习情况分析

系统会记录学生做题、观看视频、接受辅导和使用学习资源的过程。知识图谱与知识卡片的有效停留也会形成学习记录。这些信息由学习轨迹服务统一处理，用于更新学生在各知识点上的掌握情况。

浏览入口只接收已发布图谱节点和知识卡的访问记录，后端核对课程、修订、节点与知识点，并计算弱证据参数。作答评分、视频学习与辅导结果由各自业务服务写入学习轨迹，评分值和来源置信度由服务端确定。

学习状态计算依次执行Beta证据更新、在线平滑、时序融合和先修关系修正。在线平滑采用`η=min(η_max,n/(n+κ))`和`m_new=(1−η)m_old+ηm_posterior`，其中`n=alpha+beta`，默认`η_max=0.35`、`κ=10`。`TrajectoryService`支持按课程指定平滑参数，并随学习事件保存模型版本和参数。时间衰减与事件重放用于处理补录或更正的学习事件，更新结果会同步提供给习题、视频、辅导和教学推送模块。

不确定性由Beta后验方差和知识点对齐置信度计算：`clip(2√variance + 0.15(1−alignment_confidence), 0, 1)`。时序融合与先修约束的数值算子由系统和实验共用。后端掌握度对外使用0—100分，习题个性化难度编译按这一单位解释输入。

学生概览、图谱节点、教师详情及资源推送采用同一分类规则：有效证据量小于2.5或不确定性大于0.45时为“未接触”，其余状态按掌握度是否达到50分分为“薄弱”与“已掌握”。教师端的低证据提示同时标记需要继续观察的知识点，使教学判断与推送名单保持一致。

资源完成率按当前课程中可接收的已发布图谱、题组、视频和定向资源统计。同一资源在目录和收件箱中只计一次；题组全部提交、可信视频完成记录或资源任务完成记录构成完成依据。课程进度、学生概览与教师学情使用同一统计方法。打开资源与完成任务分别记录，资源完成不直接等同于知识掌握度上升。

### 课程知识图谱与材料处理

教师可以创建和编辑课程知识图谱，包括知识点、关系和知识卡片。每次修改都会保留版本记录，发布前还需确认材料来源和图谱内容。未发布的草稿可以放弃，未使用的草稿图谱也可以删除。

课程材料支持PDF、DOCX、PPTX和TXT格式。文件上传后，系统会先进行格式检查和隔离存放，再提取文本并按内容分段。系统根据材料寻找知识点及其关系，教师可以逐项接受或拒绝，也可以修改后写入图谱草稿。删除材料时，与该材料关联的候选内容会一并更新。

当前课程的候选知识点会按相关程度排序。系统可以自动匹配已有知识点；遇到名称或含义不明确的内容时，会交给教师确认，也允许教师暂不采用。

### 大模型任务

模型服务通过Profile管理服务地址、模型编号和访问凭证。不同教学任务可以分别设置提示词、输入要求和输出格式。调用结果返回后，系统会检查JSON结构、课程对象和材料依据，再交给教师确认。

模型调用失败时，系统会在同一Profile下按设定次数重试，并记录任务编号、使用的模型和处理结果。教师选择的Profile不会被系统自行替换，便于学校按照自己的部署条件选择模型服务。

### 六大核心算法

- 习题模块支持题组生成、三层提示、学生作答和评分，结果会更新学习情况。
- 视频模块支持视频搜索、内容核对、教师发布和学生接收。
- 辅导模块支持多种辅导方式，可以参考历史对话和长期学习记录，并沉淀教师认可的辅导经验。
- 教学推送模块根据学生近期学习情况识别重点关注对象，生成推送名单草稿。教师确认后，资源才会进入学生收件箱。
- 图谱模块支持新知识点登记、规范名称检查和跨任务复用。
- 学习轨迹模块汇总上述功能产生的学习记录，为其他模块提供更新后的学习情况。

当前示例数据包含三门课程。每门课程提供两份已发布知识图谱，每份图谱含11个节点和14条关系。

## 本地启动

### 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --index-url https://pypi.org/simple -r requirements-complete.lock.txt
python -m pip install --index-url https://pypi.org/simple -e ".[dev]" --no-deps
Copy-Item .env.example .env
python -m dotenv -f .env run -- alembic upgrade head
python -m uvicorn app.main:app --env-file .env --port 8000
```

本地验证环境为Python 3.12.7、Node.js 20.18.0、npm 10.8.2。后端完整依赖由`requirements-complete.lock.txt`固定，前端由`package-lock.json`固定。首次使用前查看`backend/.env.example`与`frontend/.env.example`。在后端编辑自己的`.env`后，按上面的命令加载配置并初始化数据库。运行命令中的dotenv和Uvicorn均来自已锁定的依赖。

### 前端

另开一个终端，运行：

```powershell
cd frontend
npm ci
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。

示例账号：

- 学生：`student@zhixing.edu.cn` / `zhixing2026`
- 教师：`teacher@zhixing.edu.cn` / `zhixing2026`

## 运行检查

后端测试：

```powershell
cd backend
python -m pytest -q
alembic check
```

前端检查：

```powershell
cd frontend
npm run typecheck
npm run build
npx playwright install chromium
node qa\verify-login.cjs
node qa\verify.cjs
npm run qa:interactions
npm run qa:navigation
```

后端测试覆盖学习状态更新、在线平滑、幂等写入、事件重放、图谱联动及各教学模块流程，并检查评分事件来源、已发布节点引用和双端分类阈值。算法服务测试直接调用领域服务，接口测试则验证浏览入口和业务结果入口各自的权限与输入规则。习题流程测试会为每次运行新建SQLite数据库，防止旧数据影响测试结果。`qa/verify-login.cjs`检查登录校验、键盘操作、密码显隐、会话、权限与网络失败；`qa/verify.cjs`检查知识图谱、材料解析及模型不可用状态。`npm run qa:interactions`检查退出失败清理、课程乱序响应、输入法、辅导草稿和会话管理；其中最小接口样本仅用于界面失败状态测试。运行浏览器检查前需启动本地前后端。登录和图谱检查的截图默认写入被Git忽略的`.qa-artifacts`，可通过`ZHIXING_QA_OUTPUT_DIR`指定输出目录；交互检查可通过`ZHIXUE_QA_OUTPUT`指定JSON结果目录，默认输出到终端。其他专项脚本保留在`qa`目录，其端口与数据库由脚本参数或环境变量指定。脚本会自动寻找Windows系统中的Microsoft Edge；也可以通过`ZHIXING_BROWSER_PATH`指定浏览器。在未安装可用浏览器时，执行上面的Playwright安装命令即可准备Chromium。

## 数据库与文件配置

### DeepSeek官方模型配置

在后端本机`.env`中填写自己的服务端凭据，并保留官方请求地址和模型标识：

```dotenv
DEEPSEEK_API_KEY=replace-with-your-own-server-key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL_ID=deepseek-flash
DEEPSEEK_THINKING_MODE=disabled
ZHIXING_MODEL_ALLOWED_DATA_REGIONS=deployment_configured
ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES=provider_account_policy
```

数据区域与保留策略由部署者依据所选服务和账号规则核验，再登记上述应用策略标签。当前官方文档将`deepseek-flash`映射到DeepSeek-V4.1-Flash-1017；请求使用别名，版本映射以[官方说明](https://api-docs.deepseek.com/)为准。

平台的短结构化文本任务默认显式关闭思考模式，保留JSON结构、知识引用、答案和提示质量检查。DeepSeek专属参数在适配器中处理，其他供应商沿用自己的参数。`enabled`可用于经过验证的思考模式任务，使用前应结合输出额度和超时设置重新检查结果。

重新启动后端后，学生或教师登录，访问`/api/v1/model-profiles?task_kind=a5.tutor_reply`，携带当前会话的Bearer令牌即可检查任务配置的可用性。未提供模型凭据、服务地址、模型ID或策略授权时，生成入口显示服务不可用；已有课程资源和常规业务仍可使用。前端环境变量只保存API地址，模型密钥始终保留在后端运行环境。

初始化会建立独立的Flash Profile及配置修订，既有模型运行记录继续保留。任务记录包括所选Profile、实际请求model、配置与提示词版本，以及供应商返回的model和可获得的token用量。空内容、截断、限流、超时、供应商拒绝和结构/质量不合格结果分别反馈。图谱与题组等教学资源由教师复核并确认发布，辅导答复保留依据与继续提问入口。

### 自动检查

GitHub Actions在推送和Pull Request时执行前端`npm ci`、类型检查、生产构建以及后端确定性测试。测试使用隔离数据库和测试适配器。浏览器登录、输入恢复和键盘导航检查在本地启动应用后运行；`npm run qa:navigation`覆盖学生搜索焦点、主要内容跳转及移动导航。

### 数据与迁移

`compose.yaml`提供PostgreSQL、后端和前端三个服务，数据库与材料使用命名卷持久保存。生成与检索由请求中的业务服务执行并保存运行结果；更大规模部署可接入独立Worker、对象存储和异步通知服务，复用现有的课程权限、资源版本与质量检查。

- 本地默认使用SQLite，数据库文件位于 `backend/.data/zhixing.db`。可通过 `ZHIXING_DATABASE_URL` 改用其他数据库。
- 数据访问使用SQLAlchemy，数据库版本由Alembic管理，也可迁移至PostgreSQL。当前迁移版本为 `0012_expand_model_version`；学习状态与掌握度证据的模型版本字段均支持128字符，可完整保存时序融合和图谱修正的组合版本标识。
- 教学材料默认保存在 `backend/.data/assets/{quarantine,accepted}`。可通过 `ZHIXING_ASSET_ROOT` 修改位置。
- 单个材料文件默认不超过20MB，可通过 `ZHIXING_ASSET_MAX_BYTES` 调整。
- 项目随包提供的示例课程配置位于 `backend/config/project_facts.yaml`。如需使用其他课程配置，可通过 `ZHIXING_FACT_SOURCE` 指定文件。

已有数据库升级前先备份数据库及教学材料，在后端目录执行`python -m dotenv -f .env run -- alembic upgrade head`。第12个迁移将两处模型版本字段从40字符扩展至128字符，保留原有学习状态、证据及其关联关系。升级后的检查命令为`python -m dotenv -f .env run -- alembic check`。若数据库已保存超过40字符的组合版本标识，回退至第11个迁移会被阻止，以保护完整版本记录。

## 账号与模型配置

- 密码使用PBKDF2-HMAC-SHA256加盐保存。会话令牌只在后端保存摘要，在线退出后会话立即失效。网络中断时，客户端仍清理本地身份、课程与草稿，并提示服务器撤销尚未确认。
- 模型访问密钥只从运行环境读取，不写入源码。
- 四组预置模型配置分别通过 `*_API_KEY`、`*_API_BASE` 和 `*_MODEL_ID` 配置。
- 部署时还需设置 `ZHIXING_MODEL_ALLOWED_DATA_REGIONS` 和 `ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES`，用于说明所选服务的数据存放区域和保留方式。
- DeepSeek Flash Profile使用官方OpenAI兼容接口`https://api.deepseek.com`，请求模型为`deepseek-flash`，访问凭证由后端运行环境提供。
- 模型服务需要支持 `response_format=json_object`。返回结果仍会经过JSON结构检查。



## 开源依赖说明

`THIRD_PARTY_NOTICES.md`列出前端与后端使用的直接依赖及传递依赖，`sbom.spdx.json`以SPDX 2.3格式记录版本、许可证和依赖关系。如依赖声明发生变化，可在联网环境中运行`python tools/generate_sbom.py`重新生成两份清单。

## 团队与研发基础

作品名称：**知学智教——大模型驱动的个性化教学平台**。本次参赛团队为“码力全开”（39139），参赛成员刘嘉程，西安交通大学研究生组，指导教师庞善民。

项目建立在前期智慧教学研究和课程应用的基础上。刘嘉程参与了2024年生成式人工智能赋能课程教学改革（“智课”）专题研究项目“AI驱动下的课程考核与质量评价”，面向机器学习相关课程开展教学应用，项目于2026年通过结题验收。前期合作研究形成了NeurIPS 2025论文“Knowledge Starts with Practice: Knowledge-Aware Exercise Generative Recommendation with Adaptive Multi-Agent Cooperation”，为知识状态分析和多智能体写作提供研究基础。

平台将课程知识图谱、学习证据、习题、视频、辅导和资源发布整合为师生协作流程。当前Web入口采用统一的师生登录组件，支持键盘操作、字段校验、密码显隐和明确的登录反馈。
