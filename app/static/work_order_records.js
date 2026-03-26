/* Work Order Records – tree view logic
 * Loaded as a static file so it is NOT processed by prepare_static_html_for_stage.
 * All API URLs are RELATIVE (no leading "/") so they resolve correctly both
 * locally (base = "/") and behind API Gateway (base = "/dev/" via <base href>). */

var FRIENDLY_KEYS = {
  BOP: 'Bill of Process', BOM: 'Bill of Materials', PCF: 'Product Carbon Footprint',
  operations: 'Bill of Process', materials: 'Bill of Materials', pcf: 'Product Carbon Footprint',
  productCarbonFootprint: 'Total PCF', primaryDataShare: 'Primary Data Share',
  shareOnTotal: 'Share on Total', emissionUnit: 'Unit', typeOfActivity: 'Activity',
  dLuc: 'dLUC', assessmentYear: 'Assessment Year', dataSource: 'Data Source',
  batchNumber: 'Batch Number', factoryId: 'Factory ID', sourceSystem: 'Source System',
  energy_type: 'Energy Type',
  carbon_intensity_gco2_per_kwh: 'Carbon Intensity',
  carbon_footprint_kg: 'Total Carbon Footprint',
  carbon_footprint_per_unit: 'Carbon Footprint per Unit',
  carbon_footprint_production_per_unit: 'Production Stage (per unit)',
  carbon_footprint_distribution_per_unit: 'Distribution Stage (per unit)',
  total_consumption: 'Total Consumption',
  total_quantity: 'Total Quantity',
  uom: 'Unit of Measure',
  product_name: 'Product Name'
};
var BADGE_MAP = { BOP: 'bop', BOM: 'bom', PCF: 'pcf', operations: 'bop', materials: 'bom', pcf: 'pcf' };
var BADGE_TEXT = {
  BOP: 'BOP', BOM: 'BOM', PCF: 'PCF',
  operations: 'BOP', materials: 'BOM', pcf: 'PCF'
};

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
function isSplitEnergyBlock(o) {
  if (!o || typeof o !== 'object' || Array.isArray(o)) return false;
  var vals = Object.values(o);
  return vals.length > 0 && vals.every(function (v) {
    return v && typeof v === 'object' && 'total_consumption' in v && 'uom' in v;
  });
}

var ENERGY_FIELD_ORDER = [
  'energy_type', 'total_consumption',
  'carbon_intensity_gco2_per_kwh', 'carbon_footprint_kg'
];

var MATERIAL_FIELD_ORDER = [
  'total_quantity', 'uom',
  'carbon_footprint_production_per_unit',
  'carbon_footprint_distribution_per_unit', 'carbon_footprint_kg'
];

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
  // CompressedAir total consumption must show m³/Nm³, not kWh (stored uom may be M3, NM3, etc.)
  var isCompressedAir = (obj.energy_type || '').toString().toLowerCase().indexOf('compressedair') !== -1 ||
    (obj.energy_type || '').toString().toLowerCase().indexOf('compressed air') !== -1;
  var totalConsumptionUnit = (k) => {
    if (k !== 'total_consumption') return null;
    if (isCompressedAir) return 'm\u00B3';  // m³ (cubic meters)
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
    var leaf = document.createElement('div');
    leaf.className = 'wor-leaf';
    var lk = document.createElement('span');
    lk.className = 'wor-leaf-key';
    lk.textContent = friendlyKey(key);
    var fv = formatVal(val);
    var lv = document.createElement('span');
    lv.className = 'wor-leaf-val ' + fv.c;
    lv.textContent = fv.t;
    leaf.appendChild(lk);
    leaf.appendChild(lv);
    return leaf;
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
  } else {
    entries = Object.entries(val);
  }
  var node = document.createElement('div');
  node.className = 'wor-node';
  var isWorkOrder = depth === 0 || key.startsWith('PO_') || key.startsWith('WO_') || key.startsWith('WO-');
  var badgeCls = BADGE_MAP[key] ? 'wor-badge-' + BADGE_MAP[key] : (isWorkOrder ? 'wor-badge-po' : '');
  var badgeText = BADGE_MAP[key] ? (BADGE_TEXT[key] || key) : (isWorkOrder ? 'Work Order' : '');
  var cnt = Array.isArray(val) ? val.length : Object.keys(val).length;
  var workOrderKey = (depth === 0) ? key : null;
  var header = makeHeader(friendlyKey(key), badgeCls, badgeText, cnt + ' item' + (cnt !== 1 ? 's' : ''), workOrderKey);
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

function makeHeader(label, badgeCls, badgeText, countText, workOrderKey) {
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
  if (workOrderKey) {
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
      if (!confirm('Delete work order "' + workOrderKey + '"? This cannot be undone.')) return;
      deleteWorkOrder(workOrderKey, menuWrap.closest('.wor-card'));
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
  document.querySelectorAll('#wor-tree .wor-children').forEach(function (c) {
    c.classList.add('wor-open');
    c.style.maxHeight = 'none';
    c.style.opacity = '1';
    var chev = c.closest('.wor-node').querySelector(':scope > .wor-header .wor-chev');
    if (chev) chev.classList.add('wor-expanded');
  });
}

function collapseAll() {
  document.querySelectorAll('#wor-tree .wor-children').forEach(function (c) {
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

document.addEventListener('click', function (e) {
  if (e.target.closest && e.target.closest('.wor-card-menu')) return;
  setTimeout(function () {
    document.querySelectorAll('.wor-card-menu.wor-dropdown-open').forEach(function (m) {
      m.classList.remove('wor-dropdown-open');
    });
  }, 0);
});

async function loadRecords() {
  var root = document.getElementById('wor-tree');
  try {
    var res = await fetch('api/data_explorer');
    if (res.status === 401) { window.location.href = 'login'; return; }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    root.innerHTML = '';
    var keys = Object.keys(data);
    if (keys.length === 0) {
      root.innerHTML = '<p class="wor-empty">No work order records available yet.</p>';
    } else {
      keys.forEach(function (k) { root.appendChild(buildTree(k, data[k], 0)); });
    }
  } catch (err) {
    root.innerHTML = '<p class="wor-error">Failed to load data: ' + err.message + '</p>';
  }
}

document.getElementById('btn-expand-all').addEventListener('click', expandAll);
document.getElementById('btn-collapse-all').addEventListener('click', collapseAll);
loadRecords();
