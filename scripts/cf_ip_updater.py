#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare 优选 IP 抓取脚本
适配 GitHub Actions 环境
"""

import re
import os
import sys
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 配置 ---
URL = "https://api.uouin.com/cloudflare.html"
OUTPUT_FILE = "output/cf_preferred_ips.txt"  # 相对于仓库根目录
TARGET_PORT = "443"
MAX_RESULTS = 30
MAX_LATENCY = 300  # 最大延迟 300ms
MIN_SPEED = 5      # 最低速度 5mb/s


def log(msg):
    """带时间戳的日志输出"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)


def create_driver():
    """创建并配置 Chrome 驱动（适配 GitHub Actions 环境）"""
    options = Options()
    
    # GitHub Actions 必需参数
    options.add_argument('--headless')               # 无头模式
    options.add_argument('--no-sandbox')             # 禁用沙箱（CI 环境必需）
    options.add_argument('--disable-dev-shm-usage')  # 解决内存不足问题
    options.add_argument('--disable-gpu')            # 禁用 GPU 加速
    options.add_argument('--window-size=1920,1080')  # 设置窗口大小
    
    # 反爬虫伪装
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 添加 User-Agent
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # 禁用日志输出
    options.add_argument('--log-level=3')
    options.add_argument('--silent')
    
    service = Service('/usr/local/bin/chromedriver')
    return webdriver.Chrome(service=service, options=options)


def fetch_table_data():
    """从目标网页抓取表格数据"""
    driver = create_driver()
    try:
        log(f"正在加载页面: {URL}")
        driver.get(URL)
        
        # 等待表格加载完成
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        time.sleep(3)  # 额外等待确保数据完全渲染
        
        # 获取表格所有行（跳过表头）
        table = driver.find_element(By.TAG_NAME, "table")
        rows = table.find_elements(By.TAG_NAME, "tr")[1:]
        
        candidates = []
        seen_ips = set()
        
        log(f"找到 {len(rows)} 行数据")
        
        for row in rows:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 5:
                    continue
                
                # 解析各列数据
                isp = cols[0].text.strip()
                ip = cols[1].text.strip()
                
                # 丢包率
                loss_text = cols[2].text.strip().replace('%', '')
                loss = float(loss_text) if loss_text else 100
                
                # 延迟
                lat_text = cols[3].text.strip().replace('ms', '')
                lat = float(lat_text) if lat_text else 999
                
                # 速度
                spd_text = cols[4].text.strip().replace('mb/s', '').replace('mb', '').replace('MB/s', '').replace('MB', '')
                spd = float(spd_text) if spd_text else 0
                
                # 筛选条件
                if ':' in ip:  # 跳过带端口的 IP
                    continue
                if loss > 0:
                    continue
                if lat > MAX_LATENCY:
                    continue
                if spd < MIN_SPEED:
                    continue
                if ip in seen_ips:
                    continue
                
                seen_ips.add(ip)
                candidates.append({
                    'ip': ip,
                    'latency': lat,
                    'speed': spd,
                    'isp': isp if isp else 'CF'
                })
                
            except Exception as e:
                log(f"解析行数据时出错: {e}")
                continue
        
        return candidates
        
    finally:
        driver.quit()


def sort_by_score(candidates):
    """根据综合得分排序（延迟和速度各占 50% 权重）"""
    if not candidates:
        return []
    
    max_lat = max(c['latency'] for c in candidates)
    max_spd = max(c['speed'] for c in candidates)
    
    for c in candidates:
        # 延迟越低越好，速度越高越好
        latency_score = 1 - (c['latency'] / max_lat) if max_lat > 0 else 0
        speed_score = c['speed'] / max_spd if max_spd > 0 else 0
        c['score'] = 0.5 * latency_score + 0.5 * speed_score
    
    return sorted(candidates, key=lambda x: -x['score'])


def main():
    log("=" * 50)
    log("开始获取 Cloudflare 优选 IP（GitHub Actions 环境）")
    log(f"筛选条件: 延迟 ≤ {MAX_LATENCY}ms, 速度 ≥ {MIN_SPEED}mb/s, 0% 丢包")
    log("=" * 50)
    
    try:
        candidates = fetch_table_data()
    except Exception as e:
        log(f"❌ 抓取失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    log(f"✅ 共筛选出 {len(candidates)} 个符合条件的 IP")
    
    if not candidates:
        log("⚠️ 警告：未找到符合条件的 IP")
        # 即使没有结果也创建一个空文件，避免工作流报错
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='ascii') as f:
            f.write("# No IPs found matching criteria\n")
        sys.exit(0)
    
    # 按得分排序，取前 N 个
    top_ips = sort_by_score(candidates)[:MAX_RESULTS]
    
    # 生成输出行
    lines = []
    for c in top_ips:
        line = f"{c['ip']}:{TARGET_PORT}#{c['isp']}"
        lines.append(line)
        log(f"📌 已选择 - {c['ip']:15} [{c['isp']:6}] 延迟: {c['latency']:6.1f}ms  速度: {c['speed']:6.1f}mb/s  得分: {c['score']:.3f}")
    
    # 写入文件
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines))
    
    log("=" * 50)
    log(f"🎉 成功！已将 {len(lines)} 个 IP 写入 {OUTPUT_FILE}")
    log("=" * 50)


if __name__ == "__main__":
    main()
