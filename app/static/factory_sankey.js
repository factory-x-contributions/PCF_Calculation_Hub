/* Factory Sankey Diagram – Building → Machine → Idle|Production → Energy Type.
 * Pure SVG, no external dependencies. Called via window.renderFactorySankey(). */

(function () {
  'use strict';

  var PALETTE = ['#0d9488', '#2563eb', '#c2410c', '#7c3aed', '#d97706', '#059669', '#dc2626', '#4f46e5'];
  var ENERGY_CLR = '#64748b';
  var IDLE_SPLIT_CLR = '#0f766e';
  var PROD_SPLIT_CLR = '#c2410c';
  var NODE_W = 20;
  var NODE_GAP = 22;
  var MIN_NODE_H = 6;
  var MIN_LINK_W = 2;
  var LEFT_PAD = 140;
  var RIGHT_PAD = 120;
  var TOP_PAD = 38;
  var BOT_PAD = 16;
  var NUM_COLS = 4;

  function fmtKwh(v) {
    if (v >= 1e6) return (v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '\u2009GWh';
    if (v >= 1000) return (v / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 }) + '\u2009MWh';
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + '\u2009kWh';
  }

  function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; }
  function svgEl(tag) { return document.createElementNS('http://www.w3.org/2000/svg', tag); }

  /* ── graph construction ── */
  function buildGraph(raw) {
    var nodes = [], links = [], nMap = {}, ci = 0;

    function ensure(id, label, col, color) {
      if (nMap[id]) return nMap[id];
      var n = { id: id, label: label, col: col, color: color, val: 0, h: 0, x: 0, y: 0, srcVal: 0, tgtVal: 0 };
      nMap[id] = n;
      nodes.push(n);
      return n;
    }

    Object.keys(raw).forEach(function (bId) {
      var bc = PALETTE[ci++ % PALETTE.length];
      ensure('b:' + bId, bId, 0, bc);

      Object.keys(raw[bId]).forEach(function (mId) {
        var mData = raw[bId][mId];
        var mNid = 'm:' + bId + '/' + mId;
        var mTotal = 0;
        var mLabel = mId;
        Object.keys(mData).forEach(function (eId) {
          var block = mData[eId];
          if (block && typeof block === 'object' && block.machine_name) {
            var mn = String(block.machine_name).trim();
            if (mn) mLabel = mn;
          }
          mTotal += (block.idle_consumption_total_kwh || 0) + (block.prod_consumption_total_kwh || 0);
        });
        if (mTotal <= 0) return;

        ensure(mNid, mLabel, 1, bc);
        links.push({ src: 'b:' + bId, tgt: mNid, value: mTotal, color: bc });

        Object.keys(mData).forEach(function (eId) {
          var block = mData[eId];
          if (!block || typeof block !== 'object') return;
          var idleK = block.idle_consumption_total_kwh || 0;
          var prodK = block.prod_consumption_total_kwh || 0;
          var eLabel = eId.charAt(0).toUpperCase() + eId.slice(1);
          ensure('e:' + eId, eLabel, 3, ENERGY_CLR);

          if (idleK > 0) {
            var idleId = 'i:' + bId + '/' + mId + '/' + eId;
            ensure(idleId, 'Idle', 2, IDLE_SPLIT_CLR);
            links.push({ src: mNid, tgt: idleId, value: idleK, color: bc });
            links.push({ src: idleId, tgt: 'e:' + eId, value: idleK, color: bc });
          }
          if (prodK > 0) {
            var prodId = 'p:' + bId + '/' + mId + '/' + eId;
            ensure(prodId, 'Production', 2, PROD_SPLIT_CLR);
            links.push({ src: mNid, tgt: prodId, value: prodK, color: bc });
            links.push({ src: prodId, tgt: 'e:' + eId, value: prodK, color: bc });
          }
        });
      });
    });

    nodes.forEach(function (n) { n.srcVal = 0; n.tgtVal = 0; });
    links.forEach(function (l) {
      nMap[l.src].srcVal += l.value;
      nMap[l.tgt].tgtVal += l.value;
    });
    nodes.forEach(function (n) { n.val = Math.max(n.srcVal, n.tgtVal); });

    return { nodes: nodes, links: links, nMap: nMap };
  }

  /* ── layout ── */
  function doLayout(g, W, H) {
    var cols = [[], [], [], []];
    g.nodes.forEach(function (n) { if (n.val > 0) cols[n.col].push(n); });
    cols.forEach(function (c) { c.sort(function (a, b) { return b.val - a.val; }); });

    var innerW = W - LEFT_PAD - RIGHT_PAD;
    var colSpacing = (innerW - NODE_W) / (NUM_COLS - 1);
    var colX = [];
    for (var i = 0; i < NUM_COLS; i++) colX.push(LEFT_PAD + i * colSpacing);

    var usableH = H - TOP_PAD - BOT_PAD;

    cols.forEach(function (col, ci) {
      if (!col.length) return;
      var totalVal = col.reduce(function (s, n) { return s + n.val; }, 0);
      var gaps = Math.max(0, col.length - 1) * NODE_GAP;
      var valSpace = Math.max(0, usableH - gaps);
      var y = TOP_PAD;
      col.forEach(function (n) {
        n.x = colX[ci];
        n.h = totalVal > 0 ? Math.max(MIN_NODE_H, (n.val / totalVal) * valSpace) : MIN_NODE_H;
        n.y = y;
        y += n.h + NODE_GAP;
      });
    });

    /* source-side link routing */
    var bySource = {};
    g.links.forEach(function (l) { (bySource[l.src] = bySource[l.src] || []).push(l); });
    Object.keys(bySource).forEach(function (nid) {
      bySource[nid].sort(function (a, b) { return g.nMap[a.tgt].y - g.nMap[b.tgt].y; });
      var n = g.nMap[nid], off = 0;
      bySource[nid].forEach(function (l) {
        var lh = n.val > 0 ? Math.max(MIN_LINK_W, (l.value / n.val) * n.h) : MIN_LINK_W;
        l.sy = n.y + off + lh / 2;
        l.sw = lh;
        off += lh;
      });
    });

    /* target-side link routing */
    var byTarget = {};
    g.links.forEach(function (l) { (byTarget[l.tgt] = byTarget[l.tgt] || []).push(l); });
    Object.keys(byTarget).forEach(function (nid) {
      byTarget[nid].sort(function (a, b) { return g.nMap[a.src].y - g.nMap[b.src].y; });
      var n = g.nMap[nid], off = 0;
      byTarget[nid].forEach(function (l) {
        var lh = n.val > 0 ? Math.max(MIN_LINK_W, (l.value / n.val) * n.h) : MIN_LINK_W;
        l.ty = n.y + off + lh / 2;
        l.tw = lh;
        off += lh;
      });
    });
  }

  /* ── cubic-bezier link path ── */
  function linkPath(l, nMap) {
    var sx = nMap[l.src].x + NODE_W, tx = nMap[l.tgt].x;
    var mx = (sx + tx) / 2;
    var st = l.sy - l.sw / 2, sb = l.sy + l.sw / 2;
    var tt = l.ty - l.tw / 2, tb = l.ty + l.tw / 2;
    return 'M' + sx + ',' + st +
      'C' + mx + ',' + st + ' ' + mx + ',' + tt + ' ' + tx + ',' + tt +
      'L' + tx + ',' + tb +
      'C' + mx + ',' + tb + ' ' + mx + ',' + sb + ' ' + sx + ',' + sb + 'Z';
  }

  /* ── render ── */
  window.renderFactorySankey = function (containerId, rawData) {
    var el = document.getElementById(containerId);
    if (!el) return;

    if (!Object.keys(rawData).length) {
      el.innerHTML = '<p class="fed-sankey-empty">No data to visualize.</p>';
      return;
    }

    var g = buildGraph(rawData);
    if (!g.links.length) {
      el.innerHTML = '<p class="fed-sankey-empty">No energy flows to visualize.</p>';
      return;
    }

    var cw = el.parentElement ? el.parentElement.getBoundingClientRect().width - 48 : 700;
    var W = Math.max(720, Math.min(1280, cw));
    var maxPerCol = Math.max.apply(null, [0, 1, 2, 3].map(function (c) {
      return g.nodes.filter(function (n) { return n.col === c && n.val > 0; }).length;
    }));
    var H = Math.max(280, maxPerCol * 64 + TOP_PAD + BOT_PAD);

    doLayout(g, W, H);

    el.innerHTML = '';
    el.style.position = 'relative';

    var svg = svgEl('svg');
    svg.setAttribute('width', '100%');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('class', 'fed-sankey-svg');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    /* ── tooltip ── */
    var tip = document.createElement('div');
    tip.className = 'fed-sankey-tooltip';
    el.appendChild(tip);

    function showTip(html, e) {
      tip.innerHTML = html;
      tip.style.display = 'block';
      moveTip(e);
    }
    function moveTip(e) {
      var cr = el.getBoundingClientRect();
      var x = e.clientX - cr.left + 14;
      var y = e.clientY - cr.top - 14;
      if (x + 200 > cr.width) x = e.clientX - cr.left - 200;
      if (y < 0) y = 4;
      tip.style.left = x + 'px';
      tip.style.top = y + 'px';
    }
    function hideTip() { tip.style.display = 'none'; }

    /* ── column headers ── */
    var headerGroup = svgEl('g');
    var colLabels = ['Buildings', 'Machines', 'Idle / Production', 'Energy types'];
    var innerW = W - LEFT_PAD - RIGHT_PAD;
    var colSpacing = (innerW - NODE_W) / (NUM_COLS - 1);
    var colCX = [];
    for (var hi = 0; hi < NUM_COLS; hi++) {
      colCX.push(LEFT_PAD + hi * colSpacing + NODE_W / 2);
    }
    colLabels.forEach(function (lbl, i) {
      var t = svgEl('text');
      t.setAttribute('x', colCX[i]);
      t.setAttribute('y', 16);
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('class', 'fed-sankey-col-header');
      t.textContent = lbl;
      headerGroup.appendChild(t);
    });
    svg.appendChild(headerGroup);

    /* ── links ── */
    var linkGroup = svgEl('g');
    g.links.forEach(function (l) {
      var p = svgEl('path');
      p.setAttribute('d', linkPath(l, g.nMap));
      p.setAttribute('fill', l.color);
      p.setAttribute('fill-opacity', '0.28');
      p.setAttribute('class', 'fed-sankey-link');
      p.dataset.src = l.src;
      p.dataset.tgt = l.tgt;

      p.addEventListener('mouseenter', function (e) {
        p.setAttribute('fill-opacity', '0.6');
        showTip(
          '<strong>' + g.nMap[l.src].label + '</strong> → <strong>' + g.nMap[l.tgt].label + '</strong><br>' + fmtKwh(l.value),
          e
        );
      });
      p.addEventListener('mousemove', moveTip);
      p.addEventListener('mouseleave', function () { p.setAttribute('fill-opacity', '0.28'); hideTip(); });
      linkGroup.appendChild(p);
    });
    svg.appendChild(linkGroup);

    /* ── nodes + labels ── */
    var nodeGroup = svgEl('g');
    g.nodes.forEach(function (n) {
      if (n.val <= 0) return;

      var r = svgEl('rect');
      r.setAttribute('x', n.x);
      r.setAttribute('y', n.y);
      r.setAttribute('width', NODE_W);
      r.setAttribute('height', n.h);
      r.setAttribute('rx', 3);
      r.setAttribute('fill', n.color);
      r.setAttribute('class', 'fed-sankey-node');
      r.dataset.nid = n.id;

      r.addEventListener('mouseenter', function (e) {
        svg.querySelectorAll('.fed-sankey-link').forEach(function (p) {
          p.setAttribute('fill-opacity', (p.dataset.src === n.id || p.dataset.tgt === n.id) ? '0.6' : '0.06');
        });
        showTip('<strong>' + n.label + '</strong><br>' + fmtKwh(n.val), e);
      });
      r.addEventListener('mousemove', moveTip);
      r.addEventListener('mouseleave', function () {
        svg.querySelectorAll('.fed-sankey-link').forEach(function (p) { p.setAttribute('fill-opacity', '0.28'); });
        hideTip();
      });
      nodeGroup.appendChild(r);

      /* name label */
      var t = svgEl('text');
      t.setAttribute('class', 'fed-sankey-label');
      t.style.pointerEvents = 'none';

      if (n.col === 0) {
        t.setAttribute('x', n.x - 8);
        t.setAttribute('text-anchor', 'end');
        t.setAttribute('y', n.y + n.h / 2);
        t.setAttribute('dy', '0.35em');
      } else if (n.col === 3) {
        t.setAttribute('x', n.x + NODE_W + 8);
        t.setAttribute('text-anchor', 'start');
        t.setAttribute('y', n.y + n.h / 2);
        t.setAttribute('dy', '0.35em');
      } else {
        t.setAttribute('x', n.x + NODE_W / 2);
        t.setAttribute('text-anchor', 'middle');
        t.setAttribute('y', n.y - 6);
      }
      t.textContent = trunc(n.label, 22);
      nodeGroup.appendChild(t);

      /* value sub-label (buildings and energy types only) */
      if (n.col === 0 || n.col === 3) {
        var vt = svgEl('text');
        vt.setAttribute('class', 'fed-sankey-val');
        vt.style.pointerEvents = 'none';
        if (n.col === 0) {
          vt.setAttribute('x', n.x - 8);
          vt.setAttribute('text-anchor', 'end');
        } else {
          vt.setAttribute('x', n.x + NODE_W + 8);
          vt.setAttribute('text-anchor', 'start');
        }
        vt.setAttribute('y', n.y + n.h / 2 + 14);
        vt.textContent = fmtKwh(n.val);
        nodeGroup.appendChild(vt);
      }
    });
    svg.appendChild(nodeGroup);

    el.appendChild(svg);
  };
})();
