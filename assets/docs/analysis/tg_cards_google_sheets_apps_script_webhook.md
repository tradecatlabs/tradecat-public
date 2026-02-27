# Apps Script Webhook（参考实现）：接收 CardEvent → 落事实表 → 渲染看板

> 目标：把 Google Sheets 当成“函数入口”（HTTP POST JSON），并且满足：
> - HMAC 鉴权（公开只读表也能安全写入）
> - 幂等（card_key 去重）
> - 并发安全（dashboard_next_row 用锁）
> - 先落事实后渲染（可重建）

## 1) 你需要先建好工作簿内的 Sheet

必须存在（大小写一致）：
- `看板`
- `卡片索引`
- `卡片字段EAV`
- `卡片明细行`
- `明细字段EAV`
- `大字段索引`
- `元数据`

## 2) Script Properties

在 Apps Script 项目里设置：
- `TC_SHEETS_SECRET`：HMAC 密钥（与 `SHEETS_WEBHOOK_SECRET` 一致）
- `TC_DASHBOARD_COL_L`：默认 `A`
- `TC_DASHBOARD_COL_R`：默认 `M`

## 3) doPost(e) 参考代码（可直接粘贴）

```javascript
function doPost(e) {
  try {
    var raw = (e && e.postData && e.postData.contents) ? e.postData.contents : "";
    // Apps Script 对自定义 header 的获取不稳定：建议同时支持 query 参数传递签名
    // 最稳做法：客户端同时发 Header + Query，两边都校验（此处给最小实现）。

    var ts = _getHeader(e, "X-TC-Timestamp");
    var nonce = _getHeader(e, "X-TC-Nonce");
    var sig = _getHeader(e, "X-TC-Signature");
    _authOrThrow(ts, nonce, sig, raw);

    var payload = JSON.parse(raw || "{}");
    var cardKey = String(payload.card_key || "");
    if (!cardKey) {
      return _json(400, { ok: false, error: "missing_card_key" });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    _ensureSchema(ss);

    // 1) 幂等：卡片索引 是否已有 card_key（先快速检查一次）
    if (_cardsIndexHas(ss, cardKey)) {
      return _json(200, { ok: true, card_key: cardKey, idempotent: true });
    }

    // 2) 渲染与落盘（锁住 next_row，避免并发撞块；锁内二次幂等检查避免并发重复写）
    var lock = LockService.getScriptLock();
    lock.waitLock(20000);
    try {
      if (_cardsIndexHas(ss, cardKey)) {
        return _json(200, { ok: true, card_key: cardKey, idempotent: true });
      }

      var meta = _metaGet(ss);
      var y = Number(meta.dashboard_next_row || 1);
      var colL = meta.dashboard_col_l || "A";
      var colR = meta.dashboard_col_r || "M";
      var rowsCnt = _inferRowsCount(payload);
      var height = 7 + rowsCnt;

      // 2.1) Blob：超长 raw 字段先落 Drive，再把 payload 内对应字段替换成引用（无遗漏）
      _appendBlobsIndex(ss, payload);

      // 2.2) 先落事实：index + fields_eav + rows_eav
      var dash = { sheet: "看板", col_l: colL, col_r: colR, row_y: y, height: height };
      _appendCardsIndex(ss, payload, dash);
      _appendCardFieldsEav(ss, payload);
      _appendRowsEav(ss, payload);

      // 2.3) 再渲染看板
      _renderDashboard(ss, payload, y, colL, colR);
      _metaSet(ss, { dashboard_next_row: y + height });
      return _json(200, { ok: true, card_key: cardKey, idempotent: false, dashboard: dash });
    } finally {
      lock.releaseLock();
    }

  } catch (err) {
    return _json(500, { ok: false, error: String(err && err.message ? err.message : err) });
  }
}

// ---------------- auth ----------------
function _authOrThrow(ts, nonce, sig, body) {
  var secret = PropertiesService.getScriptProperties().getProperty("TC_SHEETS_SECRET") || "";
  if (!secret) throw new Error("missing_script_property:TC_SHEETS_SECRET");
  if (!ts || !nonce || !sig) throw new Error("missing_auth_headers");

  // 时间窗（±5min）
  var now = Date.now();
  var t = Number(ts);
  if (!t || Math.abs(now - t) > 5 * 60 * 1000) throw new Error("timestamp_out_of_window");

  // nonce 去重（最小实现：存 meta.recent_nonce_{nonce}=ts，超过窗口自动覆盖）
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var key = "nonce_" + nonce;
  var seen = _metaGet(ss)[key];
  if (seen) throw new Error("nonce_replay");
  var obj = {}; obj[key] = String(ts);
  _metaSet(ss, obj);

  var msg = ts + "." + nonce + "." + body;
  var calc = _hmacSha256Hex(secret, msg);
  if (calc !== sig) throw new Error("bad_signature");
}

function _hmacSha256Hex(secret, message) {
  var sig = Utilities.computeHmacSha256Signature(message, secret);
  return sig.map(function(b){ var v = (b < 0) ? b + 256 : b; return ("0" + v.toString(16)).slice(-2); }).join("");
}

function _getHeader(e, name) {
  // Apps Script 原生无法可靠读取自定义 header；此处允许客户端把 header 再复制到 query 参数。
  // 推荐客户端同时加：?X-TC-Timestamp=...&X-TC-Nonce=...&X-TC-Signature=...
  var p = (e && e.parameter) ? e.parameter : {};
  return p[name] || p[name.toLowerCase()] || "";
}

// ---------------- sheets helpers ----------------
function _sheet(ss, name) {
  var sh = ss.getSheetByName(name);
  if (!sh) throw new Error("missing_sheet:" + name);
  return sh;
}

function _sheetOrCreate(ss, name) {
  var sh = ss.getSheetByName(name);
  if (sh) return sh;
  return ss.insertSheet(name);
}

function _ensureSchema(ss) {
  // 允许“零手工建表”：缺什么 tab 就创建什么 tab
  _ensureHeaderRow(_sheetOrCreate(ss, "看板"), ["_"]); // 看板不依赖表头，但确保 sheet 存在
  _ensureHeaderRow(_sheetOrCreate(ss, "卡片索引"), [
    "card_key",
    "ts_utc",
    "source_service",
    "card_type",
    "title",
    "update_time",
    "sort_desc",
    "last_update",
    "tg_url",
    "dash_sheet",
    "dash_col_l",
    "dash_col_r",
    "dash_row_y",
    "dash_height",
  ]);
  _ensureHeaderRow(_sheetOrCreate(ss, "卡片字段EAV"), ["card_key", "field_path", "value_text", "value_type"]);
  _ensureHeaderRow(_sheetOrCreate(ss, "卡片明细行"), ["card_key", "row_index", "row_key", "row_json"]);
  _ensureHeaderRow(_sheetOrCreate(ss, "明细字段EAV"), ["card_key", "row_index", "field_path", "value_text", "value_type"]);
  _ensureHeaderRow(_sheetOrCreate(ss, "大字段索引"), ["card_key", "blob_key", "sha256", "mime", "url", "size_chars", "created_at"]);
  _ensureHeaderRow(_sheetOrCreate(ss, "元数据"), ["key", "value"]);
}

function _ensureHeaderRow(sh, headers) {
  var last = sh.getLastRow();
  if (last >= 1) return;
  sh.appendRow(headers);
}

function _metaGet(ss) {
  var sh = _sheet(ss, "元数据");
  var vals = sh.getDataRange().getValues();
  var out = {};
  for (var i = 0; i < vals.length; i++) {
    var k = vals[i][0];
    var v = vals[i][1];
    if (k) out[String(k)] = v;
  }
  if (!out.dashboard_next_row) out.dashboard_next_row = 1;
  if (!out.dashboard_col_l) out.dashboard_col_l = PropertiesService.getScriptProperties().getProperty("TC_DASHBOARD_COL_L") || "A";
  if (!out.dashboard_col_r) out.dashboard_col_r = PropertiesService.getScriptProperties().getProperty("TC_DASHBOARD_COL_R") || "M";
  return out;
}

function _metaSet(ss, kv) {
  var sh = _sheet(ss, "元数据");
  for (var k in kv) {
    var v = kv[k];
    var pos = _findKeyRow(sh, k);
    if (pos < 0) {
      sh.appendRow([k, v]);
    } else {
      sh.getRange(pos, 2).setValue(v);
    }
  }
}

function _findKeyRow(sh, key) {
  var last = sh.getLastRow();
  if (last < 1) return -1;
  var vals = sh.getRange(1, 1, last, 1).getValues();
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]) === String(key)) return i + 1;
  }
  return -1;
}

function _cardsIndexHas(ss, cardKey) {
  var sh = _sheet(ss, "卡片索引");
  // 用 TextFinder 避免拉全列到内存；且要求整格匹配
  var r = sh.getRange("A:A").createTextFinder(String(cardKey)).matchEntireCell(true).findNext();
  if (!r) return false;
  return r.getRow() >= 2; // 跳过表头
}

function _appendCardsIndex(ss, payload, dash) {
  var sh = _sheet(ss, "卡片索引");
  var cardKey = String(payload.card_key || "");
  var tsUtc = String(payload.ts_utc || "");
  var sourceService = String(payload.source_service || "");
  var cardType = String(payload.card_type || "");
  var title = String((payload.header && payload.header.title) ? payload.header.title : "");
  var updateTime = String((payload.header && payload.header.update_time) ? payload.header.update_time : "");
  var sortDesc = String((payload.header && payload.header.sort_desc) ? payload.header.sort_desc : "");
  var lastUpdate = String((payload.params && payload.params.last_update) ? payload.params.last_update : "");
  var tgUrl = String((payload.tg && payload.tg.url) ? payload.tg.url : "");
  sh.appendRow([
    cardKey,
    tsUtc,
    sourceService,
    cardType,
    title,
    updateTime,
    sortDesc,
    lastUpdate,
    tgUrl,
    String(dash && dash.sheet ? dash.sheet : ""),
    String(dash && dash.col_l ? dash.col_l : ""),
    String(dash && dash.col_r ? dash.col_r : ""),
    Number(dash && dash.row_y ? dash.row_y : 0),
    Number(dash && dash.height ? dash.height : 0),
  ]);
}

function _appendCardFieldsEav(ss, payload) {
  var sh = _sheet(ss, "卡片字段EAV");
  var cardKey = String(payload.card_key || "");
  var rows = [];
  _flattenEav(rows, "", payload);
  _appendRows(sh, rows.map(function(it){ return [cardKey, it.path, it.value, it.type]; }), 4);
}

function _appendRowsEav(ss, payload) {
  var rows = (payload.table && payload.table.rows) ? payload.table.rows : [];
  if (!rows || rows.length === 0) return;

  var cardKey = String(payload.card_key || "");
  var shRows = _sheet(ss, "卡片明细行");
  var shEav = _sheet(ss, "明细字段EAV");

  var rowsBatch = [];
  var eavBatch = [];
  for (var i = 0; i < rows.length; i++) {
    var rowObj = rows[i] || {};
    var rowKey = _inferRowKey(rowObj);
    var rowJson = JSON.stringify(rowObj);
    rowsBatch.push([cardKey, i + 1, rowKey, rowJson]);

    var flat = [];
    _flattenEav(flat, "", rowObj);
    for (var j = 0; j < flat.length; j++) {
      eavBatch.push([cardKey, i + 1, flat[j].path, flat[j].value, flat[j].type]);
    }
  }

  _appendRows(shRows, rowsBatch, 4);
  _appendRows(shEav, eavBatch, 5);
}

function _appendBlobsIndex(ss, payload) {
  var cardKey = String(payload.card_key || "");
  var raw = payload.raw || {};
  if (!raw) return;

  var threshold = Number(PropertiesService.getScriptProperties().getProperty("TC_BLOB_THRESHOLD_CHARS") || "20000");
  var folderId = String(PropertiesService.getScriptProperties().getProperty("TC_BLOB_FOLDER_ID") || "");
  var sh = _sheet(ss, "大字段索引");
  var createdAt = new Date().toISOString();

  // raw.telegram_text_full
  if (raw.telegram_text_full != null) {
    var s = String(raw.telegram_text_full);
    if (s.length > threshold) {
      var r1 = _drivePutText(folderId, _safeName("tg_" + cardKey + "_raw_text.txt"), s, "text/plain");
      sh.appendRow([cardKey, "raw.telegram_text_full", r1.sha256, "text/plain", r1.url, s.length, createdAt]);
      raw.telegram_text_full = { blob_url: r1.url, sha256: r1.sha256, size_chars: s.length };
    }
  }

  // raw.payload_json_full
  if (raw.payload_json_full != null) {
    var j = (typeof raw.payload_json_full === "string") ? String(raw.payload_json_full) : JSON.stringify(raw.payload_json_full);
    if (j.length > threshold) {
      var r2 = _drivePutText(folderId, _safeName("tg_" + cardKey + "_raw_json.json"), j, "application/json");
      sh.appendRow([cardKey, "raw.payload_json_full", r2.sha256, "application/json", r2.url, j.length, createdAt]);
      raw.payload_json_full = { blob_url: r2.url, sha256: r2.sha256, size_chars: j.length };
    }
  }

  payload.raw = raw;
}

function _appendRows(sh, rows, cols) {
  if (!rows || rows.length === 0) return;
  var start = sh.getLastRow() + 1;
  sh.getRange(start, 1, rows.length, cols).setValues(rows);
}

function _inferRowKey(rowObj) {
  if (!rowObj) return "";
  if (rowObj["币种"] != null) return String(rowObj["币种"]);
  if (rowObj["symbol"] != null) return String(rowObj["symbol"]);
  if (rowObj["Symbol"] != null) return String(rowObj["Symbol"]);
  return "";
}

function _flattenEav(out, prefix, val) {
  var t = _valueType(val);
  if (t === "null" || t === "bool" || t === "number" || t === "string") {
    out.push({ path: prefix || "_", value: String(val == null ? "" : val), type: t });
    return;
  }

  if (t === "array") {
    out.push({ path: prefix || "_", value: "", type: "array" });
    for (var i = 0; i < val.length; i++) {
      _flattenEav(out, (prefix ? prefix : "_") + "[" + i + "]", val[i]);
    }
    return;
  }

  // object
  out.push({ path: prefix || "_", value: "", type: "object" });
  for (var k in val) {
    if (!val.hasOwnProperty(k)) continue;
    var next = prefix ? (prefix + "." + k) : k;
    _flattenEav(out, next, val[k]);
  }
}

function _valueType(v) {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return "array";
  var tp = typeof v;
  if (tp === "boolean") return "bool";
  if (tp === "number") return "number";
  if (tp === "string") return "string";
  return "object";
}

function _sha256Hex(text) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8);
  return bytes.map(function(b){ var v = (b < 0) ? b + 256 : b; return ("0" + v.toString(16)).slice(-2); }).join("");
}

function _safeName(name) {
  return String(name).replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 180);
}

function _drivePutText(folderId, filename, text, mime) {
  var folder = folderId ? DriveApp.getFolderById(folderId) : DriveApp.getRootFolder();
  var file = folder.createFile(filename, text, mime);
  // 公开只读看板的典型策略：blob 用“知道链接即可读”
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { url: file.getUrl(), sha256: _sha256Hex(text) };
}

function _inferRowsCount(payload) {
  var rows = (payload.table && payload.table.rows) ? payload.table.rows : [];
  return rows && rows.length ? rows.length : 0;
}

function _renderDashboard(ss, payload, y, colL, colR) {
  var sh = _sheet(ss, "看板");
  var colLNum = sh.getRange(colL + "1").getColumn();
  var colRNum = sh.getRange(colR + "1").getColumn();
  var width = colRNum - colLNum + 1;

  // 0) title/update/sort：合并行
  var title = (payload.header && payload.header.title) ? payload.header.title : "";
  var update = (payload.header && payload.header.update_time) ? ("⏰ 更新 " + payload.header.update_time) : "";
  var sort = (payload.header && payload.header.sort_desc) ? ("📊 排序 " + payload.header.sort_desc) : "";
  sh.getRange(y, colLNum, 1, width).merge().setValue(title);
  sh.getRange(y + 1, colLNum, 1, width).merge().setValue(update);
  sh.getRange(y + 2, colLNum, 1, width).merge().setValue(sort);

  // 1) table header + rows：真实列
  var columns = (payload.table && payload.table.columns) ? payload.table.columns : [];
  var rows = (payload.table && payload.table.rows) ? payload.table.rows : [];

  if (columns.length > 0) {
    sh.getRange(y + 3, colLNum, 1, Math.min(columns.length, width)).setValues([columns.slice(0, width)]);
    for (var i = 0; i < rows.length; i++) {
      var rowObj = rows[i];
      var line = [];
      for (var c = 0; c < columns.length && c < width; c++) {
        var key = columns[c];
        line.push(rowObj[key] != null ? String(rowObj[key]) : "");
      }
      sh.getRange(y + 4 + i, colLNum, 1, Math.min(line.length, width)).setValues([line]);
    }
  }

  // 2) hint/last_update：合并行
  var hint = (payload.hint && payload.hint.text) ? ("💡 " + payload.hint.text) : "";
  sh.getRange(y + 4 + rows.length, colLNum, 1, width).merge().setValue(hint);
  sh.getRange(y + 5 + rows.length, colLNum, 1, width).merge().setValue("⏰ 最后更新 " + (payload.params && payload.params.last_update ? payload.params.last_update : ""));
  // y+6+N 空行留给下一块
}

function _json(code, obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
```

## 4) 注意事项（踩坑提醒）
- Apps Script 对自定义 Header 的读取不稳定：建议客户端把签名参数同时放 query（上面的 `_getHeader` 已支持）。
- 真正“无遗漏”需要对 payload 做递归 flatten，写入 `卡片字段EAV`/`明细字段EAV`，并对超长 raw 走 Drive blob 引用。
