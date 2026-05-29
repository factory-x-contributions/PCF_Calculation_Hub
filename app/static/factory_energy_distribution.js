/* SPDX-FileCopyrightText: Copyright Siemens 2026 */
/* SPDX-License-Identifier: Apache-2.0 */
/* Factory Energy Distribution – same accordion pattern as work order records.
 * Data: app/data/data_base_factory.json via GET api/factory_energy_distribution */

var _fedCachedData = null;

var FRIENDLY_KEYS = {
  idle_consumption_total_kwh: 'Idle consumption (total)',
  prod_consumption_total_kwh: 'Production consumption (total)',
  total_time: 'Total time',
  total_idle_time: 'Total idle time',
  work_orders_duration: 'Work orders (duration)',
  idle_consumption_rate: 'Idle consumption rate',
  prod_consumption_rate: 'Production consumption rate',
  publication_datetime: 'Publication time'
};

var BADGE_MAP = {};
var BADGE_TEXT = {};

function friendlyKey(k) {
  return FRIENDLY_KEYS[k] || k
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
}

function formatVal(v) {
  if (v === null || v === undefined) return { t: 'null', c: 'wor-null' };
  if (typeof v === 'boolean') return { t: String(v), c: 'wor-bool' };
  if (typeof v === 'number') {
    var f = Number.isInteger(v)
      ? v.toLocaleString()
      : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
    return { t: f, c: 'wor-num' };
  }
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) {
    var d = new Date(v);
    return {
      t: d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) +
         ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
      c: 'wor-str'
    };
  }
  return { t: String(v), c: 'wor-str' };
}

var chevSvg = '<svg class="wor-chev" width="16" height="16" '
  + 'style="width:16px;height:16px;min-width:16px;flex-shrink:0" '
  + 'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
  + '<polyline points="9 6 15 12 9 18"></polyline></svg>';

var dotsSvg = '<svg class="wor-dots" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">'
  + '<circle cx="12" cy="6" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="18" r="1.5"/></svg>';

function isLeaf(v) { return v === null || typeof v !== 'object'; }
function isEmission(o) { return o && typeof o === 'object' && 'typeOfActivity' in o && 'total' in o && 'fossil' in o; }
function isEnergyBlock(o) { return o && typeof o === 'object' && 'total_consumption' in o && 'uom' in o; }
function isMaterialBlock(o) { return o && typeof o === 'object' && 'total_quantity' in o && 'uom' in o; }
function isFactoryIdleNode(o) {
  return o && typeof o === 'object' && !Array.isArray(o) && 'idle_consumption_total_kwh' in o;
}
function isSplitEnergyBlock(o) {
  if (!o || typeof o !== 'object' || Array.isArray(o)) return false;
  var vals = Object.values(o);
  return vals.length > 0 && vals.every(function (v) {
    return v && typeof v === 'object' && 'total_consumption' in v && 'uom' in v;
  });
}

var ENERGY_FIELD_ORDER = ['energy_type', 'total_consumption', 'carbon_intensity_gco2_per_kwh', 'carbon_footprint_kg'];
var MATERIAL_FIELD_ORDER = ['total_quantity', 'uom', 'carbon_footprint_production_per_unit', 'carbon_footprint_distribution_per_unit', 'carbon_footprint_kg'];
/** Fields not shown under energy-type consumption detail (machine is the parent row; count is internal). */
var FACTORY_IDLE_HIDDEN = {
  machine_name: 1,
  entry_count: 1,
  aggregate_scope: 1,
  total_duration_minutes: 1,
  total_idle_time_minutes: 1
};

var FACTORY_IDLE_ORDER = [
  'idle_consumption_total_kwh',
  'prod_consumption_total_kwh',
  'total_time',
  'total_idle_time',
  'work_orders_duration',
  'idle_consumption_rate',
  'prod_consumption_rate',
  'publication_datetime'
];

function normalizeFactoryIdle(obj) {
  var o = Object.assign({}, obj);
  if (o.total_time == null && o.total_duration_minutes != null) {
    o.total_time = o.total_duration_minutes;
  }
  if (o.total_idle_time == null && o.total_idle_time_minutes != null) {
    o.total_idle_time = o.total_idle_time_minutes;
  }
  return o;
}

function energyVal(num, unit) {
  var fmt = typeof num === 'number'
    ? (Number.isInteger(num)
        ? num.toLocaleString()
        : num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 }))
    : String(num);
  return { _ev: true, num: fmt, unit: unit };
}

