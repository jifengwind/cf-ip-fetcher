#!/usr/bin/env python3
import json
import sys
import subprocess

def get_chrome_version():
    result = subprocess.run(['google-chrome', '--version'], capture_output=True, text=True)
    version = result.stdout.strip().split()[-1]
    print(f"Chrome version: {version}")
    return version

def get_chromedriver_url(chrome_version):
    chrome_major = chrome_version.split('.')[0]
    
    # 先尝试精确匹配
    import urllib.request
    with urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json') as f:
        data = json.load(f)
    
    builds = data['builds']
    for build, info in builds.items():
        if info['version'] == chrome_version:
            for d in info['downloads']['chromedriver']:
                if d['platform'] == 'linux64':
                    return d['url']
    
    # 精确匹配失败，尝试主版本匹配
    with urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/latest-versions-per-milestone-with-downloads.json') as f:
        data = json.load(f)
    
    milestones = data['milestones']
    if chrome_major in milestones:
        for d in milestones[chrome_major]['downloads']['chromedriver']:
            if d['platform'] == 'linux64':
                return d['url']
    
    raise Exception(f"Could not find ChromeDriver for Chrome {chrome_version}")

if __name__ == '__main__':
    chrome_version = get_chrome_version()
    url = get_chromedriver_url(chrome_version)
    print(url)
