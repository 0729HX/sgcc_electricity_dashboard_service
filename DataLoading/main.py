import logging
import logging.config
import os
import sys
import time
import schedule
import json
import random
from datetime import datetime,timedelta
from const import *
from data_fetcher import DataFetcher


def _load_options_from_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        return {}
    options = {}
    in_options = False
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("options:"):
                in_options = True
                continue
            if in_options:
                if not line.startswith("  "):
                    break
                parts = stripped.split(":", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip()
                if " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                options[key] = value
    return options


def main():
    global RETRY_TIMES_LIMIT
    try:
        config_options = _load_options_from_config()

        for key in [
            "ENABLE_DATABASE_STORAGE",
            "DB_NAME",
            "DATA_RETENTION_DAYS",
            "IGNORE_USER_ID",
            "RETRY_WAIT_TIME_OFFSET_UNIT",
            "JOB_START_TIME",
            "PHONE_NUMBER",
            "PASSWORD",
            "MYSQL_HOST",
            "MYSQL_PORT",
            "MYSQL_USER",
            "MYSQL_PASSWORD",
            "MYSQL_DB",
        ]:
            if key in config_options:
                os.environ[key] = str(config_options[key])

        PHONE_NUMBER = config_options.get("PHONE_NUMBER")
        PASSWORD = config_options.get("PASSWORD")
        JOB_START_TIME = config_options.get("JOB_START_TIME", "07:00")
        LOG_LEVEL = config_options.get("LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))
        VERSION = os.getenv("VERSION")
        RETRY_TIMES_LIMIT = int(config_options.get("RETRY_TIMES_LIMIT", os.getenv("RETRY_TIMES_LIMIT", 5)))

        if not PHONE_NUMBER or not PASSWORD:
            logging.error("PHONE_NUMBER 或 PASSWORD 未配置，请在 config.yaml 中设置后再运行。")
            sys.exit(1)

        logger_init(LOG_LEVEL)
        logging.info("国网电力数据抓取服务已启动。")
    except Exception as e:
        logging.error(f"读取配置失败，程序将带错误信息退出：{e}。")
        sys.exit()

    logging.info(f"当前仓库版本为 {VERSION}，仓库地址为 https://github.com/ARC-MX/sgcc_electricity_new.git")
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"当前日期时间为 {current_datetime}。")

    fetcher = DataFetcher(PHONE_NUMBER, PASSWORD)

    random_delay_minutes = random.randint(-10, 10)
    parsed_time = datetime.strptime(JOB_START_TIME, "%H:%M") + timedelta(minutes=random_delay_minutes)
    logging.info(f"当前登录手机号为 {PHONE_NUMBER}，程序每天将在 {parsed_time.strftime('%H:%M')} 执行一次。")

    next_run_time = parsed_time + timedelta(hours=12)

    logging.info(f'立即执行任务！之后每天将在 {parsed_time.strftime("%H:%M")} 和 {next_run_time.strftime("%H:%M")} 启动任务。')
    schedule.every().day.at(parsed_time.strftime("%H:%M")).do(run_task, fetcher)
    schedule.every().day.at(next_run_time.strftime("%H:%M")).do(run_task, fetcher)
    run_task(fetcher)

    while True:
        schedule.run_pending()
        time.sleep(1)


def run_task(data_fetcher: DataFetcher):
    for retry_times in range(1, RETRY_TIMES_LIMIT + 1):
        try:
            data_fetcher.fetch()
            return
        except Exception as e:
            logging.error(f"状态刷新任务失败，原因：[{e}]，剩余重试次数 {RETRY_TIMES_LIMIT - retry_times} 次。")
            continue

def logger_init(level: str):
    logger = logging.getLogger()
    logger.setLevel(level)
    logging.getLogger("urllib3").setLevel(logging.CRITICAL)
    format = logging.Formatter("%(asctime)s  [%(levelname)-8s] ---- %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(format)
    logger.addHandler(sh)


if __name__ == "__main__":
    main()
