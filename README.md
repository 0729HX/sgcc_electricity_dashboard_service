# SGCC 电力用电监控仪表盘
<img width="1920" height="1080" alt="image" src="https://github.com/0729HX/sgcc_electricity_dashboard_service/blob/main/%E6%95%88%E6%9E%9C%E5%9B%BE.JPG" />


一个面向个人/家庭/小型场景的国网电力用电数据抓取与可视化仪表盘项目。  
通过自动登录国家电网网站，定时抓取账户的用电数据，落库到 MySQL 中，并通过 Web 仪表盘以黑色玻璃拟态风格展示账户余额、最近用电情况、月度/年度统计等信息。

> 本仓库用于演示完整的「数据抓取 + 数据落库 + Web 仪表盘」方案，示例配置中所有账号、密码、主机地址等均为虚构占位值，请在实际部署时替换为自己的真实配置。

---

## 项目来源说明

- 数据抓取脚本  
  `DataLoading` 目录中的国网电力爬取逻辑来源于仓库地址：`https://github.com/ARC-MX/sgcc_electricity_new`作者此前的开源脚本项目，在此基础上对以下部分进行了改造：
  - 将原本以文件导出为主的方式，调整为以 MySQL 落库为主；
  - 增加了「已有最近 30 天数据则只抓取 7 天并增量更新」的逻辑；
  - 补全了建库建表与字段注释逻辑，便于下游统计与可视化使用。

- 本仓库新增内容  
  - 基于 Flask + ECharts 的可视化仪表盘服务（`Panel` 目录）；
  - 用于容器化部署的 Dockerfile 与 `docker-compose.yml`；
  - 统一的 `config.yaml` 配置入口与示例配置。

---

## 特性概览

- 自动化数据抓取
  - 使用 Selenium 自动登录国家电网网站
  - 支持滑块验证码识别（基于 ONNX 模型）
  - 定时任务每日自动运行，无需人工干预

- 数据持久化与增量更新
  - 使用 MySQL 存储年度、月度、每日用电数据和余额信息
  - 自动建库建表并补充字段注释
  - 检查数据库是否已有最近 30 天数据，如果齐全则只抓取最近 7 天并增量更新，避免重复拉全量历史数据

- 可视化仪表盘
  - 后端基于 Flask 提供 REST API
  - 前端使用 ECharts 构建黑色玻璃风格仪表盘
  - 显示账户余额、最近日用电量及日期、累计用电/电费等概览
  - 日用电折线图、月度用电/电费柱状图，带平均线及颜色分级提示

- 一键 Docker 部署
  - 使用 `docker-compose` 启动两个容器：
    - `dataloading`：数据抓取与写库服务
    - `panel`：Web 仪表盘服务
  - 默认暴露前端访问端口 `8011`

---

## 项目结构

以 `dashboard_service` 目录为服务根目录，核心结构如下：

```text
dashboard_service/
├─ docker-compose.yml      # 容器编排配置
├─ config.yaml             # 全局配置文件（唯一配置入口）
├─ requirements.txt        # Python 依赖
│
├─ DataLoading/            # 数据抓取与写库服务（Python + Selenium）
│  ├─ main.py              # 定时任务入口，读取 config.yaml 后运行抓取逻辑
│  ├─ data_fetcher.py      # 核心数据抓取逻辑（登录、抓取、写库、增量更新等）
│  ├─ onnx.py              # 滑块验证码识别相关逻辑
│  ├─ const.py             # 常量配置（登录 URL、页面 URL 等）
│  ├─ Dockerfile           # DataLoading 服务构建脚本
│  └─ ...                  # 其他工具代码
│
└─ Panel/                  # Web 仪表盘服务（Flask + ECharts）
   ├─ app.py               # Flask 应用入口，提供 API 和页面渲染
   ├─ templates/
   │  └─ index.html        # 仪表盘页面（黑玻璃/ECharts）
   ├─ Dockerfile           # Panel 服务构建脚本
   └─ ...                  # 前端相关资源
```

---

## 技术栈

- 语言与运行环境
  - Python 3.11（容器基于 `python:3.11-slim`）
  - Docker & docker-compose

- 后端与抓取
  - Selenium（Edge / Firefox 驱动）
  - ONNX Runtime（滑块验证码识别）
  - schedule（定时任务）
  - PyMySQL（连接 MySQL）

- Web 仪表盘
  - Flask（提供 API 与页面）
  - ECharts（数据可视化）
  - 定制黑色玻璃拟态主题样式

- 数据库
  - MySQL（建议 5.7+ / 8.x）
  - 主要表：
    - `yearly_stats`：年度统计（总用电量/电费、余额、最近一次日用电）
    - `monthly_stats`：月度用电/电费
    - `daily_usage`：每日用电明细（支持按 user_id + date 去重增量更新）

