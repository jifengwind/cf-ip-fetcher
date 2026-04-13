#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare 优选 IP 抓取脚本（Selenium 版本）
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
OUTPUT_FILE = "output/cf_preferred_ips.txt"
TARGET_PORT = "443"
MAX_RESULTS = 40
MAX_LATENCY = 300   # 最大延迟 300ms
MIN_SPEED = 5       # 最低速度 5mb/s


def log(msg):
    """带时间戳的日志输出"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)


def create_driver():
    """创建并配置 Chrome 驱动（适配 GitHub Actions 环境）"""
    options = Options()
    
    # GitHub Actions 必需参数
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
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
                if len(cols) < 6:
                    continue
                
                # 解析各列数据
                # 表格结构：序号 | 线路 | IP | 丢包 | 延迟 | 速度 | 带宽 | Colo | 时间
                line_type = cols[1].text.strip()      # 线路类型
                ip = cols[2].text.strip()             # IP 地址
                loss_text = cols[3].text.strip()      # 丢包率
                latency_text = cols[4].text.strip()   # 延迟
                speed_text = cols[5].text.strip()     # 速度
                
                # 跳过 IPv6
                if ':' in ip:
                    continue
                
                # 解析数值
                try:
                    loss = float(loss_text.replace('%', ''))
                except:
                    loss = 100
                
                try:
                    latency = float(latency_text.replace('ms', ''))
                except:
                    latency = 999
                
                try:
                    speed = float(speed_text.replace('mb/s', '').replace('MB/s', ''))
                except:
                    speed = 0
                
                # 筛选条件
                if loss > 0:
                    continue
                if latency > MAX_LATENCY:
                    continue
                if speed < MIN_SPEED:
                    continue
                if ip in seen_ips:
                    continue
                
                seen_ips.add(ip)
                
                # 使用页面标注的线路类型
                isp = line_type if line_type not in ['IPV6', '多线'] else '多线'
                
                candidates.append({
                    'ip': ip,
                    'latency': latency,
                    'speed': speed,
                    'isp': isp
                })
                
            except Exception as e:
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
        latency_score = 1 - (c['latency'] / max_lat) if max_lat > 0 else 0
        speed_score = c['speed'] / max_spd if max_spd > 0 else 0
        c['score'] = 0.5 * latency_score + 0.5 * speed_score
    
    return sorted(candidates, key=lambda x: -x['score'])


def main():
    log("=" * 50)
    log("开始获取 Cloudflare 优选 IP（GitHub Actions + Selenium）")
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
        log(f"📌 {c['ip']:15} [{c['isp']:6}] 延迟: {c['latency']:6.1f}ms  速度: {c['speed']:6.1f}mb/s  得分: {c['score']:.3f}")
    
    # 写入文件
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines))
    
    log("=" * 50)
    log(f"🎉 成功！已将 {len(lines)} 个 IP 写入 {OUTPUT_FILE}")
    log("=" * 50)


if __name__ == "__main__":
    main()
