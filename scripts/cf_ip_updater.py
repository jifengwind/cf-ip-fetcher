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
    options.add_argument('--silent')
    
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
        
        # 分析表头，确定各列的位置
        header_row = rows[0]
        header_cells = header_row.find_elements(By.TAG_NAME, "th")
        if not header_cells:
            header_cells = header_row.find_elements(By.TAG_NAME, "td")
        
        # 打印表头，用于调试
        header_texts = [cell.text.strip() for cell in header_cells]
        log(f"表头列数: {len(header_texts)}")
        log(f"表头内容: {header_texts}")
        
        # 找出关键列的索引
        ip_idx = None
        latency_idx = None
        speed_idx = None
        isp_idx = None
        
        for i, text in enumerate(header_texts):
            if 'IP' in text or 'ip' in text:
                ip_idx = i
            elif '延迟' in text or 'latency' in text.lower():
                latency_idx = i
            elif '速度' in text or 'speed' in text.lower():
                speed_idx = i
            elif '线路' in text or 'isp' in text.lower():
                isp_idx = i
        
        # 如果没有"线路"列，则通过其他方式判断
        if isp_idx is None:
            log("未找到'线路'列，将使用 IP 段经验判断运营商")
        
        log(f"列索引: IP={ip_idx}, 延迟={latency_idx}, 速度={speed_idx}, 线路={isp_idx}")
        
        candidates = []
        seen_ips = set()
        
        for row in rows[1:]:  # 跳过表头
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < max([idx for idx in [ip_idx, latency_idx, speed_idx] if idx is not None]) + 1:
                    continue
                
                # 提取 IP
                ip = cells[ip_idx].text.strip() if ip_idx is not None else ''
                if ':' in ip or not ip:
                    continue
                
                # 提取线路（如果有）
                isp = cells[isp_idx].text.strip() if isp_idx is not None else '多线'
                
                # 提取延迟
                latency_text = cells[latency_idx].text.strip() if latency_idx is not None else ''
                try:
                    latency = float(latency_text.replace('ms', '').strip())
                except:
                    latency = 999
                
                # 提取速度
                speed_text = cells[speed_idx].text.strip() if speed_idx is not None else ''
                try:
                    speed = float(speed_text.lower().replace('mb/s', '').replace('mb', '').strip())
                except:
                    speed = 0
                
                # 调试第一行
                if len(candidates) == 0 and len(seen_ips) == 0:
                    log(f"调试：第一行解析 - IP:{ip}, 线路:{isp}, 延迟:{latency}, 速度:{speed}")
                
                # 筛选条件
                if latency > MAX_LATENCY:
                    continue
                if speed < MIN_SPEED:
                    continue
                if ip in seen_ips:
                    continue
                
                seen_ips.add(ip)
                
                candidates.append({
                    'ip': ip,
                    'latency': latency,
                    'speed': speed,
                    'isp': isp if isp not in ['IPV6', ''] else '多线'
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
