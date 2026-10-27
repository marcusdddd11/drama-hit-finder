#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从飞书表格「数据底稿」子表（全量）构建剧目库，并计算「榜单热度分」。

重要：本分数只覆盖爆款判定的【热度层】（榜单排名 + 多源交叉），
不包含投放层（素材数/在投天数）与变现层（分账/内购）。
因此产出的是「疑似爆款」排序，不是最终选品结论。
"""
import json
import os
import re
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, 'data')

SHEETS = ['reelshort', 'pinedrama', 'dramabox', 'netshort', 'shortmax', 'moboreels', 'goodshort']
# 文件名 -> 剧场名
PLATFORM_ALIAS = {'reelshort': 'ReelShort', 'pinedrama': 'PineDrama', 'dramabox': 'Dramabox',
                  'netshort': 'NetShort', 'shortmax': 'ShortMax', 'moboreels': 'MoboReels',
                  'goodshort': 'GoodShort'}

COLS = ['seq', 'name', 'drama_id', 'tags', 'lang', 'region',
        'src_type', 'src', 'rank_d', 'p_d', 'rank_w', 'p_w',
        'rank_m', 'p_m', 'platform', 'pub_date']

EXCEL_EPOCH = datetime(1899, 12, 30)


def parse_date(v):
    """兼容 Excel 序列号 / YYYY/M/D / YYYY-MM-DD / 空"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # 原表里混有区间写法 '2026-08-18 ~ 2026-10-17'，取起点（上线日期）
    if '~' in s:
        s = s.split('~')[0].strip()
    if re.fullmatch(r'\d{5}(\.\d+)?', s):
        try:
            return EXCEL_EPOCH + timedelta(days=int(float(s)))
        except Exception:
            return None
    s2 = s.replace('-', '/')
    for fmt in ('%Y/%m/%d', '%Y/%m/%d %H:%M:%S', '%Y/%m'):
        try:
            return datetime.strptime(s2, fmt)
        except ValueError:
            continue
    return None