function prepareEnergyEntries(obj) {
  var uom = obj.uom || '';
  var isCompressedAir = (obj.energy_type || '').toString().toLowerCase().indexOf('compressedair') !== -1 ||
    (obj.energy_type || '').toString().toLowerCase().indexOf('compressed air') !== -1;
  var totalConsumptionUnit = function (k) {
    if (k !== 'total_consumption') return null;
    if (isCompressedAir) return 'm\u00B3';
    return uom || null;
  };
  var entries = [];
  ENERGY_FIELD_ORDER.forEach(function (k) {
    if (!(k in obj)) return;
    var v = obj[k];
    if (typeof v === 'number') {
      var unit = totalConsumptionUnit(k);
      if (k === 'total_consumption' && unit) v = energyVal(v, unit);
      else if (k === 'carbon_intensity_gco2_per_kwh') v = energyVal(v, 'gCO\u2082/kWh');
      else if (k === 'carbon_footprint_kg') v = energyVal(v, 'kg CO\u2082e');
    }
    entries.push([k, v]);
  });
  Object.keys(obj).forEach(function (k) {
    if (ENERGY_FIELD_ORDER.indexOf(k) === -1 && k !== 'uom') entries.push([k, obj[k]]);
  });
  return entries;
}

function prepareMaterialEntries(obj) {
  var uom = obj.uom || 'piece';
  var entries = [];
  MATERIAL_FIELD_ORDER.forEach(function (k) {
    if (!(k in obj)) return;
    var v = obj[k];
    if (typeof v === 'number') {
      if (k === 'total_quantity') v = energyVal(v, uom);
      else if (k.indexOf('carbon_footprint') !== -1) v = energyVal(v, 'kg CO\u2082e');
    }
    entries.push([k, v]);
  });
  Object.keys(obj).forEach(function (k) {
    if (MATERIAL_FIELD_ORDER.indexOf(k) === -1 && k !== 'carbon_footprint_per_unit') entries.push([k, obj[k]]);
  });
  return entries;
}

/** Machine accordion + labels: prefer stored machine_name (hall display for building_idle). */
function fedMachineRowLabel(machineKey, machineVal) {
  if (!machineVal || typeof machineVal !== 'object') return friendlyKey(machineKey);
  var picked = null;
  Object.keys(machineVal).forEach(function (eId) {
    var b = machineVal[eId];
    if (b && typeof b === 'object' && b.machine_name) {
      var mn = String(b.machine_name).trim();
      if (mn) picked = mn;
    }
  });
  if (picked) return picked;
  return friendlyKey(machineKey);
}

/** Reserved machine bucket for per-hall idle totals (not a physical machine). */
var FED_BUILDING_IDLE_KEY = 'building_idle';

function fedRowIsHallIdleAggregate(machineKey, machineVal) {
  if (machineKey === FED_BUILDING_IDLE_KEY) return true;
  if (!machineVal || typeof machineVal !== 'object') return false;
  var keys = Object.keys(machineVal);
  if (keys.length === 0) return false;
  for (var i = 0; i < keys.length; i++) {
    var b = machineVal[keys[i]];
    if (!b || typeof b !== 'object' || b.aggregate_scope !== 'building') {
      return false;
    }
  }
  return true;
}

function prepareFactoryIdleEntries(obj) {
  obj = normalizeFactoryIdle(obj);
  var entries = [];
  FACTORY_IDLE_ORDER.forEach(function (k) {
    if (!(k in obj)) return;
    var v = obj[k];
    if (k === 'work_orders_duration' && v && typeof v === 'object' && !Array.isArray(v)) {
      var parts = [];
      Object.keys(v).sort().forEach(function (wo) {
        var num = v[wo];
        var fmt = typeof num === 'number'
          ? (Number.isInteger(num)
              ? num.toLocaleString()
              : num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 }))
          : String(num);
        parts.push(wo + ': ' + fmt + ' min');
      });
      v = parts.join(', ');
    } else if (typeof v === 'number') {
      if (k === 'idle_consumption_total_kwh' || k === 'prod_consumption_total_kwh') v = energyVal(v, 'kWh');
      else if (k === 'total_time' || k === 'total_idle_time') v = energyVal(v, 'min');
      else if (k === 'idle_consumption_rate' || k === 'prod_consumption_rate') v = energyVal(v, 'kWh/h');
    }
    entries.push([k, v]);
  });
  Object.keys(obj).forEach(function (k) {
    if (FACTORY_IDLE_ORDER.indexOf(k) === -1 && !FACTORY_IDLE_HIDDEN[k]) entries.push([k, obj[k]]);
  });
  return entries;
}

