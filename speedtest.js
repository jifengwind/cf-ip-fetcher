const fs = require('fs');
const https = require('https');

// ==================== 配置区 ====================
const TOP_COUNT = 40;                // 最终选取的IP数量
const PORT = 443;                   // 目标端口
const MAX_LATENCY = 300;            // 最大延迟 (ms)
const MIN_SPEED = 5;                // 最低速度 (mb/s)

// 数据源
const IP_SOURCES = [
    {
        name: 'api.uouin.com',
        url: 'https://api.uouin.com/cloudflare.html',
        type: 'html'  // HTML 表格类型
    },
    {
        name: 'ip.164746.xyz',
        url: 'https://ip.164746.xyz',
        type: 'text'  // 纯文本类型，用正则提取
    },
    {
        name: 'wetest.vip',
        url: 'https://www.wetest.vip/page/cloudflare/address_v4.html',
        type: 'text'
    }
];
// =================================================

// 运营商识别（基于 IP 段经验）
function detectISP(ip) {
    if (!ip) return '多线';
    
    const parts = ip.split('.');
    const firstOctet = parts[0];
    const secondOctet = parts[1];
    
    if (firstOctet === '104') {
        if (['16', '18', '19', '28'].includes(secondOctet)) return '移动';
        if (['20', '22', '26', '31'].includes(secondOctet)) return '电信';
        if (['23', '31'].includes(secondOctet)) return '联通';
    }
    
    if (firstOctet === '162' && secondOctet === '159') return '电信';
    if (firstOctet === '172') {
        if (['64', '67'].includes(secondOctet)) return '联通';
        if (['68', '69', '70'].includes(secondOctet)) return '移动';
    }
    
    return '多线';
}

// 从 api.uouin.com 的 HTML 表格中解析数据
async function fetchFromApiUouin() {
    console.log('正在获取: api.uouin.com (表格解析模式)');
    
    return new Promise((resolve) => {
        const url = 'https://api.uouin.com/cloudflare.html';
        
        const options = {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        };
        
        https.get(url, options, (res) => {
            let html = '';
            res.on('data', chunk => html += chunk);
            res.on('end', () => {
                const candidates = [];
                const seenIPs = new Set();
                
                // 宽松正则：匹配每个 <tr> 内的前6个 <td> 内容
                const rowPattern = /<tr>[\s\S]*?<td>(\d+)<\/td>[\s\S]*?<td>([^<]+)<\/td>[\s\S]*?<td>([^<]+)<\/td>[\s\S]*?<td>([^<]+)<\/td>[\s\S]*?<td>([^<]+)<\/td>[\s\S]*?<td>([^<]+)<\/td>[\s\S]*?<\/tr>/gi;
                
                let match;
                while ((match = rowPattern.exec(html)) !== null) {
                    const lineType = match[2].trim();      // 线路类型
                    const ip = match[3].trim();            // IP 地址
                    const lossText = match[4].trim();      // 丢包率
                    const latencyText = match[5].trim();   // 延迟
                    const speedText = match[6].trim();     // 速度
                    
                    // 跳过 IPv6
                    if (ip.includes(':')) continue;
                    
                    // 解析数值
                    const loss = parseFloat(lossText.replace('%', '')) || 0;
                    const latency = parseFloat(latencyText.replace('ms', '')) || 999;
                    const speed = parseFloat(speedText.replace('mb/s', '').replace('MB/s', '')) || 0;
                    
                    // 筛选条件
                    if (loss > 0) continue;
                    if (latency > MAX_LATENCY) continue;
                    if (speed < MIN_SPEED) continue;
                    if (seenIPs.has(ip)) continue;
                    
                    seenIPs.add(ip);
                    
                    // 优先使用页面标注的线路类型
                    const isp = (lineType !== 'IPV6' && lineType !== '多线') ? lineType : detectISP(ip);
                    
                    candidates.push({
                        ip: ip,
                        latency: latency,
                        speed: speed,
                        isp: isp,
                        score: 0
                    });
                }
                
                console.log(`  成功解析 ${candidates.length} 个符合条件的 IP`);
                resolve(candidates);
            });
        }).on('error', (err) => {
            console.log(`  获取失败: ${err.message}`);
            resolve([]);
        });
    });
}

// 从纯文本页面提取 IP（原有逻辑）
async function fetchFromTextSource(source) {
    console.log(`正在获取: ${source.name}`);
    
    return new Promise((resolve) => {
        const options = {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        };
        
        https.get(source.url, options, (res) => {
            let text = '';
            res.on('data', chunk => text += chunk);
            res.on('end', () => {
                const ipPattern = /(\d{1,3}(?:\.\d{1,3}){3})/g;
                const ips = [];
                const seen = new Set();
                
                let match;
                while ((match = ipPattern.exec(text)) !== null) {
                    const ip = match[1];
                    if (!seen.has(ip) && isValidPublicIP(ip)) {
                        seen.add(ip);
                        ips.push({
                            ip: ip,
                            latency: 999,
                            speed: 0,
                            isp: detectISP(ip),
                            score: 0
                        });
                    }
                }
                
                console.log(`  成功提取 ${ips.length} 个 IP`);
                resolve(ips);
            });
        }).on('error', (err) => {
            console.log(`  获取失败: ${err.message}`);
            resolve([]);
        });
    });
}

