#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发布前体检 —— 新数据与上一次发布的快照对比，异常则拒绝发布。

用法：
    python3 scripts/check_release.py            # 体检，并询问是否把本次设为新基线
    python3 scripts/check_release.py --accept   # 体检通过后直接把本次设为新基线
    python3 scripts/check_release.py --reset    # 强制用当前数据重建基线（跳过体检）

退出码：
    0 = PASS / WARN（可以发布）
    1 = FAIL（禁止发布，先查数据）
    2 = 尚未建立基线，本次已生成

设计要点：
    - 拦的是「肉眼看不见的数据劣化」，不是页面报错。
      页面崩不崩看得出来；剧目数从 5545 掉到 900 看不出来。
    - 阈值集中在 THRESHOLDS，改一处即可。
"""
import json
import os
import sys
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(ROOT, "data", "drama_library.json")
# 基线只存「指标快照」而非整份剧目库 —— 几 KB，能安全提交进 git。
# 这样 GitHub Actions 里也有基线可比对，否则 CI 每次都是「首次」，体检形同虚设。
BASE = os.path.join(ROOT, "data", "release_baseline.json")

# ---------------- 阈值（按需调整） ----------------
THRESHOLDS = {
    "dramas_drop":      0.10,   # 唯一剧目数跌幅超过 10% → FAIL
    "raw_rows_drop":    0.10,   # 原始行数跌幅超过 10% → FAIL
    "s_drop":           0.30,   # S 级数量跌幅超过 30% → FAIL
    "a_drop":           0.30,   # A 级数量跌幅超过 30% → FAIL
    "s_gain":           1.00,   # S 级暴涨超过 100% → WARN（多半是规则/数据源变了）
    "bc_drop":          0.50,   # B/C 级跌幅超过 50% → WARN（它们基数大，允许更大波动）
    "min_platforms":    7,      # 去重剧场数少于 7 → FAIL
    "min_langs":        5,      # 去重语种少于 5 → FAIL
    "min_dramas":       1000,   # 绝对下限：少于 1000 部 → FAIL
    "s_top_retention":  0.50,   # 旧 Top50 里留存不足 50% → WARN
}
# ------------------------------------------------

C_RED, C_GRN, C_YEL, C_DIM, C_BOLD, C_OFF = "\033[91m", "\033[92m", "\033[93m", "\033[2m", "\033[1m", "\033[0m"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def wide(s):
    """终端显示宽度：中日韩全角字符占 2 列"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def pad(s, width):
    """按显示宽度右补齐"""
    return s + " " * max(0, width - wide(s))


def load_base():
    """读基线。兼容两种形态：精简指标快照（现版）/ 整份剧目库（旧版）"""
    d = load(BASE)
    return profile(d) if "dramas" in d else d