function buildEmCard(entry) {
  var card = document.createElement('div');
  card.className = 'wor-emission-card';
  var order = ['typeOfActivity','total','shareOnTotal','primaryDataShare','emissionUnit','fossil','biogenic','dLuc','landUse','aircraft','comment'];
  var keys = order.filter(function (k) { return k in entry; });
  Object.keys(entry).forEach(function (k) { if (keys.indexOf(k) === -1) keys.push(k); });
  keys.forEach(function (k) {
    var fv = formatVal(entry[k]);
    var d = document.createElement('div');
    d.className = 'wor-em-field';
    var lbl = document.createElement('span');
    lbl.className = 'wor-em-label';
    lbl.textContent = friendlyKey(k) + ':';
    var val = document.createElement('span');
    val.className = 'wor-em-val ' + fv.c;
    val.textContent = fv.t;
    d.appendChild(lbl);
    d.appendChild(document.createTextNode(' '));
    d.appendChild(val);
    card.appendChild(d);
  });
  return card;
}

function buildTree(key, val, depth) {
  if (val && val._ev) {
    var leaf = document.createElement('div');
    leaf.className = 'wor-leaf';
    var lk = document.createElement('span');
    lk.className = 'wor-leaf-key';
    lk.textContent = friendlyKey(key);
    var lv = document.createElement('span');
    lv.className = 'wor-leaf-val wor-num';
    lv.textContent = val.num + ' ';
    var uSpan = document.createElement('span');
    uSpan.className = 'wor-unit';
    uSpan.textContent = val.unit;
    lv.appendChild(uSpan);
    leaf.appendChild(lk);
    leaf.appendChild(lv);
    return leaf;
  }

  if (isLeaf(val)) {
    var leaf2 = document.createElement('div');
    leaf2.className = 'wor-leaf';
    var lk2 = document.createElement('span');
    lk2.className = 'wor-leaf-key';
    lk2.textContent = friendlyKey(key);
    var fv = formatVal(val);
    var lv2 = document.createElement('span');
    lv2.className = 'wor-leaf-val ' + fv.c;
    lv2.textContent = fv.t;
    leaf2.appendChild(lk2);
    leaf2.appendChild(lv2);
    return leaf2;
  }

  if (Array.isArray(val) && val.every(isEmission)) {
    var wrap = document.createElement('div');
    wrap.className = 'wor-node';
    var hdr = makeHeader(friendlyKey(key), '', 'wor-badge-arr', val.length + ' entries');
    var ch = document.createElement('div');
    ch.className = 'wor-children';
    val.forEach(function (entry, i) {
      var label = entry.typeOfActivity || 'Entry ' + (i + 1);
      var eNode = document.createElement('div');
      eNode.className = 'wor-node';
      var eHdr = makeHeader(label, '', '', '');
      var eCh = document.createElement('div');
      eCh.className = 'wor-children';
      eCh.appendChild(buildEmCard(entry));
      eNode.appendChild(eHdr);
      eNode.appendChild(eCh);
      wireToggle(eHdr, eCh);
      ch.appendChild(eNode);
    });
    wrap.appendChild(hdr);
    wrap.appendChild(ch);
    wireToggle(hdr, ch);
    return wrap;
  }

  var entries;
  if (Array.isArray(val)) {
    entries = val.map(function (v, i) { return [String(i), v]; });
  } else if (isSplitEnergyBlock(val)) {
    entries = Object.entries(val).map(function (pair) {
      var block = Object.assign({ energy_type: pair[0] }, pair[1]);
      return [pair[0], block];
    });
  } else if (isEnergyBlock(val)) {
    entries = prepareEnergyEntries(val);
  } else if (isMaterialBlock(val)) {
    entries = prepareMaterialEntries(val);
  } else if (isFactoryIdleNode(val)) {
    entries = prepareFactoryIdleEntries(val);
  } else {
    entries = Object.entries(val);
  }

  var node = document.createElement('div');
  node.className = 'wor-node';
  var fed = window.FACTORY_ENERGY_DISTRIBUTION;
  var badgeCls = '';
  var badgeText = '';
  if (fed) {
    if (depth === 0) { badgeCls = 'wor-badge-fed-building'; badgeText = 'Building'; }
    else if (depth === 1) {
      if (fedRowIsHallIdleAggregate(key, val)) {
        badgeCls = 'wor-badge-fed-building';
        badgeText = 'Building';
      } else {
        badgeCls = 'wor-badge-fed-machine';
        badgeText = 'Machine';
      }
    }
    else if (depth === 2) { badgeCls = 'wor-badge-fed-energy'; badgeText = 'Energy'; }
  } else {
    var isWorkOrder = depth === 0 || key.startsWith('PO_') || key.startsWith('WO_') || key.startsWith('WO-');
    badgeCls = BADGE_MAP[key] ? 'wor-badge-' + BADGE_MAP[key] : (isWorkOrder ? 'wor-badge-po' : '');
    badgeText = BADGE_MAP[key] ? (BADGE_TEXT[key] || key) : (isWorkOrder ? 'Work Order' : '');
  }
  var cnt = Array.isArray(val) ? val.length : Object.keys(val).length;
  var workOrderKey = fed ? null : ((depth === 0) ? key : null);
  var fedBuildingKey = fed && depth === 0 ? key : null;
  var headerLabel = friendlyKey(key);
  if (fed && depth === 1) {
    headerLabel = fedMachineRowLabel(key, val);
  }
  var header = makeHeader(
    headerLabel,
    badgeCls,
    badgeText,
    cnt + ' item' + (cnt !== 1 ? 's' : ''),
    workOrderKey,
    fedBuildingKey
  );
  var children = document.createElement('div');
  children.className = 'wor-children';
  entries.forEach(function (pair) { children.appendChild(buildTree(pair[0], pair[1], depth + 1)); });
  node.appendChild(header);
  node.appendChild(children);
  wireToggle(header, children);

  if (depth === 0) {
    var card = document.createElement('div');
    card.className = 'wor-card';
    card.appendChild(node);
    return card;
  }
  return node;
}

