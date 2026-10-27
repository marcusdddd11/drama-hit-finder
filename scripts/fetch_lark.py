#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从飞书表格直接拉数据（GitHub Actions 版）——不依赖 lark-cli，只用标准库。

为什么要有这个脚本：
  lark-cli 是本地工具，依赖扫码授权的 user token，会过期，服务器上跑不了。
  Actions / Worker 这类无人值守环境必须用「飞书自建应用」的 tenant_access_token，
  凭证是 App ID + App Secret，长期有效。

用法:
  LARK_APP_ID=cli_xxx LARK_APP_SECRET=xxx python3 scripts/fetch_lark.py

输出:
  data/{reelshort,pinedrama,...}.json，格式与 lark-cli +table-get 一致：
  {"sheets":[{"data":[[表头行], [数据行], ...]}]}
  下游 build_library.py 直接消费，不用改。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, 'data')

# 已核对（2026-10-26 用 lark-cli sheets +workbook-info 实际拉到，不是猜的）
SPREADSHEET_TOKEN = 'Q3GgsvAIAhkrkCtH1JOctLJunrf'

# 数据源 = 「数据底稿」子表（全量 7079 行，剧场/语种/来源 100% 填充）。
# 7 个剧场分表（各 8206 行）不是全量 —— 合计只有 6399 有效行，去重后比底稿少 1194 部剧。
# 不要再拿分表当数据源。
SHEETS = {
    '数据底稿': '61450f',
}
# 底稿：第 1 行日期、第 2 行表头、第 3 行「参考行」占位，数据从第 4 行开始
ROW_START = 4
ROW_END = 7082
CHUNK = 2400       # 分段读取（底稿单行内容长，4000 行会被截断）
MAX_RETRY = 3

LARK_BASE = 'https://open.feishu.cn/open-apis'


def http(url, method='GET', headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    data = json.dumps(body).encode('utf-8') if body is not None else None
    last = None
    for i in range(MAX_RETRY):
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read().decode("utf-8", "replace")[:300]}'
        except Exception as e:                      # noqa: BLE001
            last = str(e)
        if i < MAX_RETRY - 1:
            time.sleep(2 ** i)
    raise RuntimeError(f'请求失败 {url} -> {last}')


def tenant_token(app_id, app_secret):
    j = http(
        f'{LARK_BASE}/auth/v3/tenant_access_token/internal',
        method='POST',
        headers={'Content-Type': 'application/json; charset=utf-8'},
        body={'app_id': app_id, 'app_secret': app_secret},
    )
    if j.get('code') != 0:
        raise RuntimeError(f'取 tenant_access_token 失败: code={j.get("code")} msg={j.get("msg")}')
    return j['tenant_access_token']


def build_ranges(sheet_id):
    out = []
    s = ROW_START
    while s <= ROW_END:
        e = min(s + CHUNK - 1, ROW_END)
        out.append(f'{sheet_id}!A{s}:P{e}')
        s = e + 1
    return out


# 权限类错误码（换什么姿势调用都一样，直接提示根因）
PERM_CODES = {99991663, 99991661, 99991664, 99991665, 99991667, 99991668}


def fetch_sheet(tk, sheet_id):
    """
    读取单个子表。

    飞书「读取多个范围」接口要点（查官方文档确认，别凭印象改）：
      - GET 方法，不是 POST
      - 路径是 /sheets/v2/spreadsheets/<token>/values_batch_get（spreadsheets 复数）
      - ranges 是 URL query 参数，多个 range 用逗号分隔
      - 单次响应上限 10MB，所以要分段读
    """
    qs = urllib.parse.urlencode({
        'ranges': ','.join(build_ranges(sheet_id)),
        'valueRenderOption': 'ToString',
        'dateTimeRenderOption': 'FormattedString',
    })
    url = f'{LARK_BASE}/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}/values_batch_get?{qs}'
    j = http(url, headers={'Authorization': 'Bearer ' + tk})
    if j.get('code') != 0:
        code, msg = j.get('code'), j.get('msg')
        if code in PERM_CODES:
            raise RuntimeError(
                f'飞书权限不足（code={code} msg={msg}）。99% 是漏了这一步：'
                f'打开表格 → 右上角「分享」→ 把自建应用加为「可阅读」协作者'
            )
        raise RuntimeError(f'读取子表 {sheet_id} 失败: code={code} msg={msg}')
    return j['data']


def main():
    app_id = os.environ.get('LARK_APP_ID')
    app_secret = os.environ.get('LARK_APP_SECRET')
    if not app_id or not app_secret:
        print('!! 缺少环境变量 LARK_APP_ID / LARK_APP_SECRET', file=sys.stderr)
        return 1

    tk = tenant_token(app_id, app_secret)
    os.makedirs(DATA_DIR, exist_ok=True)

    rows_all = []
    for name, sid in SHEETS.items():
        data = fetch_sheet(tk, sid)
        rows = []
        for vr in (data.get('valueRanges') or []):
            for row in (vr.get('values') or []):
                rows.append(row)
        if not rows:
            print(f'!! {name} 拉取为空，跳过（表格结构可能变了）', file=sys.stderr)
            return 1
        print(f'  {name:<10} {len(rows):>5} 行')
        rows_all.extend(rows)

    # 底稿是唯一数据源，合并写入 master.json（build_library.py 优先读它）
    out = {'sheets': [{'name': '数据底稿', 'range': f'A{ROW_START}:P{ROW_END}', 'data': rows_all}]}
    path = os.path.join(DATA_DIR, 'master.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'  合并 -> {os.path.basename(path)}  {len(rows_all)} 行')
    return 0


if __name__ == '__main__':
    sys.exit(main())
