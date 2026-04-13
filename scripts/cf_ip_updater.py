#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare 优选 IP 抓取脚本（Selenium 版本）
适配 GitHub Actions 环境
"""

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
    
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_argument('--log-level=3')
    
    service = Service('/usr/local/bin/chromedriver')
    return webdriver.Chrome(service=service, options=options)


def fetch_table_data():
    """从目标网页抓取表格数据"""
    driver = create_driver()
    try:
        log(f"正在加载页面: {URL}")
        driver.get(URL)
        
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        time.sleep(3)
        
        table = driver.find_element(By.TAG_NAME, "table")
        rows = table.find_elements(By.TAG_NAME, "tr")
        
        log(f"总共找到 {len(rows)} 行")
        
        candidates = []
        seen_ips = set()
        first_valid_row = True
        
        for row in rows[1:]:  # 跳过表头
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                
                # 数据行实际是 8 列（缺少序号列）
                # 列顺序: 0:线路, 1:IP, 2:丢包, 3:延迟, 4:速度, 5:带宽, 6:Colo, 7:时间
                if len(cells) < 8:
                    continue
                
                line_type = cells[0].text.strip()
                ip = cells[1].text.strip()
                loss_text = cells[2].text.strip()
                latency_text = cells[3].text.strip()
                speed_text = cells[4].text.strip()
                
                # 跳过 IPv6
                if ':' in ip:
                    continue
                
                # 跳过空 IP
                if not ip or ip == '':
                    continue
                
                # 验证是否为有效 IP 格式
                if not any(c.isdigit() for c in ip):
                    continue
                
                # 解析延迟
                try:
                    latency = float(latency_text.replace('ms', '').strip())
                except:
                    latency = 999
                
                # 解析速度
                try:
                    speed = float(speed_text.lower().replace('mb/s', '').replace('mb', '').strip())
                except:
                    speed = 0
                
                # 第一行调试
                if first_valid_row:
                    log(f"调试：第一行数据 - 线路:'{line_type}', IP:'{ip}', 延迟:'{latency_text}'->{latency}, 速度:'{speed_text}'->{speed}")
                    first_valid_row = False
                
                # 筛选条件
                if latency > MAX_LATENCY:
                    continue
                if speed < MIN_SPEED:
                    continue
                if ip in seen_ips:
                    continue
                
                seen_ips.add(ip)
                
                # 线路类型处理
                isp = line_type if line_type not in ['IPV6', ''] else '多线'
                
                candidates.append({
                    'ip': ip,
                    'latency': latency,
                    'speed': speed,
                    'isp': isp
                })
                
            except Exception as e:
                continue
        
        log(f"最终筛选出 {len(candidates)} 个候选 IP")
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
    log(f"筛选条件: 延迟 ≤ {MAX_LATENCY}ms, 速度 ≥ {MIN_SPEED}mb/s")
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
    
    top_ips = sort_by_score(candidates)[:MAX_RESULTS]
    
    lines = []
    for c in top_ips:
        line = f"{c['ip']}:{TARGET_PORT}#{c['isp']}"
        lines.append(line)
        log(f"📌 {c['ip']:15} [{c['isp']:6}] 延迟: {c['latency']:6.1f}ms  速度: {c['speed']:6.1f}mb/s  得分: {c['score']:.3f}")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines))
    
    log("=" * 50)
    log(f"🎉 成功！已将 {len(lines)} 个 IP 写入 {OUTPUT_FILE}")
    log("=" * 50)


if __name__ == "__main__":
    main()