// 验证公网 IPv4
function isValidPublicIP(ip) {
    const parts = ip.split('.').map(Number);
    if (parts.length !== 4) return false;
    if (parts.some(n => isNaN(n) || n < 0 || n > 255)) return false;
    
    // 排除私网/保留地址
    if (parts[0] === 0 || parts[0] === 10 || parts[0] === 127) return false;
    if (parts[0] === 169 && parts[1] === 254) return false;
    if (parts[0] === 192 && parts[1] === 168) return false;
    if (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) return false;
    if (parts[0] >= 224) return false;
    
    return true;
}

// 计算综合得分并排序
function sortByScore(candidates) {
    if (candidates.length === 0) return [];
    
    // 对于没有延迟/速度数据的源，只按 ISP 分组排序
    const validLatency = candidates.filter(c => c.latency < 999);
    const validSpeed = candidates.filter(c => c.speed > 0);
    
    if (validLatency.length === 0 || validSpeed.length === 0) {
        // 数据不足时，按运营商和 IP 稳定排序
        return candidates.sort((a, b) => {
            if (a.isp !== b.isp) return a.isp.localeCompare(b.isp);
            return a.ip.localeCompare(b.ip);
        });
    }
    
    const maxLatency = Math.max(...validLatency.map(c => c.latency));
    const maxSpeed = Math.max(...validSpeed.map(c => c.speed));
    
    candidates.forEach(c => {
        if (c.latency < 999 && c.speed > 0) {
            const latencyScore = 1 - (c.latency / maxLatency);
            const speedScore = c.speed / maxSpeed;
            c.score = 0.5 * latencyScore + 0.5 * speedScore;
        } else {
            c.score = 0;
        }
    });
    
    return candidates.sort((a, b) => b.score - a.score);
}

// 主函数
async function main() {
    console.log('开始聚合 Cloudflare 优选 IP...\n');
    
    const allCandidates = [];
    
    // 先抓取 api.uouin.com（有完整延迟/速度数据）
    const apiData = await fetchFromApiUouin();
    allCandidates.push(...apiData);
    
    // 再抓取其他纯文本源
    for (const source of IP_SOURCES) {
        if (source.name === 'api.uouin.com') continue; // 已处理
        
        const candidates = await fetchFromTextSource(source);
        allCandidates.push(...candidates);
    }
    
    // 按 IP 去重（保留延迟/速度数据更好的那个）
    const ipMap = new Map();
    allCandidates.forEach(c => {
        const existing = ipMap.get(c.ip);
        if (!existing || c.score > existing.score) {
            ipMap.set(c.ip, c);
        }
    });
    
    let candidates = Array.from(ipMap.values());
    console.log(`\n去重后共 ${candidates.length} 个候选 IP`);
    
    if (candidates.length === 0) {
        console.log('警告：未找到任何可用 IP');
        process.exit(1);
    }
    
    // 按得分排序
    candidates = sortByScore(candidates);
    
    // 取前 TOP_COUNT 个
    const finalIPs = candidates.slice(0, TOP_COUNT);
    
    // 生成输出
    const lines = finalIPs.map(c => `${c.ip}:${PORT}#${c.isp}`);
    
    fs.writeFileSync('ips.txt', lines.join('\n'));
    fs.writeFileSync('last-update.txt', new Date().toISOString());
    
    console.log(`\n✅ 已生成 ${finalIPs.length} 个 IP，格式：IP:${PORT}#运营商`);
    console.log('📁 文件已写入: ips.txt');
    
    // 统计运营商分布
    const stats = {};
    finalIPs.forEach(c => {
        stats[c.isp] = (stats[c.isp] || 0) + 1;
    });
    
    console.log('\n📊 运营商分布:');
    Object.entries(stats).sort((a, b) => b[1] - a[1]).forEach(([isp, count]) => {
        console.log(`   ${isp}: ${count}`);
    });
    
    console.log('\n📋 前10个 IP 预览:');
    finalIPs.slice(0, 10).forEach((c, i) => {
        const scoreInfo = c.score > 0 ? `得分: ${c.score.toFixed(3)}` : '无延迟数据';
        const latencyInfo = c.latency < 999 ? `${c.latency}ms` : '无数据';
        const speedInfo = c.speed > 0 ? `${c.speed.toFixed(1)}mb/s` : '无数据';
        console.log(`   ${i + 1}. ${c.ip}:${PORT}#${c.isp} (延迟: ${latencyInfo}, 速度: ${speedInfo}, ${scoreInfo})`);
    });
    
    console.log('\n⏰ 更新时间:', new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }));
}

main().catch(err => {
    console.error('❌ 执行失败:', err.message);
    process.exit(1);
});
