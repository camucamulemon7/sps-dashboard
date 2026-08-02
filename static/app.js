(function () {
  'use strict';

  var state = { config: null, range: null, timer: null, countdown: 0, loading: false };

  function byId(id) { return document.getElementById(id); }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function text(tag, className, value) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    node.appendChild(document.createTextNode(value));
    return node;
  }
  function requestJson(url, done) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) { return; }
      if (xhr.status >= 200 && xhr.status < 300) {
        try { done(null, JSON.parse(xhr.responseText)); }
        catch (error) { done(error); }
      } else {
        var message = 'HTTP ' + xhr.status;
        try { message = JSON.parse(xhr.responseText).detail || message; } catch (ignore) {}
        done(new Error(message));
      }
    };
    xhr.onerror = function () { done(new Error('ネットワークエラー')); };
    xhr.send();
  }
  function formatNumber(value) {
    return Math.round(Number(value || 0)).toLocaleString('ja-JP');
  }
  function formatCompact(value) {
    value = Number(value || 0);
    if (value >= 1000000) { return (value / 1000000).toFixed(1) + 'M'; }
    if (value >= 1000) { return (value / 1000).toFixed(1) + 'K'; }
    return formatNumber(value);
  }
  function formatCost(value) { return '$' + Number(value || 0).toFixed(4); }
  function formatLatency(value) {
    value = Number(value || 0);
    return value >= 1000 ? (value / 1000).toFixed(2) + 's' : Math.round(value) + 'ms';
  }
  function rangeLabel(value) {
    if (value === '24h') { return '24時間'; }
    if (value === '7d') { return '7日'; }
    if (value === '30d') { return '30日'; }
    return value;
  }
  function setError(message) {
    var banner = byId('error-banner');
    banner.className = message ? 'error-banner' : 'error-banner hidden';
    banner.textContent = message || '';
  }
  function currentDashboardUrl() {
    return window.location.href.split('#')[0].split('?')[0];
  }
  function iframeMarkup(url) {
    return '<iframe\n  src="' + url + '"\n  title="LLM Usage Dashboard"\n  width="100%"\n  height="800"\n  frameborder="0">\n</iframe>';
  }
  function copyValue(node, label) {
    function complete(ok) {
      byId('copy-status').textContent = ok ? label + 'をコピーしました' : 'コピーできませんでした。選択して手動でコピーしてください。';
    }
    if (window.navigator.clipboard && window.navigator.clipboard.writeText) {
      window.navigator.clipboard.writeText(node.value).then(function () { complete(true); }, function () { fallbackCopy(); });
      return;
    }
    fallbackCopy();
    function fallbackCopy() {
      node.focus(); node.select();
      try { complete(document.execCommand('copy')); } catch (error) { complete(false); }
    }
  }
  function openEmbedModal() {
    var url = currentDashboardUrl();
    byId('public-url').value = url;
    byId('iframe-code').value = iframeMarkup(url);
    byId('preview-link').href = url;
    byId('copy-status').textContent = '';
    byId('embed-modal').className = 'modal';
    byId('embed-modal').setAttribute('aria-hidden', 'false');
    document.body.className = 'modal-open';
    byId('embed-close').focus();
  }
  function closeEmbedModal() {
    byId('embed-modal').className = 'modal hidden';
    byId('embed-modal').setAttribute('aria-hidden', 'true');
    document.body.className = '';
    byId('embed-button').focus();
  }
  function initEmbedDialog() {
    byId('embed-button').onclick = openEmbedModal;
    byId('embed-close').onclick = closeEmbedModal;
    byId('copy-url').onclick = function () { copyValue(byId('public-url'), '公開URL'); };
    byId('copy-iframe').onclick = function () { copyValue(byId('iframe-code'), 'iframeコード'); };
    byId('embed-modal').onclick = function (event) {
      if (event.target.getAttribute && event.target.getAttribute('data-close-modal') === 'true') { closeEmbedModal(); }
    };
    document.onkeydown = function (event) {
      event = event || window.event;
      if ((event.key === 'Escape' || event.keyCode === 27) && byId('embed-modal').className.indexOf('hidden') === -1) { closeEmbedModal(); }
    };
  }
  function renderRanges() {
    var holder = byId('range-buttons');
    clear(holder);
    for (var i = 0; i < state.config.allowed_ranges.length; i += 1) {
      (function (rangeValue) {
        var button = text('button', rangeValue === state.range ? 'active' : '', rangeLabel(rangeValue));
        button.type = 'button';
        button.onclick = function () { state.range = rangeValue; renderRanges(); loadDashboard(); };
        holder.appendChild(button);
      }(state.config.allowed_ranges[i]));
    }
  }
  function renderSummary(summary) {
    var cards = [
      ['リクエスト', formatNumber(summary.requests), 'Trace単位'],
      ['合計コスト', formatCost(summary.total_cost), '米ドル'],
      ['合計トークン', formatCompact(summary.total_tokens), '入力 ' + formatCompact(summary.input_tokens) + ' / 出力 ' + formatCompact(summary.output_tokens)],
      ['平均レイテンシー', formatLatency(summary.average_latency_ms), 'P95 ' + formatLatency(summary.p95_latency_ms)],
      ['エラー率', (Number(summary.error_rate || 0) * 100).toFixed(1) + '%', 'LLM関連 ' + formatNumber(summary.observations) + '件']
    ];
    var holder = byId('summary-cards');
    clear(holder);
    for (var i = 0; i < cards.length; i += 1) {
      var card = document.createElement('article');
      card.className = 'metric-card';
      card.appendChild(text('p', 'metric-label', cards[i][0]));
      card.appendChild(text('p', 'metric-value', cards[i][1]));
      card.appendChild(text('p', 'metric-note', cards[i][2]));
      holder.appendChild(card);
    }
  }
  function renderTrend(points) {
    var holder = byId('trend-chart');
    var legend = byId('trend-legend');
    clear(holder);
    clear(legend);
    if (!points.length) { holder.appendChild(text('p', 'empty', '対象期間のデータがありません')); return; }
    var palette = ['#1f4e79', '#2f75b5', '#70ad47', '#ed7d31', '#8064a2', '#5b9bd5', '#a5a5a5', '#ffc000'];
    var modelTotals = {}, hasBreakdown = false;
    for (var p = 0; p < points.length; p += 1) {
      var modelTokens = points[p].model_tokens || {};
      for (var modelName in modelTokens) {
        if (Object.prototype.hasOwnProperty.call(modelTokens, modelName)) {
          hasBreakdown = true;
          modelTotals[modelName] = Number(modelTotals[modelName] || 0) + Number(modelTokens[modelName] || 0);
        }
      }
    }
    if (!hasBreakdown) { modelTotals['合計'] = 1; }
    var modelNames = [];
    for (var name in modelTotals) {
      if (Object.prototype.hasOwnProperty.call(modelTotals, name) && modelTotals[name] > 0) { modelNames.push(name); }
    }
    modelNames.sort(function (a, b) { return modelTotals[b] - modelTotals[a]; });
    var visibleModels = modelNames.slice(0, 7);
    if (modelNames.length > 7) { visibleModels.push('その他'); }
    for (var l = 0; l < visibleModels.length; l += 1) {
      var item = document.createElement('span'); item.className = 'legend-item';
      var swatch = document.createElement('span'); swatch.className = 'legend-swatch';
      swatch.style.backgroundColor = palette[l % palette.length]; item.appendChild(swatch);
      item.appendChild(document.createTextNode(visibleModels[l])); legend.appendChild(item);
    }
    function seriesValue(point, seriesName) {
      if (!hasBreakdown) { return seriesName === '合計' ? Number(point.total_tokens || 0) : 0; }
      if (seriesName !== 'その他') { return Number((point.model_tokens || {})[seriesName] || 0); }
      var other = 0;
      for (var key in point.model_tokens) {
        if (Object.prototype.hasOwnProperty.call(point.model_tokens, key) && visibleModels.indexOf(key) === -1) {
          other += Number(point.model_tokens[key] || 0);
        }
      }
      return other;
    }
    var width = 900, height = 270, padX = 48, top = 20, bottom = 224, max = 1;
    for (var i = 0; i < points.length; i += 1) { max = Math.max(max, Number(points[i].total_tokens || 0)); }
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', '時間別トークン利用量');
    for (i = 0; i <= 4; i += 1) {
      var gridY = top + i * (bottom - top) / 4;
      var grid = document.createElementNS(svg.namespaceURI, 'line');
      grid.setAttribute('x1', padX); grid.setAttribute('x2', width - padX);
      grid.setAttribute('y1', gridY); grid.setAttribute('y2', gridY);
      grid.setAttribute('class', 'chart-grid'); svg.appendChild(grid);
      var scale = document.createElementNS(svg.namespaceURI, 'text');
      scale.setAttribute('x', padX - 7); scale.setAttribute('y', gridY + 4);
      scale.setAttribute('class', 'chart-scale'); scale.setAttribute('text-anchor', 'end');
      scale.appendChild(document.createTextNode(formatCompact(max * (4 - i) / 4)));
      svg.appendChild(scale);
    }
    var plotWidth = width - padX * 2;
    var step = plotWidth / points.length;
    var barWidth = Math.max(3, step * 0.62);
    var detail = text('p', 'chart-detail', '棒にカーソルを合わせると時間別の値を確認できます');
    function pointLabel(point) {
      var date = new Date(point.timestamp);
      var month = date.getMonth() + 1, day = date.getDate(), hour = date.getHours();
      return month + '/' + day + ' ' + (hour < 10 ? '0' : '') + hour + ':00';
    }
    for (i = 0; i < points.length; i += 1) {
      (function (point, index) {
        var value = Number(point.total_tokens || 0);
        var barBottom = bottom;
        if (!value) {
          var emptyBar = document.createElementNS(svg.namespaceURI, 'rect');
          emptyBar.setAttribute('x', padX + index * step + (step - barWidth) / 2);
          emptyBar.setAttribute('y', bottom - 1); emptyBar.setAttribute('width', barWidth);
          emptyBar.setAttribute('height', 1); emptyBar.setAttribute('class', 'chart-bar-empty');
          svg.appendChild(emptyBar);
        }
        for (var seriesIndex = 0; seriesIndex < visibleModels.length; seriesIndex += 1) {
          var seriesName = visibleModels[seriesIndex];
          var segmentValue = seriesValue(point, seriesName);
          if (!segmentValue) { continue; }
          var segmentHeight = segmentValue / max * (bottom - top);
          var bar = document.createElementNS(svg.namespaceURI, 'rect');
          bar.setAttribute('x', padX + index * step + (step - barWidth) / 2);
          bar.setAttribute('y', barBottom - segmentHeight); bar.setAttribute('width', barWidth);
          bar.setAttribute('height', segmentHeight); bar.setAttribute('class', 'chart-bar');
          bar.style.fill = palette[seriesIndex % palette.length]; bar.setAttribute('tabindex', '0');
          var message = pointLabel(point) + ' — ' + seriesName + ': ' + formatNumber(segmentValue) + ' tokens（合計 ' + formatNumber(value) + ' / ' + formatNumber(point.observations) + ' calls）';
          var title = document.createElementNS(svg.namespaceURI, 'title');
          title.appendChild(document.createTextNode(message)); bar.appendChild(title);
          bar.onmouseover = bar.onfocus = (function (detailMessage) {
            return function () { detail.textContent = detailMessage; };
          }(message));
          svg.appendChild(bar); barBottom -= segmentHeight;
        }
        var labelEvery = Math.max(1, Math.ceil(points.length / 8));
        if (index % labelEvery === 0 || index === points.length - 1) {
          var axisLabel = document.createElementNS(svg.namespaceURI, 'text');
          axisLabel.setAttribute('x', padX + index * step + step / 2);
          axisLabel.setAttribute('y', bottom + 22); axisLabel.setAttribute('text-anchor', 'middle');
          axisLabel.setAttribute('class', 'chart-axis-label');
          axisLabel.appendChild(document.createTextNode(pointLabel(point)));
          svg.appendChild(axisLabel);
        }
      }(points[i], i));
    }
    holder.appendChild(svg); holder.appendChild(detail);
  }
  function renderModels(models) {
    var holder = byId('model-list'); clear(holder);
    if (!models.length) { holder.appendChild(text('p', 'empty', 'モデルデータがありません')); return; }
    var visible = [];
    for (var modelIndex = 0; modelIndex < models.length; modelIndex += 1) {
      if (Number(models[modelIndex].total_tokens || 0) > 0) { visible.push(models[modelIndex]); }
    }
    if (!visible.length) { visible = models; }
    var max = 1;
    for (var i = 0; i < visible.length; i += 1) { max = Math.max(max, Number(visible[i].total_tokens || 0)); }
    for (i = 0; i < Math.min(visible.length, 10); i += 1) {
      var row = document.createElement('div'); row.className = 'bar-row';
      var top = document.createElement('div'); top.className = 'bar-top';
      top.appendChild(text('span', 'bar-name', visible[i].name));
      top.appendChild(text('span', 'bar-value', formatCompact(visible[i].total_tokens) + ' tokens'));
      row.appendChild(top);
      var track = document.createElement('div'); track.className = 'bar-track';
      var fill = document.createElement('div'); fill.className = 'bar-fill';
      fill.style.width = Math.max(2, Number(visible[i].total_tokens || 0) / max * 100) + '%';
      track.appendChild(fill); row.appendChild(track); holder.appendChild(row);
    }
  }
  function renderUsers(users) {
    var body = byId('user-table'); clear(body);
    if (!users.length) {
      var emptyRow = document.createElement('tr'); var cell = text('td', 'empty', 'ユーザーデータがありません');
      cell.colSpan = 4; emptyRow.appendChild(cell); body.appendChild(emptyRow); return;
    }
    for (var i = 0; i < Math.min(users.length, 20); i += 1) {
      var row = document.createElement('tr');
      row.appendChild(text('td', 'user-id', users[i].user_id));
      row.appendChild(text('td', '', formatNumber(users[i].requests)));
      row.appendChild(text('td', '', formatCompact(users[i].total_tokens)));
      row.appendChild(text('td', '', formatCost(users[i].total_cost)));
      body.appendChild(row);
    }
  }
  function renderStatus(data) {
    var source = data.sources && data.sources.length ? data.sources[0] : { status: 'unknown', name: 'unknown' };
    var pill = byId('source-status');
    pill.className = 'status-pill status-' + source.status;
    var statusLabels = { healthy: '正常', degraded: '一部取得', unknown: '不明' };
    pill.textContent = source.name + ': ' + (statusLabels[source.status] || source.status);
    byId('last-updated').textContent = '最終更新: ' + new Date(data.generated_at).toLocaleString('ja-JP');
    byId('data-window').textContent = data.from_timestamp + ' — ' + data.to_timestamp;
    setError(source.message || '');
  }
  function render(data) {
    renderSummary(data.summary); renderTrend(data.trend); renderModels(data.models);
    renderUsers(data.users); renderStatus(data);
  }
  function loadDashboard() {
    if (state.loading) { return; }
    state.loading = true; byId('refresh-button').disabled = true; setError('');
    requestJson('/api/dashboard?range=' + encodeURIComponent(state.range), function (error, data) {
      state.loading = false; byId('refresh-button').disabled = false;
      if (error) { setError('データを取得できません: ' + error.message); return; }
      state.countdown = state.config.refresh_seconds; render(data);
    });
  }
  function tick() {
    if (!state.config) { return; }
    state.countdown -= 1;
    if (state.countdown <= 0) { loadDashboard(); state.countdown = state.config.refresh_seconds; }
    byId('next-refresh').textContent = '次回更新: ' + Math.max(0, state.countdown) + '秒';
  }
  function init() {
    requestJson('/api/config', function (error, config) {
      if (error) { setError('設定を取得できません: ' + error.message); return; }
      state.config = config; state.range = config.default_range; state.countdown = config.refresh_seconds;
      document.title = config.title; byId('dashboard-title').textContent = config.title;
      renderRanges(); byId('refresh-button').onclick = loadDashboard;
      initEmbedDialog();
      loadDashboard(); state.timer = window.setInterval(tick, 1000);
    });
  }
  init();
}());
