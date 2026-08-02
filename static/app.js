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
      ['リクエスト', formatNumber(summary.requests), 'distinct traces'],
      ['合計コスト', formatCost(summary.total_cost), 'USD'],
      ['合計トークン', formatCompact(summary.total_tokens), 'in ' + formatCompact(summary.input_tokens) + ' / out ' + formatCompact(summary.output_tokens)],
      ['平均レイテンシー', formatLatency(summary.average_latency_ms), 'P95 ' + formatLatency(summary.p95_latency_ms)],
      ['エラー率', (Number(summary.error_rate || 0) * 100).toFixed(1) + '%', formatNumber(summary.observations) + ' observations']
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
    clear(holder);
    if (!points.length) { holder.appendChild(text('p', 'empty', '対象期間のデータがありません')); return; }
    var width = 900, height = 250, padX = 46, padY = 28, max = 1;
    for (var i = 0; i < points.length; i += 1) { max = Math.max(max, Number(points[i].total_tokens || 0)); }
    var coords = [];
    for (i = 0; i < points.length; i += 1) {
      var x = points.length === 1 ? width / 2 : padX + i * (width - padX * 2) / (points.length - 1);
      var y = height - padY - Number(points[i].total_tokens || 0) / max * (height - padY * 2);
      coords.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'トークン利用量の推移');
    var baseline = document.createElementNS(svg.namespaceURI, 'line');
    baseline.setAttribute('x1', padX); baseline.setAttribute('x2', width - padX);
    baseline.setAttribute('y1', height - padY); baseline.setAttribute('y2', height - padY);
    baseline.setAttribute('class', 'chart-grid'); svg.appendChild(baseline);
    var area = document.createElementNS(svg.namespaceURI, 'polygon');
    area.setAttribute('points', padX + ',' + (height - padY) + ' ' + coords.join(' ') + ' ' + (width - padX) + ',' + (height - padY));
    area.setAttribute('class', 'chart-area'); svg.appendChild(area);
    var line = document.createElementNS(svg.namespaceURI, 'polyline');
    line.setAttribute('points', coords.join(' ')); line.setAttribute('class', 'chart-line'); svg.appendChild(line);
    holder.appendChild(svg);
    var labels = document.createElement('div'); labels.className = 'chart-labels';
    labels.appendChild(text('span', '', points[0].timestamp));
    labels.appendChild(text('span', '', formatCompact(max) + ' tokens peak'));
    labels.appendChild(text('span', '', points[points.length - 1].timestamp));
    holder.appendChild(labels);
  }
  function renderModels(models) {
    var holder = byId('model-list'); clear(holder);
    if (!models.length) { holder.appendChild(text('p', 'empty', 'モデルデータがありません')); return; }
    var max = 1;
    for (var i = 0; i < models.length; i += 1) { max = Math.max(max, Number(models[i].total_tokens || 0)); }
    for (i = 0; i < Math.min(models.length, 10); i += 1) {
      var row = document.createElement('div'); row.className = 'bar-row';
      var top = document.createElement('div'); top.className = 'bar-top';
      top.appendChild(text('span', 'bar-name', models[i].name));
      top.appendChild(text('span', 'bar-value', formatCompact(models[i].total_tokens) + ' tokens'));
      row.appendChild(top);
      var track = document.createElement('div'); track.className = 'bar-track';
      var fill = document.createElement('div'); fill.className = 'bar-fill';
      fill.style.width = Math.max(2, Number(models[i].total_tokens || 0) / max * 100) + '%';
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
    pill.textContent = source.name + ': ' + source.status;
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
