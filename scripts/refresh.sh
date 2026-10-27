#!/bin/bash
# 一键刷新海外短剧剧目库
#   飞书表格 -> data/*.json -> data/drama_library.{json,csv} -> web/drama_data.js
# 用法: bash scripts/refresh.sh
# 前置: lark-cli 已登录（lark-cli auth status）。token 过期时会提示重新授权。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1
export LARKSUITE_CLI_NO_SKILLS_NOTIFIER=1

URL="https://qcnvh9os52bb.feishu.cn/wiki/FE1iwsFjDi8IBfkzdS3cDsQInNg"
# 数据源 = 「数据底稿」子表（全量）。7 个剧场分表不是全量，不要再拿它们当数据源。
MASTER_SHEET="数据底稿"
MASTER_LAST=7082          # 底稿最大行（表头在第 2 行，数据从第 4 行开始）
CHUNK=2400                # 分段拉取，避免单次读取被字符上限截断
PY="/Users/killersu/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

echo "[1/4] 检查飞书登录状态..."
STATUS="$(lark-cli auth status --json 2>/dev/null || true)"
# 注意：tokenStatus 有 valid / needs_refresh 两种可用态。
# needs_refresh = 「下次调用自动刷新」，不是过期，当过期处理会误报。
if ! printf '%s' "$STATUS" | "$PY" -c '
import json,sys
d=json.load(sys.stdin)
u=d.get("identities",{}).get("user",{})
sys.exit(0 if u.get("tokenStatus") in ("valid","needs_refresh") else 1)
'; then
  echo "  !! 飞书登录已过期或不可用，请重新授权（lark-cli auth login --no-wait --json）"
  exit 1
fi
echo "  OK（$("$PY" -c "import json,sys;print(json.loads(sys.argv[1])[\"identities\"][\"user\"][\"userName\"])" "$STATUS")）"

echo "[2/4] 拉取 [${MASTER_SHEET}]（分段，每段 ${CHUNK} 行）..."
mkdir -p data
rm -f data/_master_*.json
START=4
IDX=0
while [ "$START" -le "$MASTER_LAST" ]; do
  END=$((START + CHUNK - 1))
  [ "$END" -gt "$MASTER_LAST" ] && END=$MASTER_LAST
  OUT="data/_master_${IDX}.json"
  if lark-cli sheets +table-get \
    --url "$URL" --sheet-name "$MASTER_SHEET" --range "A${START}:P${END}" \
    --no-header --as user --output-path "./$OUT" >/dev/null 2>&1; then
    TRUNC="$("$PY" -c "import json,sys;d=json.load(open('$OUT'));print(d['sheets'][0].get('truncated'))" 2>/dev/null || echo unknown)"
    [ "$TRUNC" = "True" ] && { echo "  !! 分段 A${START}:P${END} 被截断，请调小 CHUNK"; exit 1; }
    echo "  A${START}:P${END} -> ok"
  else
    echo "  !! A${START}:P${END} 拉取失败（飞书返回错误）"; exit 1
  fi
  START=$((END + 1))
  IDX=$((IDX + 1))
done

"$PY" - <<'PYEOF'
import glob, json
rows = []
for f in sorted(glob.glob('data/_master_*.json')):
    rows.extend(json.load(open(f, encoding='utf-8'))['sheets'][0]['data'])
json.dump({'sheets': [{'name': '数据底稿', 'data': rows}]},
          open('data/master.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(f'  合并 -> data/master.json  {len(rows)} 行')
PYEOF

echo "[3/5] 清洗 + 打分 + 生成网页数据..."
"$PY" scripts/build_library.py

echo "[4/5] 发布前体检（与上一次快照对比）..."
# 体检不通过 → 直接中止，且不打包：dist/ 里保持上次验证过的版本，
# 避免手滑把脏数据的单文件发出去。
if ! "$PY" scripts/check_release.py --yes; then
  echo
  echo "!! 体检未通过，已中止。dist/ 未更新，线上仍是旧版本。"
  echo "!! 处理完再重跑本脚本；确认这批数据没问题可加 --force。若确实要采信："
  echo "   $PY scripts/check_release.py --reset"
  [ "${REFRESH_FORCE:-0}" = "1" ] || exit 1
fi

echo "[5/5] 打包单文件版（可直接发给别人，离线可用）..."
bash scripts/bundle_standalone.sh

echo
echo "数据已更新: web/drama_data.js + dist/DramaHitFinder.html"
echo
echo "★ 发布前请务必先做两件事："
echo "  1) 打开 dist/DramaHitFinder.html 本地预览，确认显示无误"
echo "  2) 确认后再让我上传覆盖线上（我不会在你点头前发布）"