function makeHeader(label, badgeCls, badgeText, countText, workOrderKey, fedBuildingKey) {
  var header = document.createElement('div');
  header.className = 'wor-header';
  header.innerHTML = chevSvg;
  var keySpan = document.createElement('span');
  keySpan.className = 'wor-key';
  keySpan.textContent = label;
  header.appendChild(keySpan);
  if (badgeCls && badgeText) {
    var badge = document.createElement('span');
    badge.className = 'wor-badge ' + badgeCls;
    badge.textContent = badgeText;
    header.appendChild(badge);
  }
  if (countText) {
    var count = document.createElement('span');
    count.className = 'wor-count';
    count.textContent = countText;
    header.appendChild(count);
  }
  if (workOrderKey || fedBuildingKey) {
    var menuWrap = document.createElement('div');
    menuWrap.className = 'wor-card-menu';
    menuWrap.innerHTML = dotsSvg;
    menuWrap.title = 'Actions';
    menuWrap.setAttribute('aria-label', 'Actions');
    var dropdown = document.createElement('div');
    dropdown.className = 'wor-card-dropdown';
    dropdown.setAttribute('role', 'menu');
    dropdown.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    var deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'wor-card-dropdown-item wor-card-dropdown-delete';
    deleteBtn.textContent = 'Delete';
    deleteBtn.setAttribute('role', 'menuitem');
    deleteBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      menuWrap.classList.remove('wor-dropdown-open');
      var cardEl = menuWrap.closest('.wor-card');
      if (workOrderKey) {
        if (!confirm('Delete work order "' + workOrderKey + '"? This cannot be undone.')) return;
        deleteWorkOrder(workOrderKey, cardEl);
      } else if (fedBuildingKey) {
        if (!confirm('Delete all idle consumption for building "' + fedBuildingKey + '"? This cannot be undone.')) return;
        deleteFactoryBuilding(fedBuildingKey, cardEl);
      }
    });
    dropdown.appendChild(deleteBtn);
    menuWrap.appendChild(dropdown);
    menuWrap.addEventListener('click', function (e) { e.stopPropagation(); });
    menuWrap.addEventListener('mousedown', function (e) {
      e.stopPropagation();
      document.querySelectorAll('.wor-card-menu.wor-dropdown-open').forEach(function (m) {
        if (m !== menuWrap) m.classList.remove('wor-dropdown-open');
      });
      menuWrap.classList.toggle('wor-dropdown-open');
    });
    header.appendChild(menuWrap);
  }
  return header;
}

