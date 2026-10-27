/* 浏览器端清洗：把飞书原始行（转发的 valueRanges）聚合成剧目库 + 热度分
 * 逻辑与 scripts/build_library.py 一一对应，改一边必须改另一边。
 * 输入 buildLibrary({ReelShort:[[...16列...], ...], ...}, refDate)
 * 输出 {meta, dramas}，结构与 web/drama_data.js 完全一致。
 */
(function (global) {
  'use strict';

  var COLS = ['seq', 'name', 'drama_id', 'tags', 'lang', 'region',
    'src_type', 'src', 'rank_d', 'p_d', 'rank_w', 'p_w',
    'rank_m', 'p_m', 'platform', 'pub_date'];

  // '🌟仿真人&AI剧' 已于 2026-10-27 经火星确认移除（底稿 0 部），与 build_library.py 保持一致
  var FORMAT_TAGS = { 'AI仿真人': 1, '实拍': 1, '3D漫': 1, '2D漫': 1, '动漫': 1, '动态解说漫': 1, '🎧 动态解说漫': 1 };
  var AUDIENCE_TAGS = { '女频': 1, '男频': 1, 'BL': 1, 'LGBTQ+': 1, '双男主': 1, '双女主': 1, '大女主': 1 };
  var NOISE_TAGS = { '其他': 1 };

  function classifyTag(t) {
    if (FORMAT_TAGS[t]) return 'format';
    if (AUDIENCE_TAGS[t]) return 'audience';
    if (NOISE_TAGS[t]) return 'noise';
    return 'theme';
  }

  var EXCEL_EPOCH_UTC = Date.UTC(1899, 11, 30);

  function parseDate(v) {
    if (v === null || v === undefined) return null;
    var s = String(v).trim();
    if (!s) return null;
    // 原表里混有区间写法 '2026-08-18 ~ 2026-10-17'，取起点（上线日期）
    if (s.indexOf('~') !== -1) s = s.split('~')[0].trim();
    if (/^\d{5}(\.\d+)?$/.test(s)) {
      return new Date(EXCEL_EPOCH_UTC + parseFloat(s) * 86400000);
    }
    var s2 = s.replace(/-/g, '/');
    var m = s2.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})/);
    if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    m = s2.match(/^(\d{4})\/(\d{1,2})$/);
    if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, 1));
    return null;
  }

  function toInt(v) {
    if (v === null || v === undefined) return null;
    var s = String(v).trim();
    if (!s) return null;
    var m = s.match(/\d+/);
    return m ? parseInt(m[0], 10) : null;
  }

  function splitTags(v) {
    if (!v) return [];
    var s = String(v).replace(/，/g, '、').replace(/,/g, '、');
    var out = [];
    var parts = s.split('、');
    for (var i = 0; i < parts.length; i++) {
      var t = parts[i].trim();
      if (t && out.indexOf(t) === -1) out.push(t);
    }
    return out;
  }

  function Counter() { this.m = new Map(); this.order = []; }
  Counter.prototype.add = function (k) {
    if (this.m.has(k)) this.m.set(k, this.m.get(k) + 1);
    else { this.m.set(k, 1); this.order.push(k); }
  };
  Counter.prototype.keys = function () {
    var self = this;
    return this.order.slice().sort(function (a, b) { return self.m.get(b) - self.m.get(a); });
  };

  // Python 的 round(x, 1) 是「银行家舍入」（.5 取偶数），JS Math.round 是四舍五入。
  // 必须对齐，否则同分剧目排序会跟 Python 版本错位。
  function round1(x) {
    var v = x * 10;
    var fl = Math.floor(v);
    var frac = v - fl;
    if (Math.abs(frac - 0.5) < 1e-9) {
      return (fl % 2 === 0 ? fl : fl + 1) / 10;
    }
    return Math.round(v) / 10;
  }

  function rankScore(rk) {
    if (rk === null) return 0;
    if (rk <= 3) return 15;
    if (rk <= 10) return 12;
    if (rk <= 20) return 8;
    if (rk <= 50) return 4;
    return 1;
  }

  function fmtDate(d) {
    if (!d) return null;
    var y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, dd = d.getUTCDate();
    return y + '-' + (m < 10 ? '0' + m : m) + '-' + (dd < 10 ? '0' + dd : dd);
  }

  function mostCommonKeys(c) { return c.keys(); }

  function mkRec(r) {
    var rec = {};
    for (var c = 0; c < 16; c++) {
      var v = r[c];
      rec[COLS[c]] = (v === null || v === undefined) ? '' : v;
    }
    return rec;
  }

  function buildLibrary(sheets, refDate) {
    var rawRows = [];
    var perPlatform = {};

    if (Array.isArray(sheets)) {
      // 数据底稿模式：全量单表，无表头行，剧场取自 platform 列
      for (var i = 0; i < sheets.length; i++) {
        var r0 = sheets[i] || [];
        var rec0 = mkRec(r0);
        var nm0 = String(rec0.name).trim();
        if (!nm0 || nm0 === '短剧剧名' || nm0.indexOf('参考行') === 0) continue;
        rec0._sheet = String(rec0.platform).trim() || '未知';
        rawRows.push(rec0);
        perPlatform[rec0._sheet] = (perPlatform[rec0._sheet] || 0) + 1;
      }
    } else {
      Object.keys(sheets).forEach(function (pname) {
        var rows = sheets[pname] || [];
        var n = 0;
        for (var i = 0; i < rows.length; i++) {
          var r = rows[i] || [];
          var rec = mkRec(r);
          var name = String(rec.name).trim();
          if (!name || name === '短剧剧名') continue;
          rec._sheet = pname;
          rawRows.push(rec);
          n++;
        }
        perPlatform[pname] = n;
      });
    }

    // 聚合
    var agg = {};
    for (var i = 0; i < rawRows.length; i++) {
      var r = rawRows[i];
      var key = String(r.name).trim().replace(/\s+/g, ' ').toLowerCase();
      var a = agg[key];
      if (!a) {
        a = agg[key] = {
          name: String(r.name).trim(),
          langs: new Counter(), tags: new Counter(),
          tags_theme: new Counter(), tags_audience: new Counter(),
          tags_format: new Counter(), tags_noise: new Counter(),
          platforms: new Counter(), sources: new Counter(), src_types: new Counter(),
          regions: {}, best_d: null, best_w: null, best_m: null, dates: [], rows: 0,
          src_detail: {}
        };
      }
      a.rows++;
      if (r.lang) a.langs.add(String(r.lang).trim());
      var tg = splitTags(r.tags);
      for (var t = 0; t < tg.length; t++) {
        a.tags.add(tg[t]);
        a['tags_' + classifyTag(tg[t])].add(tg[t]);
      }
      var plat = String(r.platform).trim() || r._sheet;
      if (plat) a.platforms.add(plat);
      if (r.src) {
        var srcName = String(r.src).trim();
        a.sources.add(srcName);
        // 每来源最好名次：[d, w, m, 日榜周期, 周榜周期, 月榜周期]
        var sd = a.src_detail[srcName] || (a.src_detail[srcName] = [null, null, null, '', '', '']);
        var tri = [['rank_d', 0, 'p_d'], ['rank_w', 1, 'p_w'], ['rank_m', 2, 'p_m']];
        for (var ti = 0; ti < 3; ti++) {
          var tv = toInt(r[tri[ti][0]]);
          if (tv !== null && (sd[tri[ti][1]] === null || tv < sd[tri[ti][1]])) {
            sd[tri[ti][1]] = tv;
            sd[3 + tri[ti][1]] = String(r[tri[ti][2]] || '').trim();
          }
        }
      }
      if (r.src_type) a.src_types.add(String(r.src_type).trim());
      if (r.region) a.regions[String(r.region).trim()] = 1;
      var flds = [['rank_d', 'best_d'], ['rank_w', 'best_w'], ['rank_m', 'best_m']];
      for (var f = 0; f < flds.length; f++) {
        var v = toInt(r[flds[f][0]]);
        if (v !== null && (a[flds[f][1]] === null || v < a[flds[f][1]])) a[flds[f][1]] = v;
      }
      var dt = parseDate(r.pub_date);
      if (dt) a.dates.push(dt);
    }

    var ref = refDate || new Date();
    var refUTC = Date.UTC(ref.getFullYear(), ref.getMonth(), ref.getDate());

    var library = [];
    var keys = Object.keys(agg);
    for (var k = 0; k < keys.length; k++) {
      var a = agg[keys[k]];
      var srcCnt = a.sources.order.length;
      var platCnt = a.platforms.order.length;

      var s1 = srcCnt === 1 ? 6 : srcCnt === 2 ? 18 : srcCnt === 3 ? 30 : (srcCnt >= 4 ? 40 : 0);
      var rawBoard = rankScore(a.best_d) * 0.45 + rankScore(a.best_w) * 0.35 + rankScore(a.best_m) * 0.20;
      var s2 = round1(rawBoard / 15 * 40);
      var s3 = platCnt === 1 ? 3 : platCnt === 2 ? 10 : platCnt === 3 ? 15 : (platCnt >= 4 ? 20 : 0);

      var s4 = 0, age = null, pub = null;
      if (a.dates.length) {
        var minD = a.dates[0];
        for (var d = 1; d < a.dates.length; d++) if (a.dates[d] < minD) minD = a.dates[d];
        age = Math.floor((refUTC - minD.getTime()) / 86400000);
        if (age <= 30) { s4 = 10; if (age < 0) age = 0; }
        else if (age <= 60) s4 = 6;
        else if (age <= 90) s4 = 3;
        else s4 = 0;
        pub = fmtDate(minD);
      }

      var total = round1((s1 + s2 + s3 + s4) / 110 * 100);

      library.push({
        name: a.name,
        langs: mostCommonKeys(a.langs),
        themes: mostCommonKeys(a.tags_theme),
        audiences: mostCommonKeys(a.tags_audience),
        formats: mostCommonKeys(a.tags_format),
        platforms: mostCommonKeys(a.platforms),
        sources: mostCommonKeys(a.sources),
        src_detail: a.src_detail,
        src_types: mostCommonKeys(a.src_types),
        regions: Object.keys(a.regions).sort(),
        source_count: srcCnt,
        platform_count: platCnt,
        best_rank_d: a.best_d,
        best_rank_w: a.best_w,
        best_rank_m: a.best_m,
        pub_date: pub,
        age_days: age,
        rows: a.rows,
        score_detail: { source: s1, board: s2, platform: s3, fresh: s4 },
        heat_score: total
      });
    }

    library.sort(function (x, y) {
      if (y.heat_score !== x.heat_score) return y.heat_score - x.heat_score;
      return x.name < y.name ? -1 : x.name > y.name ? 1 : 0;
    });

    function tierOf(d) {
      var src = d.source_count, rd = d.best_rank_d, rw = d.best_rank_w;
      var top3 = (rd !== null && rd <= 3) || (rw !== null && rw <= 3);
      var top10 = (rd !== null && rd <= 10) || (rw !== null && rw <= 10);
      var top20 = (rd !== null && rd <= 20) || (rw !== null && rw <= 20);
      if (src >= 4 || (src === 3 && top3)) return 'S';
      if (src === 3 || (src === 2 && top10)) return 'A';
      if (src === 2 || (src === 1 && top20)) return 'B';
      return 'C';
    }

    var tierCount = { S: 0, A: 0, B: 0, C: 0 };
    var langCount = {};
    for (var i = 0; i < library.length; i++) {
      var d = library[i];
      d.tier = tierOf(d);
      tierCount[d.tier]++;
      for (var l = 0; l < d.langs.length; l++) langCount[d.langs[l]] = (langCount[d.langs[l]] || 0) + 1;
    }

    return {
      meta: {
        generated_at: fmtDate(new Date()) ,
        data_as_of: fmtDate(new Date()),
        live: true,
        source: '飞书文档「海外剧场榜单」· 数据底稿（全量，实时同步）',
        scope_note: '仅覆盖爆款判定的热度层（榜单排名+多源交叉），不含投放层与变现层',
        stats: {
          raw_rows: rawRows.length,
          unique_dramas: library.length,
          per_platform: perPlatform,
          tier_count: tierCount,
          lang_count: langCount
        }
      },
      dramas: library
    };
  }

  global.buildLibrary = buildLibrary;

  /* ---- 从 Worker 拉数据 ---- */
  // 返回 Promise<{ReelShort: rows, ...}>
  // 数据源 = 飞书「数据底稿」子表（全量）。7 个剧场分表不是全量，不要用。
  // 返回底稿原始行数组（不是 {剧场名: rows} 字典）—— buildLibrary 会按数组模式解析。
  var MASTER_SHEET = '数据底稿';

  global.fetchSheets = function (apiBase, sheetNames, onProgress) {
    var name = (sheetNames && sheetNames[0]) || MASTER_SHEET;
    if (onProgress) onProgress(0, 1, name);
    return fetch(apiBase.replace(/\/$/, '') + '/data?sheet=' + encodeURIComponent(name))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' (' + name + ')');
        return r.json();
      })
      .then(function (j) {
        var ranges = (j.data && j.data.valueRanges) || [];
        var rows = [];
        for (var i = 0; i < ranges.length; i++) {
          var v = ranges[i].values || [];
          for (var k = 0; k < v.length; k++) rows.push(v[k]);
        }
        if (!rows.length) throw new Error('底稿返回 0 行，检查 Worker 权限或表格结构');
        if (onProgress) onProgress(1, 1, name);
        return rows;
      });
  };

})(typeof window !== 'undefined' ? window : globalThis);