def to_int(v):
    """榜单排名，非数字返回 None"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r'\d+', s)
    return int(m.group()) if m else None


def split_tags(v):
    if not v:
        return []
    s = str(v).replace('，', '、').replace(',', '、')
    out = []
    for t in s.split('、'):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


# 原表「题材」列里混了三类东西，必须拆开，否则筛选会被污染
# 两种写法都要收：底稿里可能带 emoji 前缀，也可能被火星清理成纯文字
FORMAT_TAGS = {'AI仿真人', '实拍', '3D漫', '2D漫',
               '动态解说漫'}              # 制作形式
# 注：'🌟仿真人&AI剧' / '仿真人&AI剧' 已于 2026-10-27 经火星确认移除（底稿中 0 部）。
#     若将来数据里再出现，会被归类为「题材」而非「制作形式」——这是移除后的预期行为。
AUDIENCE_TAGS = {'女频', '男频', 'BL', 'LGBTQ+',
                 '双男主', '双女主', '大女主'}              # 受众
# 注：'男频成长' 已于 2026-10-26 从源头废弃（底稿中已无此标签），从词典移除。
#     若将来数据里再出现，会被归类为「题材」而非「受众」——这是废弃后的预期行为。
NOISE_TAGS = {'其他'}                                    # 无信息量


def classify_tag(t):
    if t in FORMAT_TAGS:
        return 'format'
    if t in AUDIENCE_TAGS:
        return 'audience'
    if t in NOISE_TAGS:
        return 'noise'
    return 'theme'


# ---------------- 加载 ----------------
# 数据源优先级：数据底稿（全量 7079 行，剧场/语种/来源 100% 填充）
#              > 7 个剧场分表（旧路径，不是全量，缺约 680 行，仅作兜底）
MASTER_PATH = os.path.join(DATA_DIR, 'master.json')

raw_rows = []
per_sheet = {}

if os.path.exists(MASTER_PATH):
    sheet = json.load(open(MASTER_PATH, encoding='utf-8'))['sheets'][0]
    n = 0
    for r in sheet['data']:                   # 底稿已按 A4 起拉，无表头行
        r = [('' if c is None else c) for c in r]
        if len(r) < 16:
            r = r + [''] * (16 - len(r))
        name = str(r[1]).strip()
        if not name or name == '短剧剧名' or name.startswith('参考行'):
            continue
        d = dict(zip(COLS, r))
        d['_sheet'] = str(r[14]).strip() or '未知'
        raw_rows.append(d)
        n += 1
    per_sheet['数据底稿'] = n
    print(f'[load] 数据源 = 数据底稿（全量）  有效行 {len(raw_rows)}')
else:
    print('[warn] 未找到 data/master.json，回退到 7 个剧场分表（非全量！）')
    for sh in SHEETS:
        path = os.path.join(DATA_DIR, f'{sh}.json')
        sheet = json.load(open(path, encoding='utf-8'))['sheets'][0]
        n = 0
        for r in sheet['data'][1:]:           # 跳过表头行（row 8）
            r = [('' if c is None else c) for c in r]
            if len(r) < 16:
                r = r + [''] * (16 - len(r))
            name = str(r[1]).strip()
            if not name or name == '短剧剧名':
                continue
            d = dict(zip(COLS, r))
            d['_sheet'] = PLATFORM_ALIAS.get(sh, sh)
            raw_rows.append(d)
            n += 1
        per_sheet[PLATFORM_ALIAS.get(sh, sh)] = n
    print(f'[load] 有效行 {len(raw_rows)}  分表: {per_sheet}')

# ---------------- 按剧名聚合 ----------------
agg = {}
for r in raw_rows:
    key = re.sub(r'\s+', ' ', str(r['name']).strip()).lower()
    a = agg.setdefault(key, {
        'name': str(r['name']).strip(),
        'langs': Counter(), 'tags': Counter(), 'platforms': Counter(),
        'tags_theme': Counter(), 'tags_audience': Counter(),
        'tags_format': Counter(), 'tags_noise': Counter(),
        'sources': Counter(), 'src_types': Counter(), 'regions': set(),
        'best_d': None, 'best_w': None, 'best_m': None,
        'dates': [], 'rows': 0,
        # 每个剧单来源各自的最好名次与统计周期：src -> [d, w, m, pd, pw, pm]
        'src_detail': {},
    })
    a['rows'] += 1
    if r['lang']:
        a['langs'][str(r['lang']).strip()] += 1
    for t in split_tags(r['tags']):
        a['tags'][t] += 1
        a['tags_' + classify_tag(t)][t] += 1
    plat = str(r['platform']).strip() or r['_sheet']
    if plat:
        a['platforms'][plat] += 1
    src = str(r['src']).strip()
    if src:
        a['sources'][src] += 1
        # 每来源最好名次：[d, w, m, 日榜周期, 周榜周期, 月榜周期]
        sd = a['src_detail'].setdefault(src, [None, None, None, '', '', ''])
        for fld, i, per in (('rank_d', 0, 'p_d'), ('rank_w', 1, 'p_w'), ('rank_m', 2, 'p_m')):
            v = to_int(r[fld])
            if v is not None and (sd[i] is None or v < sd[i]):
                sd[i] = v
                sd[3 + i] = str(r[per]).strip()
    if r['src_type']:
        a['src_types'][str(r['src_type']).strip()] += 1
    if r['region']:
        a['regions'].add(str(r['region']).strip())
    for fld, key in (('rank_d', 'best_d'), ('rank_w', 'best_w'), ('rank_m', 'best_m')):
        v = to_int(r[fld])
        if v is not None and (a[key] is None or v < a[key]):
            a[key] = v
    dt = parse_date(r['pub_date'])
    if dt:
        a['dates'].append(dt)

# ---------------- 打分 ----------------
# 参考日期：数据的更新时间 2026/10/23（表格 row1 标注）
REF_DATE = datetime(2026, 10, 23)


def rank_score(rk):
    """单个榜单名次 -> 0~15"""
    if rk is None:
        return 0
    if rk <= 3:
        return 15
    if rk <= 10:
        return 12
    if rk <= 20:
        return 8
    if rk <= 50:
        return 4
    return 1


tag_freq = Counter()
library = []
for key, a in agg.items():
    src_cnt = len(a['sources'])
    plat_cnt = len(a['platforms'])

    # 1) 多源交叉 0-40
    s1 = {1: 6, 2: 18, 3: 30}.get(src_cnt, 40 if src_cnt >= 4 else 0)

    # 2) 榜单名次 0-40（日0.45 / 周0.35 / 月0.20）
    raw_board = (rank_score(a['best_d']) * 0.45 +
                 rank_score(a['best_w']) * 0.35 +
                 rank_score(a['best_m']) * 0.20)
    s2 = round(raw_board / 15 * 40, 1)

    # 3) 跨剧场覆盖 0-20
    s3 = {1: 3, 2: 10, 3: 15}.get(plat_cnt, 20 if plat_cnt >= 4 else 0)

    # 4) 新剧加成 0-10（按最早发布时间算剧龄）
    if a['dates']:
        age = (REF_DATE - min(a['dates'])).days
        if age <= 30:
            s4, age = 10, max(age, 0)
        elif age <= 60:
            s4 = 6
        elif age <= 90:
            s4 = 3
        else:
            s4 = 0
        pub = min(a['dates']).strftime('%Y-%m-%d')
    else:
        s4, age, pub = 0, None, None

    total = round((s1 + s2 + s3 + s4) / 110 * 100, 1)

    for t in a['tags_theme']:
        tag_freq[t] += 1

    library.append({
        'name': a['name'],
        'langs': [k for k, _ in a['langs'].most_common()],
        'tags': [k for k, _ in a['tags'].most_common()],
        'themes': [k for k, _ in a['tags_theme'].most_common()],
        'audiences': [k for k, _ in a['tags_audience'].most_common()],
        'formats': [k for k, _ in a['tags_format'].most_common()],
        'platforms': [k for k, _ in a['platforms'].most_common()],
        'sources': [k for k, _ in a['sources'].most_common()],
        'src_detail': {k: a['src_detail'][k] for k in a['sources']},
        'src_types': [k for k, _ in a['src_types'].most_common()],
        'regions': sorted(a['regions']),
        'source_count': src_cnt,
        'platform_count': plat_cnt,
        'best_rank_d': a['best_d'],
        'best_rank_w': a['best_w'],
        'best_rank_m': a['best_m'],
        'pub_date': pub,
        'age_days': age,
        'rows': a['rows'],
        'score_detail': {'source': s1, 'board': s2, 'platform': s3, 'fresh': s4},
        'heat_score': total,
    })

library.sort(key=lambda x: (-x['heat_score'], x['name']))

# ---------------- 分级（按分位数兜底，保证每级都有剧） ----------------
def tier_of(d):
    """分级规则对齐表格里既有方法论：主看跨来源次数，榜单名次做加减档。
    S = 4 个及以上来源，或 3 个来源且日/周榜进前 3
    A = 3 个来源，或 2 个来源且日/周榜进前 10
    B = 2 个来源，或 1 个来源且日/周榜进前 20
    C = 其余
    heat_score 只用于同级内部排序。
    """
    src = d['source_count']
    rd, rw = d['best_rank_d'], d['best_rank_w']
    top3 = (rd is not None and rd <= 3) or (rw is not None and rw <= 3)
    top10 = (rd is not None and rd <= 10) or (rw is not None and rw <= 10)
    top20 = (rd is not None and rd <= 20) or (rw is not None and rw <= 20)
    if src >= 4 or (src == 3 and top3):
        return 'S'
    if src == 3 or (src == 2 and top10):
        return 'A'
    if src == 2 or (src == 1 and top20):
        return 'B'
    return 'C'


for d in library:
    d['tier'] = tier_of(d)

# ---------------- 输出 ----------------
out = {
    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'data_as_of': '2026-10-23',
    'source': '飞书文档「海外剧场榜单」· 数据底稿（全量 7079 行）',
    'scope_note': '仅覆盖爆款判定的热度层（榜单排名+多源交叉），不含投放层与变现层',
    'stats': {
        'raw_rows': len(raw_rows),
        'unique_dramas': len(library),
        'per_platform': per_sheet,
        'tier_count': dict(Counter(d['tier'] for d in library)),
        'lang_count': dict(Counter(l for d in library for l in d['langs'])),
    },
    'tag_freq': tag_freq.most_common(),
    'dramas': library,
}
os.makedirs(DATA_DIR, exist_ok=True)
with open(os.path.join(DATA_DIR, 'drama_library.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

with open(os.path.join(DATA_DIR, 'drama_library.csv'), 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['热度分', '等级', '剧名', '语种', '剧场', '题材', '制作形式', '受众',
                '跨来源数', '剧单来源', '日榜', '周榜', '月榜', '发布时间', '剧龄(天)'])
    for d in library:
        w.writerow([d['heat_score'], d['tier'], d['name'], '、'.join(d['langs']),
                    '、'.join(d['platforms']), '、'.join(d['themes'][:8]),
                    '、'.join(d['formats']), '、'.join(d['audiences']), d['source_count'],
                    '、'.join(d['sources']), d['best_rank_d'] or '', d['best_rank_w'] or '',
                    d['best_rank_m'] or '', d['pub_date'] or '', d['age_days'] if d['age_days'] is not None else ''])

# ---- 网页用精简数据（去掉冗余字段） ----
WEB_DIR = os.path.join(BASE, 'web')
os.makedirs(WEB_DIR, exist_ok=True)
KEEP = ['name', 'langs', 'themes', 'audiences', 'formats', 'platforms', 'sources',
        'src_types', 'source_count', 'platform_count', 'best_rank_d', 'best_rank_w',
        'best_rank_m', 'pub_date', 'age_days', 'heat_score', 'tier', 'score_detail',
        'src_detail']
slim = {
    'meta': {k: v for k, v in out.items() if k != 'dramas'},
    'dramas': [{k: d[k] for k in KEEP} for d in library],
}
with open(os.path.join(WEB_DIR, 'drama_data.js'), 'w', encoding='utf-8') as f:
    f.write('window.DRAMA_DATA=' + json.dumps(slim, ensure_ascii=False, separators=(',', ':')) + ';')
print(f'[web] 精简数据 {os.path.getsize(os.path.join(WEB_DIR, "drama_data.js")) // 1024} KB -> web/drama_data.js')

print(f'[build] 唯一剧目 {len(library)} 部')
print(f'[tier] {out["stats"]["tier_count"]}')
print(f'[lang] {out["stats"]["lang_count"]}')
print(f'[tag] 题材标签种类 {len(tag_freq)}，top15: {tag_freq.most_common(15)}')
print('\n[top 15 剧目]')
for d in library[:15]:
    print(f'  {d["heat_score"]:>5} {d["tier"]}  {d["name"][:42]:<44} 源{d["source_count"]} 剧场{d["platform_count"]} '
          f'日{d["best_rank_d"]} 周{d["best_rank_w"]} 月{d["best_rank_m"]} {d["pub_date"]}')
