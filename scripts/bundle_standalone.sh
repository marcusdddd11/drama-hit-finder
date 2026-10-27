#!/usr/bin/env bash
# 把 web/ 打包成单个自包含 HTML 文件：数据 + 清洗逻辑全部内联
# 产物：dist/海外短剧爆款筛选.html  —— 可直接发给别人，双击打开即用，不依赖服务器
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p dist
IN="web/index.html"
OUT="dist/DramaHitFinder.html"

# 兼容本地 macOS（managed python）与 GitHub Actions（ubuntu 自带 python3）
PYBIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

"$PYBIN" - "$IN" "$OUT" <<'PY'
import sys, os, re, io

src_path, out_path = sys.argv[1], sys.argv[2]
html = io.open(src_path, encoding='utf-8').read()

def inline(src_tag):
    """把 <script src="xxx.js"></script> 换成内联脚本"""
    global html
    m = re.search(r'<script src="([^"]+\.js)"></script>', html)
    if not m:
        return None
    fname = m.group(1)
    fpath = os.path.join(os.path.dirname(src_path), fname)
    code = io.open(fpath, encoding='utf-8').read()
    # 防转义：脚本内容里若出现 </script 会提前闭合标签
    assert '</script' not in code.lower(), f'{fname} 含 </script 字面量，需转义'
    html = html.replace(m.group(0), '<script>\n' + code + '\n</script>')
    return fname

n = 0
while inline(None) is not None:
    n += 1
    if n > 10:
        raise SystemExit('内联次数异常，检查递归')

assert '<script src=' not in html, '仍有未内联的外部脚本: ' + str(re.findall(r'<script src=[^>]*>', html))

with io.open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

size = os.path.getsize(out_path)
print(f'[bundle] 已内联 {n} 个脚本 -> {out_path}')
print(f'[bundle] 单文件大小: {size/1024/1024:.2f} MB')
PY

echo "[bundle] 完成: $OUT"

# 卡片 HTML 结构自检：div/span 标签必须开闭平衡，否则页面会嵌套错位
# （2026-10-26 踩过：main 容器少一个 </div>，5545 张卡片层层嵌套全崩）
"$PYBIN" - "$IN" <<'PY'
import sys, re, io
html = io.open(sys.argv[1], encoding='utf-8').read()
scripts = re.findall(r'<script>([\s\S]*?)</script>', html)
inline_js = scripts[-1] if scripts else ''
# 找 card 函数里的模板串做静态抽查：确保 '</div></div>' 收尾存在
if 'function card' in inline_js:
    m = re.search(r"function card[\s\S]*?return h;", inline_js)
    body = m.group(0) if m else ''
    opens = len(re.findall(r"h \+= '<div", body)) + len(re.findall(r"h='<div", body))
    closes = len(re.findall(r'</div>', body))
    # 每个开标签都应有对应闭标签（同行闭合的也算在 </div> 计数里）
    if opens > closes:
        raise SystemExit(f'[check] card() 开 div {opens} > 闭 {closes}，结构不平衡，禁止发布！')
print('[check] card() 标签平衡 OK')
PY