---

## 配置说明（config.yaml）

项目仅使用 `config.yaml` 作为唯一配置入口，不再依赖 `.env` 或系统环境变量（会在启动时将其中配置写入进程环境，供内部代码读取）。

配置文件示例（以下为示例值，上传到 GitHub 时不会包含真实个人信息）：

```yaml
# 配置选项
options:
  # 登录手机号
  PHONE_NUMBER: "15000000000"        # 示例手机号，占位用
  # 登录密码
  PASSWORD: "your_password"          # 示例密码，占位用
  # 是否启用数据库存储
  ENABLE_DATABASE_STORAGE: true
  # 数据库名称（逻辑名）
  DB_NAME: "sgcc_electricity"
  # 定时任务启动时间（24小时制）
  JOB_START_TIME: "07:00"
  # 重试等待时间偏移单位（分钟）
  RETRY_WAIT_TIME_OFFSET_UNIT: 15
  # MySQL 主机地址
  MYSQL_HOST: "your_mysql_host"      # 示例主机，占位用
  # MySQL 端口
  MYSQL_PORT: 3306
  # MySQL 用户名
  MYSQL_USER: "your_mysql_user"      # 示例用户名，占位用
  # MySQL 密码
  MYSQL_PASSWORD: "your_mysql_password"  # 示例密码，占位用
  # MySQL 数据库名
  MYSQL_DB: "sgcc_electricity"

# 字段类型定义（供前端或配置校验使用）
schema:
  PHONE_NUMBER: str
  PASSWORD: password
  IGNORE_USER_ID: str
  ENABLE_DATABASE_STORAGE: bool
  DB_NAME: str
  JOB_START_TIME: str
  RETRY_WAIT_TIME_OFFSET_UNIT: int(2,30)
  DATA_RETENTION_DAYS: int
```

关键说明：

- `PHONE_NUMBER` / `PASSWORD`  
  用于登录国家电网网站的账号密码，请勿将真实凭据提交到公共仓库。
- `ENABLE_DATABASE_STORAGE`  
  是否开启数据库写入，设为 `true` 后会自动在 MySQL 中创建库表并写入数据。
- `JOB_START_TIME`  
  每日数据抓取任务的基准时间（例如 `"07:00"`），程序启动时会再随机 ±10 分钟，并每天执行两次任务（相隔约 12 小时）。
- `MYSQL_*`  
  面板服务（Panel）和数据抓取服务（DataLoading）都使用这些配置连接 MySQL，并共享同一个数据库。

---

## 数据抓取逻辑概览

数据抓取服务入口：`DataLoading/main.py`

核心流程：

1. 启动时读取 `config.yaml`，设置日志级别、重试次数、定时任务时间等。
2. 创建 `DataFetcher` 实例并注册定时任务：
   - 每天在配置的 `JOB_START_TIME` ±10 分钟附近执行一次抓取任务；
   - 再间隔 12 小时再执行一次。
3. 每次抓取任务中：
   - 启动浏览器（Windows 下默认 Edge，Linux 容器中使用 Firefox + geckodriver）；
   - 打开登录页，输入手机号和密码（或验证码登录，根据配置/环境）；
   - 经过滑块验证码识别，完成登录；
   - 访问电费余额页面和用电明细页面，抓取：
     - 账户余额
     - 最近一次日用电日期与用电量
     - 年度累计用电量与电费
     - 月度用电与电费
     - 最近 N 日的日用电明细
   - 写入 MySQL 数据库（`yearly_stats`、`monthly_stats`、`daily_usage`），其中：
     - `daily_usage` 采用 `INSERT ... ON DUPLICATE KEY UPDATE` 实现增量更新；
     - 内部会优先检查数据库中是否已经有最近 30 天日用电数据，如果数据齐全，则这次只抓取最近 7 天的数据并增量更新。

---

## 仪表盘展示概览

仪表盘服务入口：`Panel/app.py`

主要内容：

- 启动时读取 `config.yaml`，设置 MySQL 连接环境变量。
- 建立数据库连接，从以下表中查询数据：
  - `yearly_stats`：读取最近一年的统计数据，提取余额、最近一次日用电日期/用电量、年度总用电/电费。
  - `daily_usage`：按日期升序读取全部日用电数据，供折线图使用。
  - `monthly_stats`：读取所有月份的用电/电费，供柱状图使用。
- API：
  - `GET /`：返回仪表盘页面 `index.html`。
  - `GET /api/stats/overview`：返回概览数据（余额、最近日用电量/日期、年度用电/电费）。
- 前端页面 `templates/index.html`：
  - 黑色玻璃拟态卡片布局；
  - ECharts 折线图、柱状图；
  - 平均线与颜色梯度根据高低程度变化，便于快速识别异常用电。

---

