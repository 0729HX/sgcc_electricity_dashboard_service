import logging
import os
import re
import subprocess
import time
import json

import random
import base64
import pymysql
from datetime import datetime
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from const import *

import numpy as np
# import cv2
from io import BytesIO
from PIL import Image
from onnx import ONNX
import platform


def base64_to_PLI(base64_str: str):
    base64_data = re.sub('^data:image/.+;base64,', '', base64_str)
    byte_data = base64.b64decode(base64_data)
    image_data = BytesIO(byte_data)
    img = Image.open(image_data)
    return img

def get_transparency_location(image):
    '''获取基于透明元素裁切图片的左上角、右下角坐标

    :param image: cv2加载好的图像
    :return: (left, upper, right, lower)元组
    '''
    # 1. 扫描获得最左边透明点和最右边透明点坐标
    height, width, channel = image.shape  # 高、宽、通道数
    assert channel == 4  # 无透明通道报错
    first_location = None  # 最先遇到的透明点
    last_location = None  # 最后遇到的透明点
    first_transparency = []  # 从左往右最先遇到的透明点，元素个数小于等于图像高度
    last_transparency = []  # 从左往右最后遇到的透明点，元素个数小于等于图像高度
    for y, rows in enumerate(image):
        for x, BGRA in enumerate(rows):
            alpha = BGRA[3]
            if alpha != 0:
                if not first_location or first_location[1] != y:  # 透明点未赋值或为同一列
                    first_location = (x, y)  # 更新最先遇到的透明点
                    first_transparency.append(first_location)
                last_location = (x, y)  # 更新最后遇到的透明点
        if last_location:
            last_transparency.append(last_location)

    # 2. 矩形四个边的中点
    top = first_transparency[0]
    bottom = first_transparency[-1]
    left = None
    right = None
    for first, last in zip(first_transparency, last_transparency):
        if not left:
            left = first
        if not right:
            right = last
        if first[0] < left[0]:
            left = first
        if last[0] > right[0]:
            right = last

    # 3. 左上角、右下角
    upper_left = (left[0], top[1])  # 左上角
    bottom_right = (right[0], bottom[1])  # 右下角

    return upper_left[0], upper_left[1], bottom_right[0], bottom_right[1]