function wireToggle(header, children) {
  header.addEventListener('click', function () {
    var chev = header.querySelector('.wor-chev');
    var open = children.classList.contains('wor-open');
    if (open) {
      children.style.maxHeight = children.scrollHeight + 'px';
      requestAnimationFrame(function () { children.style.maxHeight = '0'; children.style.opacity = '0'; });
      children.classList.remove('wor-open');
      chev.classList.remove('wor-expanded');
    } else {
      children.classList.add('wor-open');
      chev.classList.add('wor-expanded');
      children.style.maxHeight = children.scrollHeight + 'px';
      children.style.opacity = '1';
      var done = function () {
        if (children.classList.contains('wor-open')) children.style.maxHeight = 'none';
        children.removeEventListener('transitionend', done);
      };
      children.addEventListener('transitionend', done);
    }
  });
}

function expandAll() {
  document.querySelectorAll('#fed-tree .wor-children').forEach(function (c) {
    c.classList.add('wor-open');
    c.style.maxHeight = 'none';
    c.style.opacity = '1';
    var chev = c.closest('.wor-node').querySelector(':scope > .wor-header .wor-chev');
    if (chev) chev.classList.add('wor-expanded');
  });
}

function collapseAll() {
  document.querySelectorAll('#fed-tree .wor-children').forEach(function (c) {
    c.classList.remove('wor-open');
    c.style.maxHeight = '0';
    c.style.opacity = '0';
    var chev = c.closest('.wor-node').querySelector(':scope > .wor-header .wor-chev');
    if (chev) chev.classList.remove('wor-expanded');
  });
}

async function deleteWorkOrder(workOrderName, cardEl) {
  try {
    var url = 'api/data_explorer/' + encodeURIComponent(workOrderName);
    var res = await fetch(url, { method: 'DELETE' });
    if (res.status === 401) { window.location.href = 'login'; return; }
    if (!res.ok) throw new Error('Delete failed');
    if (cardEl && cardEl.parentNode) cardEl.remove();
  } catch (err) {
    alert('Failed to delete: ' + err.message);
  }
}

async function deleteFactoryBuilding(buildingId, cardEl) {
  try {
    var url = 'api/factory_energy_distribution/' + encodeURIComponent(buildingId);
    var res = await fetch(url, { method: 'DELETE', credentials: 'same-origin' });
    if (res.status === 401) { window.location.href = 'login'; return; }
    if (res.status === 404) throw new Error('Building not found');
    if (!res.ok) {
      var detail = 'HTTP ' + res.status;
      try {
        var errBody = await res.json();
        if (errBody && errBody.detail) detail = String(errBody.detail);
      } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    if (cardEl && cardEl.parentNode) cardEl.remove();
    if (_fedCachedData && _fedCachedData[buildingId]) {
      delete _fedCachedData[buildingId];
      if (typeof window.renderFactorySankey === 'function') {
        window.renderFactorySankey('fed-sankey', _fedCachedData);
      }
    }
  } catch (err) {
    alert('Failed to delete: ' + err.message);
  }
}

document.addEventListener('click', function (e) {
  if (e.target.closest && e.target.closest('.wor-card-menu')) return;
  setTimeout(function () {
    document.querySelectorAll('.wor-card-menu.wor-dropdown-open').forEach(function (m) {
      m.classList.remove('wor-dropdown-open');
    });
  }, 0);
});

async function loadRecords() {
  var root = document.getElementById('fed-tree');
  try {
    var res = await fetch('api/factory_energy_distribution', { credentials: 'same-origin' });
    if (res.status === 401) { window.location.href = 'login'; return; }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    _fedCachedData = data;
    root.innerHTML = '';
    var keys = Object.keys(data);
    if (keys.length === 0) {
      root.innerHTML = '<p class="wor-empty">No factory idle consumption data yet. Send data to <code>POST /idle_consumptions</code>.</p>';
    } else {
      keys.forEach(function (k) { root.appendChild(buildTree(k, data[k], 0)); });
    }
    if (typeof window.renderFactorySankey === 'function') {
      window.renderFactorySankey('fed-sankey', data);
    }
  } catch (err) {
    root.innerHTML = '<p class="wor-error">Failed to load data: ' + err.message + '</p>';
  }
}

document.getElementById('btn-expand-all').addEventListener('click', expandAll);
document.getElementById('btn-collapse-all').addEventListener('click', collapseAll);
loadRecords();