def save_base():
    """把当前库提炼成指标快照存下来"""
    snap = profile(load(CUR))
    with open(BASE, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return snap


def profile(d):
    """把一份库提炼成对比用的指标"""
    dramas = d.get("dramas", [])
    stats = d.get("stats", {})
    plats, langs = set(), set()
    auds, fmts, themes = set(), set(), set()
    for x in dramas:
        for p in (x.get("platforms") or []):
            if p:
                plats.add(p)
        for l in (x.get("langs") or []):
            if l:
                langs.add(l)
        for a in (x.get("audiences") or []):
            if a:
                auds.add(a)
        for f in (x.get("formats") or []):
            if f:
                fmts.add(f)
        for t in (x.get("themes") or []):
            if t:
                themes.add(t)
    tier = stats.get("tier_count", {}) or {}
    ranked = sorted(dramas, key=lambda x: (-(x.get("heat_score") or 0), x.get("name") or ""))
    top = [x.get("name") for x in ranked[:50]]
    s = sum(1 for x in dramas if (x.get("source_count") or 0) > 0)
    return {
        "generated_at": d.get("generated_at", ""),
        "data_as_of": d.get("data_as_of", ""),
        "source": d.get("source", ""),
        "raw_rows": stats.get("raw_rows", 0),
        "unique_dramas": stats.get("unique_dramas", len(dramas)),
        "tier_s": tier.get("S", 0), "tier_a": tier.get("A", 0),
        "tier_b": tier.get("B", 0), "tier_c": tier.get("C", 0),
        "platforms": sorted(plats), "n_platforms": len(plats),
        "langs": sorted(langs), "n_langs": len(langs),
        # 标签维度：剧目数持平不代表内容没变。曾出现过「男频成长」从底稿废弃、
        # 所有数量指标仍持平、体检全绿的情况，所以标签集合必须单独比对。
        "audiences": sorted(auds), "formats": sorted(fmts), "themes": sorted(themes),
        "top50": top,
        "has_source": s,
    }


def pct(new, old):
    """变化率，old 为 0 时避免除零"""
    if not old:
        return None if not new else 1.0
    return (new - old) / old


def fmt(v):
    return f"{v:,}" if isinstance(v, int) else str(v)


def delta_line(label, newv, oldv, drop_limit=None, gain_limit=None, min_value=None, warn_drop=None):
    """生成一行对比，返回 (标签, 明细, 级别)"""
    chg = pct(newv, oldv)
    mark, level = "持平" if chg == 0 else "", "OK"
    if chg is not None and chg != 0:
        mark = ("+" if chg > 0 else "") + f"{chg*100:.1f}%"
    detail = f"{fmt(newv)}  (原 {fmt(oldv)})"
    if mark:
        detail += f"  {mark}"

    if min_value is not None and newv < min_value:
        level, detail = "FAIL", detail + f"  ← 低于绝对下限 {min_value}"
    elif chg is not None and drop_limit is not None and chg < 0 and abs(chg) > drop_limit:
        level = "FAIL"
        detail += f"  ← 跌幅超 {drop_limit*100:.0f}%"
    elif chg is not None and warn_drop is not None and chg < 0 and abs(chg) > warn_drop:
        level = "WARN"
        detail += f"  ← 跌幅超 {warn_drop*100:.0f}%，留意"
    elif chg is not None and gain_limit is not None and chg > gain_limit:
        level = "WARN"
        detail += f"  ← 涨幅超 {gain_limit*100:.0f}%，确认是否预期"
    return label, detail, level


def main():
    args = sys.argv[1:]
    if "--reset" in args:
        save_base()
        print(f"{C_YEL}[reset]{C_OFF} 已用当前数据重建基线 data/release_baseline.json")
        return 0

    if not os.path.exists(CUR):
        print(f"{C_RED}[FAIL]{C_OFF} 找不到 {CUR}，先跑 scripts/refresh.sh")
        return 1

    new = profile(load(CUR))

    # 首次：建基线
    if not os.path.exists(BASE):
        save_base()
        print(f"{C_YEL}[初次]{C_OFF} 尚无历史基线，已把当前数据存为基线。下次刷新起开始对比。")
        print(f"       基线快照 data/release_baseline.json")
        print(f"       当前: {fmt(new['unique_dramas'])} 部 / S {new['tier_s']} / 剧场 {new['n_platforms']}")
        return 2

    old = load_base()
    T = THRESHOLDS
    rows, worst = [], "OK"

    for label, key, dl, gl, mv in [
        ("原始榜单行", "raw_rows", T["raw_rows_drop"], None, None),
        ("唯一剧目数", "unique_dramas", T["dramas_drop"], None, T["min_dramas"]),
        ("S 级数量", "tier_s", T["s_drop"], T["s_gain"], None),
        ("A 级数量", "tier_a", T["a_drop"], T["s_gain"], None),
    ]:
        rows.append(delta_line(label, new[key], old[key], dl, gl, mv))

    rows.append(delta_line("B 级数量", new["tier_b"], old["tier_b"], warn_drop=T["bc_drop"]))
    rows.append(delta_line("C 级数量", new["tier_c"], old["tier_c"], warn_drop=T["bc_drop"]))
    rows.append(delta_line("去重剧场数", new["n_platforms"], old["n_platforms"], None, None, T["min_platforms"]))
    rows.append(delta_line("去重语种数", new["n_langs"], old["n_langs"], None, None, T["min_langs"]))

    # 头部老剧留存率
    old_top = set(old["top50"])
    keep = len([n for n in new["top50"] if n in old_top]) if old_top else 0
    ret = keep / len(old_top) if old_top else 1
    lvl = "WARN" if ret < T["s_top_retention"] else "OK"
    rows.append(("头部剧留存", f"Top50 中 {keep}/{len(old_top)} 仍在榜  {ret*100:.0f}%" +
                 (f"  ← 低于 {T['s_top_retention']*100:.0f}%，榜单可能换源了" if lvl == "WARN" else ""), lvl))

    # 数据截止日
    if new["data_as_of"] == old["data_as_of"]:
        rows.append(("数据截止日", f"{new['data_as_of']}  (与上次相同)  ← 白刷了一次？", "WARN"))
    else:
        rows.append(("数据截止日", f"{old['data_as_of']} → {new['data_as_of']}", "OK"))

    # 剧场 / 语种 消失清单
    gone_p = sorted(set(old["platforms"]) - set(new["platforms"]))
    new_p = sorted(set(new["platforms"]) - set(old["platforms"]))
    if gone_p or new_p:
        txt = []
        if gone_p:
            txt.append("消失: " + "、".join(gone_p))
        if new_p:
            txt.append("新增: " + "、".join(new_p))
        rows.append(("剧场变动", " ｜ ".join(txt), "WARN" if gone_p else "OK"))
    gone_l = sorted(set(old["langs"]) - set(new["langs"]))
    if gone_l:
        rows.append(("语种变动", "消失: " + "、".join(gone_l), "WARN"))

    # 标签维度：值消失 = 源头废弃了这个分类，筛选项也会跟着少一个（要确认是有意还是漏数据）
    def tag_row(label, key, limit=6):
        o, n = set(old.get(key, [])), set(new.get(key, []))
        gone, add = sorted(o - n), sorted(n - o)
        if not gone and not add:
            return
        txt = []
        if gone:
            txt.append("消失: " + "、".join(gone[:limit]) + (f" 等 {len(gone)} 项" if len(gone) > limit else ""))
        if add:
            txt.append("新增: " + "、".join(add[:limit]) + (f" 等 {len(add)} 项" if len(add) > limit else ""))
        rows.append((label, " ｜ ".join(txt), "WARN" if gone else "OK"))

    tag_row("受众标签变动", "audiences")
    tag_row("制作形式变动", "formats")
    tag_row("题材标签变动", "themes", limit=8)

    W = max(wide(r[0]) for r in rows)
    print()
    print(f"{C_BOLD}发布前体检{C_OFF}   基线 {old['generated_at']}  →  本次 {new['generated_at']}")
    print("─" * 78)
    for label, detail, lvl in rows:
        tag = {"OK": f"{C_DIM}  OK  {C_OFF}", "WARN": f"{C_YEL} WARN {C_OFF}", "FAIL": f"{C_RED} FAIL {C_OFF}"}[lvl]
        if lvl == "FAIL":
            worst = "FAIL"
        elif lvl == "WARN" and worst != "FAIL":
            worst = "WARN"
        print(f" {tag}  {pad(label, W)}   {detail}")
    print("─" * 78)

    if worst == "FAIL":
        print(f"{C_RED}✗ 体检未通过 —— 禁止发布。{C_OFF}")
        print(f"  线上仍是旧版本（{old['generated_at']}），未受影响。")
        print()
        print("  下一步三选一：")
        print("   1. 查飞书表格是不是动了结构/改名/数据没跑完，修完重跑 refresh.sh")
        print("   2. 确认这次变动确实是预期的，酌情调 THRESHOLDS 阈值")
        print("   3. 确认无误后强制重设基线：python3 scripts/check_release.py --reset")
        return 1

    if worst == "WARN":
        print(f"{C_YEL}! 有变动项，请人工核对后决定是否发布{C_OFF}")
    else:
        print(f"{C_GRN}✓ 体检通过{C_OFF}，各项变动在正常范围")

    print()
    print("  发布前请自行打开 dist/DramaHitFinder.html 扫一眼（这是你的「本地预览」，不会外泄）")

    if "--accept" in args:
        save_base()
        print(f"{C_GRN}  已接受，基线更新为本次数据{C_OFF}")
    elif "--yes" not in args:
        try:
            ans = input("\n  体检结果你确认了吗？确认则记为新基线 [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans == "y":
            save_base()
            print(f"{C_GRN}  已记为新基线，下次刷新以此为对比基准{C_OFF}")
        else:
            print(f"{C_DIM}  未记录基线（线上未变动，数据仍在 data/ 里等你处理）{C_OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