class DataFetcher:

    def __init__(self, username: str, password: str):
        if 'PYTHON_IN_DOCKER' not in os.environ: 
            import dotenv
            dotenv.load_dotenv(verbose=True)
        self._username = username
        self._password = password
        base_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(base_dir, "captcha.onnx")
        self.onnx = ONNX(model_path)

        # 获取 ENABLE_DATABASE_STORAGE 的值，默认为 False
        self.enable_database_storage = os.getenv("ENABLE_DATABASE_STORAGE", "false").lower() == "true"
        self.DRIVER_IMPLICITY_WAIT_TIME = int(os.getenv("DRIVER_IMPLICITY_WAIT_TIME", 60))
        self.RETRY_TIMES_LIMIT = int(os.getenv("RETRY_TIMES_LIMIT", 5))
        self.LOGIN_EXPECTED_TIME = int(os.getenv("LOGIN_EXPECTED_TIME", 10))
        self.RETRY_WAIT_TIME_OFFSET_UNIT = int(os.getenv("RETRY_WAIT_TIME_OFFSET_UNIT", 10))
        self.IGNORE_USER_ID = os.getenv("IGNORE_USER_ID", "xxxxx,xxxxx").split(",")
        self.mysql_host = os.getenv("MYSQL_HOST", "192.168.1.223")
        self.mysql_port = int(os.getenv("MYSQL_PORT", 3306))
        self.mysql_user = os.getenv("MYSQL_USER", "root")
        self.mysql_password = os.getenv("MYSQL_PASSWORD", "root")
        self.mysql_db = os.getenv("MYSQL_DB", os.getenv("DB_NAME", "sgcc_electricity"))
        self._schema_initialized = False

    def _click_button(self, driver, button_search_type, button_search_key):
        '''封装点击函数，仅在元素可点击时执行点击'''
        WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
            EC.element_to_be_clickable((button_search_type, button_search_key))
        )
        click_element = driver.find_element(button_search_type, button_search_key)
        driver.execute_script("arguments[0].click();", click_element)

    # @staticmethod
    def _is_captcha_legal(self, captcha):
        '''检查 ddddocr 识别结果，判断验证码是否合法'''
        if (len(captcha) != 4):
            return False
        for s in captcha:
            if (not s.isalpha() and not s.isdigit()):
                return False
        return True

    # @staticmethod 
    def _sliding_track(self, driver, distance):# 机器模拟人工滑动轨迹
        # 获取按钮
        slider = driver.find_element(By.CLASS_NAME, "slide-verify-slider-mask-item")
        ActionChains(driver).click_and_hold(slider).perform()
        # 获取轨迹
        # tracks = _get_tracks(distance)
        # for t in tracks:
        yoffset_random = random.uniform(-2, 4)
        ActionChains(driver).move_by_offset(xoffset=distance, yoffset=yoffset_random).perform()
            # time.sleep(0.2)
        ActionChains(driver).release().perform()

    def _ensure_schema_comments(self, cursor):
        cursor.execute(
            """
            ALTER TABLE yearly_stats
                MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '主键ID',
                MODIFY COLUMN `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                MODIFY COLUMN `year` INT NOT NULL COMMENT '年份',
                MODIFY COLUMN `total_usage` DOUBLE NULL COMMENT '年度总用电量(kWh)',
                MODIFY COLUMN `total_charge` DOUBLE NULL COMMENT '年度总电费(元)',
                MODIFY COLUMN `balance` DOUBLE NULL COMMENT '账户当前电费余额(元)',
                MODIFY COLUMN `last_daily_date` DATE NULL COMMENT '最近一次日用电日期',
                MODIFY COLUMN `last_daily_usage` DOUBLE NULL COMMENT '最近一次日用电量(kWh)',
                COMMENT='年度用电统计表';
            """
        )
        cursor.execute(
            """
            ALTER TABLE monthly_stats
                MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '主键ID',
                MODIFY COLUMN `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                MODIFY COLUMN `year` INT NOT NULL COMMENT '年份',
                MODIFY COLUMN `month` INT NOT NULL COMMENT '月份(1-12)',
                MODIFY COLUMN `usage` DOUBLE NULL COMMENT '当月总用电量(kWh)',
                MODIFY COLUMN `charge` DOUBLE NULL COMMENT '当月总电费(元)',
                COMMENT='月度用电统计表';
            """
        )
        cursor.execute(
            """
            ALTER TABLE daily_usage
                MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '主键ID',
                MODIFY COLUMN `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                MODIFY COLUMN `date` DATE NOT NULL COMMENT '日期',
                MODIFY COLUMN `usage` DOUBLE NOT NULL COMMENT '当日用电量(kWh)',
                COMMENT='每日用电明细表';
            """
        )

    def connect_user_db(self, user_id):
        """连接数据库并创建年度、月度、每日统计三张表"""
        try:
            server_conn = pymysql.connect(
                host=self.mysql_host,
                port=self.mysql_port,
                user=self.mysql_user,
                password=self.mysql_password,
                charset="utf8mb4",
                autocommit=True,
            )
            server_cursor = server_conn.cursor()
            server_cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.mysql_db}` "
                "DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci;"
            )
            server_cursor.close()
            server_conn.close()

            self.connect = pymysql.connect(
                host=self.mysql_host,
                port=self.mysql_port,
                user=self.mysql_user,
                password=self.mysql_password,
                database=self.mysql_db,
                charset="utf8mb4",
                autocommit=False,
            )
            cursor = self.connect.cursor()
            logging.info(f"Database of {self.mysql_db} connected successfully.")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS yearly_stats (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
                    `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                    `year` INT NOT NULL COMMENT '年份',
                    `total_usage` DOUBLE NULL COMMENT '年度总用电量(kWh)',
                    `total_charge` DOUBLE NULL COMMENT '年度总电费(元)',
                    `balance` DOUBLE NULL COMMENT '账户当前电费余额(元)',
                    `last_daily_date` DATE NULL COMMENT '最近一次日用电日期',
                    `last_daily_usage` DOUBLE NULL COMMENT '最近一次日用电量(kWh)',
                    UNIQUE KEY uk_yearly_user_year (`user_id`, `year`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='年度用电统计表';
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_stats (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
                    `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                    `year` INT NOT NULL COMMENT '年份',
                    `month` INT NOT NULL COMMENT '月份(1-12)',
                    `usage` DOUBLE NULL COMMENT '当月总用电量(kWh)',
                    `charge` DOUBLE NULL COMMENT '当月总电费(元)',
                    UNIQUE KEY uk_monthly_user_ym (`user_id`, `year`, `month`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='月度用电统计表';
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_usage (
                    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
                    `user_id` VARCHAR(64) NOT NULL COMMENT '用户编号',
                    `date` DATE NOT NULL COMMENT '日期',
                    `usage` DOUBLE NOT NULL COMMENT '当日用电量(kWh)',
                    UNIQUE KEY uk_daily_user_date (`user_id`, `date`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日用电明细表';
                """
            )

            self.table_yearly = "yearly_stats"
            self.table_monthly = "monthly_stats"
            self.table_daily = "daily_usage"
            if not self._schema_initialized:
                self._ensure_schema_comments(cursor)
                self._schema_initialized = True
            self.connect.commit()
			
        # 如果表已存在，则不会创建
        except Exception as e:
            logging.error(f"Create db or Table error: {e}")
            if hasattr(self, "connect") and self.connect:
                try:
                    self.connect.close()
                except Exception:
                    pass
                self.connect = None
            return False
        return True

    def _has_recent_30_days(self, user_id):
        """检查数据库中是否已经存在该用户最近 30 天的日用电数据"""
        if self.connect is None:
            return False
        try:
            cursor = self.connect.cursor()
            cursor.execute(
                """
                SELECT COUNT(DISTINCT `date`)
                FROM daily_usage
                WHERE `user_id` = %s
                  AND `date` >= CURDATE() - INTERVAL 29 DAY;
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            count = row[0] if row and row[0] is not None else 0
            return count >= 30
        except Exception as e:
            logging.debug(f"检查最近 30 天日用电数据是否齐全失败：{e}")
            return False

    def insert_data(self, data:dict):
        if self.connect is None:
            logging.error("数据库连接尚未建立，无法写入数据。")
            return
        try:
            cursor = self.connect.cursor()
            sql = f"""
                INSERT INTO {self.table_daily} (`user_id`, `date`, `usage`)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `usage` = IF(VALUES(`usage`) <> `usage`, VALUES(`usage`), `usage`);
            """
            cursor.execute(sql, (data['user_id'], data['date'], data['usage']))
            self.connect.commit()
        except BaseException as e:
            logging.debug(f"写入每日用电数据失败：{e}")

    def _upsert_yearly_stats(self, user_id, balance, last_daily_date, last_daily_usage, yearly_usage, yearly_charge):
        if self.connect is None:
            logging.error("数据库连接尚未建立，无法更新年度统计数据。")
            return
        try:
            cursor = self.connect.cursor()
            year = datetime.now().year
            if datetime.now().month == 1:
                year = year - 1
            sql = f"""
                INSERT INTO {self.table_yearly}
                (user_id, year, total_usage, total_charge, balance, last_daily_date, last_daily_usage)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_usage = IF(VALUES(total_usage) <> total_usage, VALUES(total_usage), total_usage),
                    total_charge = IF(VALUES(total_charge) <> total_charge, VALUES(total_charge), total_charge),
                    balance = IF(VALUES(balance) <> balance, VALUES(balance), balance),
                    last_daily_date = IF(VALUES(last_daily_date) <> last_daily_date, VALUES(last_daily_date), last_daily_date),
                    last_daily_usage = IF(VALUES(last_daily_usage) <> last_daily_usage, VALUES(last_daily_usage), last_daily_usage);
            """
            total_usage = float(yearly_usage) if yearly_usage is not None else None
            total_charge = float(yearly_charge) if yearly_charge is not None else None
            last_usage = float(last_daily_usage) if last_daily_usage is not None else None
            cursor.execute(
                sql,
                (user_id, year, total_usage, total_charge, balance, last_daily_date, last_usage),
            )
            self.connect.commit()
        except BaseException as e:
            logging.debug(f"年度统计数据更新失败：{e}")

    def _upsert_monthly_stats(self, user_id, month, month_usage, month_charge):
        if self.connect is None:
            logging.error("数据库连接尚未建立，无法更新月度统计数据。")
            return
        try:
            cursor = self.connect.cursor()
            try:
                parts = re.findall(r"\d+", str(month))
                if len(parts) < 2:
                    raise ValueError(f"无效的月份格式：{month}")
                year = int(parts[0])
                month_num = int(parts[1])
            except Exception:
                logging.debug(f"Month format invalid: {month}")
                return
            usage_val = float(month_usage) if month_usage is not None else None
            charge_val = float(month_charge) if month_charge is not None else None
            sql = f"""
                INSERT INTO {self.table_monthly}
                (user_id, year, month, usage, charge)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `usage` = IF(VALUES(`usage`) <> `usage`, VALUES(`usage`), `usage`),
                    `charge` = IF(VALUES(`charge`) <> `charge`, VALUES(`charge`), `charge`);
            """
            cursor.execute(sql, (user_id, year, month_num, usage_val, charge_val))
            self.connect.commit()
        except BaseException as e:
            logging.debug(f"月度统计数据更新失败：{e}")

    def _get_webdriver(self):
        if platform.system() == 'Windows':
            driver = webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager(
            url="https://msedgedriver.microsoft.com/",
            latest_release_url="https://msedgedriver.microsoft.com/LATEST_RELEASE").install()))
        else:
            firefox_options = webdriver.FirefoxOptions()
            firefox_options.add_argument('--incognito')
            firefox_options.add_argument("--start-maximized")
            firefox_options.add_argument('--headless')
            firefox_options.add_argument('--no-sandbox')
            firefox_options.add_argument('--disable-gpu')
            firefox_options.add_argument('--disable-dev-shm-usage')
            logging.info(f"打开 Firefox 浏览器。\r")
            driver = webdriver.Firefox(options=firefox_options, service=FirefoxService("/usr/bin/geckodriver"))
            driver.implicitly_wait(self.DRIVER_IMPLICITY_WAIT_TIME)
            # driver.implicitly_wait(self.DRIVER_IMPLICITY_WAIT_TIME)
        driver.get(LOGIN_URL)
        logging.info(f"打开登录页面 LOGIN_URL: {LOGIN_URL}。\r")
        return driver

    def _login(self, driver, phone_code = False):
        try:
            if not str(driver.current_url).startswith(LOGIN_URL):
                driver.get(LOGIN_URL)
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME * 3).until(EC.visibility_of_element_located((By.CLASS_NAME, "user")))
        except:
            logging.debug(f"登录失败，打开登录地址 {LOGIN_URL} 失败。")
        # 切换到账号密码登录页
        WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, 'el-loading-mask')))
        element = WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'user')))
        element.click()
        logging.info("找到元素 'user' 并点击。\r")
        self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[1]/div[1]/div[2]/span')
        # 点击同意按钮
        self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[2]/div[1]/form/div[1]/div[3]/div/span[2]')
        logging.info("已勾选服务协议同意选项。\r")
        WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "el-input__inner"))
        )
        if phone_code:
            self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[1]/div[1]/div[3]/span')
            input_elements = driver.find_elements(By.CLASS_NAME, "el-input__inner")
            input_elements[2].send_keys(self._username)
            logging.info(f"手机号验证码登录，输入手机号：{self._username}\r")
            self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[2]/div[2]/form/div[1]/div[2]/div[2]/div/a')
            code = input("请输入手机短信验证码: ")
            input_elements[3].send_keys(code)
            logging.info(f"已输入短信验证码: {code}。\r")
            # 点击登录按钮
            self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[2]/div[2]/form/div[2]/div/button/span')
            time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT*2)
            logging.info("点击登录按钮。\r")

            return True
        else :
            # 输入用户名和密码
            input_elements = driver.find_elements(By.CLASS_NAME, "el-input__inner")
            input_elements[0].send_keys(self._username)
            logging.info(f"输入用户名（手机号）：{self._username}\r")
            input_elements[1].send_keys(self._password)
            logging.info(f"输入密码：{self._password}\r")

            # 点击登录按钮
            self._click_button(driver, By.CLASS_NAME, "el-button.el-button--primary")
            time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT*2)
            logging.info("点击登录按钮。\r")
            # ddddOCR 有时会识别失败，这里增加重试逻辑
            for retry_times in range(1, self.RETRY_TIMES_LIMIT + 1):
                
                self._click_button(driver, By.XPATH, '//*[@id="login_box"]/div[1]/div[1]/div[2]/span')
                # 获取滑块背景图
                background_JS = 'return document.getElementById("slideVerify").childNodes[0].toDataURL("image/png");'
                # targe_JS = 'return document.getElementsByClassName("slide-verify-block")[0].toDataURL("image/png");'
                # 获取 base64 图片数据
                im_info = driver.execute_script(background_JS) 
                background = im_info.split(',')[1]  
                background_image = base64_to_PLI(background)
                logging.info(f"获取电力滑块验证码背景图成功。\r")
                distance = self.onnx.get_distance(background_image)
                logging.info(f"滑块验证码计算得到的位移距离为 {distance}。\r")

                self._sliding_track(driver, round(distance*1.06)) #1.06 是补偿系数
                time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
                if (driver.current_url == LOGIN_URL): # 如果仍然停留在登录页则视为失败
                    try:
                        logging.info(f"滑块验证码校验失败，正在重新加载。\r")
                        self._click_button(driver, By.CLASS_NAME, "el-button.el-button--primary")
                        time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT*2)
                        continue
                    except:
                        logging.debug(
                            f"登录失败，可能由于验证码无效，剩余重试次数 {self.RETRY_TIMES_LIMIT - retry_times} 次。")
                else:
                    return True
            logging.error(f"登录失败，滑块验证码多次识别失败。")
        return False

        raise Exception(
            "登录失败，可能原因：1）手机号码或密码错误，请检查；2）网络不稳定，请调整 .env 中的 LOGIN_EXPECTED_TIME 后重新运行 docker compose up --build。")
        
    def fetch(self):

        """主逻辑入口"""

        driver = self._get_webdriver()
        
        driver.maximize_window()
        logging.info("浏览器驱动初始化完成。")
        
        try:
            if os.getenv("DEBUG_MODE", "false").lower() == "true":
                if self._login(driver,phone_code=True):
                    logging.info("登录成功（手机验证码方式）。")
                else:
                    logging.info("登录失败（手机验证码方式）。")
                    raise Exception("login unsuccessed")
            else:
                if self._login(driver):
                    logging.info("登录成功。")
                else:
                    logging.info("登录失败。")
                    raise Exception("login unsuccessed")
        except Exception as e:
            logging.error(
                f"浏览器异常退出，原因：{e}。剩余重试次数 {self.RETRY_TIMES_LIMIT} 次。")
            driver.quit()
            return

        logging.info(f"在 {LOGIN_URL} 登录成功。")
        logging.info(f"开始获取用户编号列表。")
        user_id_list = self._get_user_ids(driver)
        logging.info(f"共获取到 {len(user_id_list)} 个用户编号：{user_id_list}，其中 {self.IGNORE_USER_ID} 将被忽略。")


        for userid_index, user_id in enumerate(user_id_list):           
            try: 
                # 切换到电费余额页面
                driver.get(BALANCE_URL) 
                self._choose_current_userid(driver,userid_index)
                current_userid = self._get_current_userid(driver)
                if current_userid in self.IGNORE_USER_ID:
                    logging.info(f"用户编号 {current_userid} 在忽略列表中，本次跳过。")
                    continue
                else:
                    balance, last_daily_date, last_daily_usage, yearly_charge, yearly_usage, month_charge, month_usage = self._get_all_data(driver, user_id, userid_index)
            except Exception as e:
                if (userid_index != len(user_id_list)):
                    logging.info(f"当前用户 {user_id} 的数据抓取失败：{e}，将继续抓取下一个用户。")
                else:
                    logging.info(f"用户 {user_id} 的数据抓取失败：{e}")
                    logging.info("本次数据抓取结束，浏览器将退出。")
                continue    

        driver.quit()


    def _get_current_userid(self, driver):
        current_userid = driver.find_element(By.XPATH, '//*[@id="app"]/div/div/article/div/div/div[2]/div/div/div[1]/div[2]/div/div/div/div[2]/div/div[1]/div/ul/div/li[1]/span[2]').text
        return current_userid
    
    def _choose_current_userid(self, driver, userid_index):
        elements = driver.find_elements(By.CLASS_NAME, "button_confirm")
        if elements:
            self._click_button(driver, By.XPATH, f'''//*[@id="app"]/div/div[2]/div/div/div/div[2]/div[2]/div/button''')
        self._click_button(driver, By.CLASS_NAME, "el-input__suffix")
        self._click_button(driver, By.XPATH, f"/html/body/div[2]/div[1]/div[1]/ul/li[{userid_index+1}]/span")
        

    def _get_all_data(self, driver, user_id, userid_index):
        balance = self._get_electric_balance(driver)
        if (balance is None):
            logging.info(f"Get electricity charge balance for {user_id} failed, Pass.")
        else:
            logging.info(
                f"Get electricity charge balance for {user_id} successfully, balance is {balance} CNY.")
        #time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
        # swithc to electricity usage page
        driver.get(ELECTRIC_USAGE_URL)
        self._choose_current_userid(driver, userid_index)
        # get data for each user id
        yearly_usage, yearly_charge = self._get_yearly_data(driver)

        if yearly_usage is None:
            logging.error(f"Get year power usage for {user_id} failed, pass")
        else:
            logging.info(
                f"Get year power usage for {user_id} successfully, usage is {yearly_usage} kwh")
        if yearly_charge is None:
            logging.error(f"Get year power charge for {user_id} failed, pass")
        else:
            logging.info(
                f"Get year power charge for {user_id} successfully, yealrly charge is {yearly_charge} CNY")

        # 按月获取数据
        month, month_usage, month_charge = self._get_month_usage(driver)
        if month is None:
            logging.error(f"Get month power usage for {user_id} failed, pass")
        else:
            for m in range(len(month)):
                logging.info(f"Get month power charge for {user_id} successfully, {month[m]} usage is {month_usage[m]} KWh, charge is {month_charge[m]} CNY.")
        # get yesterday usage
        last_daily_date, last_daily_usage = self._get_yesterday_usage(driver)
        if last_daily_usage is None:
            logging.error(f"Get daily power consumption for {user_id} failed, pass")
        else:
            logging.info(
                f"Get daily power consumption for {user_id} successfully, , {last_daily_date} usage is {last_daily_usage} kwh.")
        if month is None:
            logging.error(f"Get month power usage for {user_id} failed, pass")

        # 新增储存用电量
        if self.enable_database_storage:
            # 将数据存储到数据库
            logging.info("已启用数据库存储，将抓取日用电数据并写入数据库。")
            # 按天获取数据，自动判断获取 7 天还是 30 天
            date, usages = self._get_daily_usage_data(driver, user_id)
            self._save_user_data(user_id, balance, last_daily_date, last_daily_usage, date, usages, month, month_usage, month_charge, yearly_charge, yearly_usage)
        else:
            logging.info("enable_database_storage is false, we will not store the data to the database.")

        
        if month_charge:
            month_charge = month_charge[-1]
        else:
            month_charge = None
        if month_usage:
            month_usage = month_usage[-1]
        else:
            month_usage = None

        return balance, last_daily_date, last_daily_usage, yearly_charge, yearly_usage, month_charge, month_usage

    def _get_user_ids(self, driver):
        try:
            # 刷新网页
            driver.refresh()
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME * 2).until(
                EC.presence_of_element_located((By.CLASS_NAME, 'el-dropdown'))
            )
            # 点击下拉按钮以展开用户编号列表
            self._click_button(driver, By.XPATH, "//div[@class='el-dropdown']/span")
            logging.debug(f'''点击下拉按钮：self._click_button(driver, By.XPATH, "//div[@class='el-dropdown']/span")''')
            # 等待下拉菜单展示
            target = WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
                lambda d: d.find_element(By.CLASS_NAME, "el-dropdown-menu.el-popper").find_element(By.TAG_NAME, "li")
            )
            logging.debug(f'''获取下拉菜单中的第一个条目：target = driver.find_element(By.CLASS_NAME, "el-dropdown-menu.el-popper").find_element(By.TAG_NAME, "li")''')
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(target))
            logging.debug(f'''等待下拉菜单元素可见：WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(target))''')
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(
                EC.text_to_be_present_in_element((By.XPATH, "//ul[@class='el-dropdown-menu el-popper']/li"), ":"))

            # 逐个获取用户编号
            userid_elements = driver.find_element(By.CLASS_NAME, "el-dropdown-menu.el-popper").find_elements(By.TAG_NAME, "li")
            userid_list = []
            for element in userid_elements:
                userid_list.append(re.findall("[0-9]+", element.text)[-1])
            return userid_list
        except Exception as e:
            logging.error(
                f"浏览器异常退出，原因：{e}，获取用户编号列表失败。")
            driver.quit()

    def _get_electric_balance(self, driver):
        try:
            balance = driver.find_element(By.CLASS_NAME, "num").text
            balance_text = driver.find_element(By.CLASS_NAME, "amttxt").text
            if "欠费" in balance_text :
                return -float(balance)
            else:
                return float(balance)
        except:
            return None

    def _get_yearly_data(self, driver):

        try:
            if datetime.now().month == 1:
                self._click_button(driver, By.XPATH, '//*[@id="pane-first"]/div[1]/div/div[1]/div/div/input')
                time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
                span_element = driver.find_element(By.XPATH, f"//span[text() = '{datetime.now().year - 1}']")
                span_element.click()
                time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
            self._click_button(driver, By.XPATH, "//div[@class='el-tabs__nav is-top']/div[@id='tab-first']")
            time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
            # wait for data displayed
            target = driver.find_element(By.CLASS_NAME, "total")
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(target))
        except Exception as e:
            logging.error(f"The yearly data get failed : {e}")
            return None, None

        # get data
        try:
            yearly_usage = driver.find_element(By.XPATH, "//ul[@class='total']/li[1]/span").text
        except Exception as e:
            logging.error(f"The yearly_usage data get failed : {e}")
            yearly_usage = None

        try:
            yearly_charge = driver.find_element(By.XPATH, "//ul[@class='total']/li[2]/span").text
        except Exception as e:
            logging.error(f"The yearly_charge data get failed : {e}")
            yearly_charge = None

        return yearly_usage, yearly_charge

    def _get_yesterday_usage(self, driver):
        """获取最近一次用电量"""
        try:
            # 点击日用电量
            self._click_button(driver, By.XPATH, "//div[@class='el-tabs__nav is-top']/div[@id='tab-second']")
            time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
            # wait for data displayed
            usage_element = driver.find_element(By.XPATH,
                                                "//div[@class='el-tab-pane dayd']//div[@class='el-table__body-wrapper is-scrolling-none']/table/tbody/tr[1]/td[2]/div")
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(usage_element)) # 等待用电量出现

            # 增加是哪一天
            date_element = driver.find_element(By.XPATH,
                                                "//div[@class='el-tab-pane dayd']//div[@class='el-table__body-wrapper is-scrolling-none']/table/tbody/tr[1]/td[1]/div")
            last_daily_date = date_element.text # 获取最近一次用电量的日期
            return last_daily_date, float(usage_element.text)
        except Exception as e:
            logging.error(f"获取最近一次日用电数据失败：{e}")
            return None, None

    def _get_month_usage(self, driver):
        """获取每月用电量"""

        try:
            self._click_button(driver, By.XPATH, "//div[@class='el-tabs__nav is-top']/div[@id='tab-first']")
            time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
            if datetime.now().month == 1:
                self._click_button(driver, By.XPATH, '//*[@id="pane-first"]/div[1]/div/div[1]/div/div/input')
                time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
                span_element = driver.find_element(By.XPATH, f"//span[text() = '{datetime.now().year - 1}']")
                span_element.click()
                time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)
            # 等待月份数据展示
            target = driver.find_element(By.CLASS_NAME, "total")
            WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(target))
            month_element = driver.find_element(By.XPATH, "//*[@id='pane-first']/div[1]/div[2]/div[2]/div/div[3]/table/tbody").text
            month_element = month_element.split("\n")
            month_element.remove("MAX")
            month_element = np.array(month_element[:-(len(month_element) % 3)]).reshape(-1, 3)
            # 将每月的用电量保存为列表
            month = []
            usage = []
            charge = []
            for i in range(len(month_element)):
                month.append(month_element[i][0])
                usage.append(month_element[i][1])
                charge.append(month_element[i][2])
            return month, usage, charge
        except Exception as e:
            logging.error(f"获取月度用电数据失败：{e}")
            return None,None,None

    # 增加获取每日用电量的函数
    def _get_daily_usage_data(self, driver, user_id):
        """储存指定天数的用电量（自动根据数据库是否已完整保存最近 30 天数据来决定取 7 天还是 30 天）"""
        try:
            retention_days = int(os.getenv("DATA_RETENTION_DAYS", 30))  # 默认配置为 30 天
        except Exception:
            retention_days = 30

        if self.enable_database_storage:
            try:
                if self.connect is None:
                    self.connect_user_db(user_id)
                if self._has_recent_30_days(user_id):
                    retention_days = 7
            except Exception as e:
                logging.debug(f"根据数据库记录判断保留天数失败，退回环境配置：{e}")

        self._click_button(driver, By.XPATH, "//div[@class='el-tabs__nav is-top']/div[@id='tab-second']")
        time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)

        # 7 天在第一个选项，开通智能缴费后 30 天 出现在第二个选项
        if retention_days == 7:
            self._click_button(driver, By.XPATH, "//*[@id='pane-second']/div[1]/div/label[1]/span[1]")
        elif retention_days == 30:
            self._click_button(driver, By.XPATH, "//*[@id='pane-second']/div[1]/div/label[2]/span[1]")
        else:
            logging.error(f"不支持的保留天数配置：{retention_days}")
            return

        time.sleep(self.RETRY_WAIT_TIME_OFFSET_UNIT)

        # 等待用电量的数据出现
        usage_element = driver.find_element(By.XPATH,
                                            "//div[@class='el-tab-pane dayd']//div[@class='el-table__body-wrapper is-scrolling-none']/table/tbody/tr[1]/td[2]/div")
        WebDriverWait(driver, self.DRIVER_IMPLICITY_WAIT_TIME).until(EC.visibility_of(usage_element))

        # 获取用电量的数据
        days_element = driver.find_elements(By.XPATH,
                                            "//*[@id='pane-second']/div[2]/div[2]/div[1]/div[3]/table/tbody/tr")  # 用电量值列表
        date = []
        usages = []
        # 将用电量保存为列表
        for i in days_element:
            day = i.find_element(By.XPATH, "td[1]/div").text
            usage = i.find_element(By.XPATH, "td[2]/div").text
            if usage != "":
                usages.append(usage)
                date.append(day)
            else:
                logging.info(f"{day} 的用电量为空，跳过该条记录。")
        return date, usages

    def _save_user_data(self, user_id, balance, last_daily_date, last_daily_usage, date, usages, month, month_usage, month_charge, yearly_charge, yearly_usage):
        # 连接数据库集合
        if self.connect is None:
            if not self.connect_user_db(user_id):
                logging.info("数据库创建失败，用户数据未正确写入。")
                return
        self._upsert_yearly_stats(user_id, balance, last_daily_date, last_daily_usage, yearly_usage, yearly_charge)

        if date: 
            for index in range(len(date)):
                dic = {'date': date[index], 'usage': float(usages[index]), 'user_id': user_id}
                try:
                    self.insert_data(dic)
                    logging.info(f"{date[index]} 的用电量 {usages[index]} KWh 已成功写入数据库。")
                except Exception as e:
                    logging.debug(f"{date[index]} 的用电量写入数据库失败，可能记录已存在：{str(e)}")
        if month: 
            for index in range(len(month)):
                try:
                    self._upsert_monthly_stats(user_id, month[index], month_usage[index], month_charge[index])
                except Exception as e:
                    logging.debug(f"{month[index]} 的月度用电数据写入数据库失败，可能记录已存在：{str(e)}")
        self.connect.close()
        self.connect = None

if __name__ == "__main__":
    with open("bg.jpg", "rb") as f:
        test1 = f.read()
        print(type(test1))
        print(test1)
