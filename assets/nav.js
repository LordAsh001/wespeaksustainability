// Site navigation: dropdown menus, mobile drawer, search palette, back-to-top,
// reading progress and "On this page" highlighting. Everything degrades gracefully.
(function () {
  var doc = document, body = doc.body;

  /* ---------- desktop dropdown menus ---------- */
  var triggers = [].slice.call(doc.querySelectorAll('.menu-trigger'));
  function closeMenus(except) {
    triggers.forEach(function (t) { if (t !== except) t.setAttribute('aria-expanded', 'false'); });
  }
  triggers.forEach(function (t) {
    var panel = doc.getElementById(t.getAttribute('aria-controls'));
    t.addEventListener('click', function (e) {
      e.stopPropagation();
      if (Date.now() - (t._hoverOpened || 0) < 450) return;
      var open = t.getAttribute('aria-expanded') === 'true';
      closeMenus(t);
      t.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (!open) { var first = panel.querySelector('a'); if (first && e.detail === 0) first.focus(); }
    });
    var group = t.parentNode, hoverTimer;
    group.addEventListener('mouseenter', function () {
      if (!matchMedia('(hover: hover)').matches) return;
      clearTimeout(hoverTimer); closeMenus(t);
      if (t.getAttribute('aria-expanded') !== 'true') { t._hoverOpened = Date.now(); t.setAttribute('aria-expanded', 'true'); }
    });
    group.addEventListener('mouseleave', function () {
      if (!matchMedia('(hover: hover)').matches) return;
      hoverTimer = setTimeout(function () { t.setAttribute('aria-expanded', 'false'); }, 180);
    });
    panel.addEventListener('keydown', function (e) {
      var links = [].slice.call(panel.querySelectorAll('a')), i = links.indexOf(doc.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); links[(i + 1) % links.length].focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); links[(i - 1 + links.length) % links.length].focus(); }
      if (e.key === 'Escape') { t.setAttribute('aria-expanded', 'false'); t.focus(); }
    });
  });
  doc.addEventListener('click', function (e) { if (!e.target.closest('.menu-group')) closeMenus(); });

  /* ---------- mobile drawer ---------- */
  var drawer = doc.getElementById('drawer'), menuBtn = doc.querySelector('.menu-btn');
  function setDrawer(open) {
    if (!drawer) return;
    drawer.hidden = !open;
    menuBtn && menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    body.classList.toggle('no-scroll', open);
    if (open) { var c = drawer.querySelector('.drawer-close'); c && c.focus(); } else if (menuBtn) menuBtn.focus();
  }
  menuBtn && menuBtn.addEventListener('click', function () { setDrawer(true); });
  if (drawer) {
    drawer.addEventListener('click', function (e) { if (e.target === drawer || e.target.closest('.drawer-close')) setDrawer(false); });
  }

  /* ---------- search palette ---------- */
  var pal = doc.getElementById('palette'), input = doc.getElementById('palette-q'), results = doc.getElementById('palette-results');
  var index = null, active = -1, lastFocus = null;
  var quick = [
    ['Stories', 'All stories', '/stories/'], ['Map', 'World map', '/map/'], ['Ideas', 'Copy This: ideas to try', '/copy-this/'],
    ['Problems', 'One problem, many solutions', '/solutions/'], ['Legacy', 'Legacy archive', '/legacy/'],
    ['Research', 'Insights', '/insights/'], ['Research', 'Open data', '/data/'], ['Take part', 'Tell your story', '/submit/']
  ];
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function norm(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
  function render(items, heading) {
    active = items.length ? 0 : -1;
    results.innerHTML = (heading ? '<p class="pal-head">' + heading + '</p>' : '') + (items.length ? '<ul role="listbox">' + items.map(function (d, i) {
      return '<li role="option" id="pal-' + i + '"' + (i === 0 ? ' aria-selected="true"' : '') + '><a href="' + d[2] + '"><span class="kind">' + esc(d[0]) + '</span><b>' + esc(d[1]) + '</b>' + (d[3] ? '<span class="pal-sub">' + esc(d[3]) + '</span>' : '') + '</a></li>';
    }).join('') + '</ul>' : '<p class="pal-empty">No matches yet. Press Enter to search everything, or <a href="/submit/">tell us a story about it</a>.</p>');
  }
  function search(q) {
    var terms = norm(q).split(/\s+/).filter(function (w) { return w.length > 1; }).map(function (w) { return w.replace(/(ing|ers|er|es|s)$/, ''); });
    if (!terms.length) { render(quick, 'Jump to'); return; }
    if (!index) { results.innerHTML = '<p class="pal-head">Loading…</p>'; return; }
    var out = index.map(function (d) {
      var t = norm(d.t), b = norm(d.s + ' ' + d.p + ' ' + d.x), sc = 0;
      for (var i = 0; i < terms.length; i++) { var a = t.indexOf(terms[i]) > -1, bb = b.indexOf(terms[i]) > -1; if (!a && !bb) return null; sc += (a ? 5 : 0) + (bb ? 1 : 0); }
      return { d: d, s: sc + (d.k === 'Story' ? .5 : 0) };
    }).filter(Boolean).sort(function (a, b) { return b.s - a.s; }).slice(0, 8).map(function (r) { return [r.d.k, r.d.t, r.d.u, r.d.p || r.d.s]; });
    render(out, out.length ? out.length + ' top results' : '');
  }
  function openPalette() {
    if (!pal) { location.href = '/search/'; return; }
    lastFocus = doc.activeElement; setDrawer(false);
    pal.hidden = false; body.classList.add('no-scroll'); input.value = ''; render(quick, 'Jump to'); input.focus();
    if (!index) fetch('/search-index.json').then(function (r) { return r.json(); }).then(function (d) { index = d; if (input.value) search(input.value); }).catch(function () {});
  }
  function closePalette() { if (!pal || pal.hidden) return; pal.hidden = true; body.classList.remove('no-scroll'); lastFocus && lastFocus.focus && lastFocus.focus(); }
  function move(dir) {
    var opts = results.querySelectorAll('[role=option]'); if (!opts.length) return;
    if (active > -1) opts[active].removeAttribute('aria-selected');
    active = (active + dir + opts.length) % opts.length; opts[active].setAttribute('aria-selected', 'true'); opts[active].scrollIntoView({ block: 'nearest' });
  }
  doc.addEventListener('click', function (e) { var t = e.target.closest('[data-open-search]'); if (t) { e.preventDefault(); openPalette(); } });
  if (pal) {
    pal.addEventListener('click', function (e) { if (e.target === pal) closePalette(); });
    var tm; input.addEventListener('input', function () { clearTimeout(tm); tm = setTimeout(function () { search(input.value); }, 90); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        var sel = results.querySelector('[aria-selected=true] a');
        if (sel) { e.preventDefault(); location.href = sel.getAttribute('href'); }
      }
    });
  }
  doc.addEventListener('keydown', function (e) {
    var typing = /input|textarea|select/i.test((doc.activeElement || {}).tagName || '') || (doc.activeElement && doc.activeElement.isContentEditable);
    if ((e.key === '/' && !typing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) { e.preventDefault(); openPalette(); }
    if (e.key === 'Escape') { closePalette(); if (drawer && !drawer.hidden) setDrawer(false); closeMenus(); }
  });

  /* ---------- back to top + reading progress + compact header ---------- */
  var topBtn = doc.querySelector('.to-top'), bar = doc.querySelector('.progress-bar span'), head = doc.querySelector('.site-head');
  var isArticle = !!doc.querySelector('.story-layout');
  function onScroll() {
    var y = window.scrollY, h = doc.documentElement.scrollHeight - innerHeight;
    if (topBtn) topBtn.hidden = y < 900;
    if (bar && isArticle) bar.style.width = (h > 0 ? Math.min(100, y / h * 100) : 0) + '%';
    head && head.classList.toggle('scrolled', y > 8);
  }
  addEventListener('scroll', onScroll, { passive: true }); onScroll();
  topBtn && topBtn.addEventListener('click', function () { scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); doc.getElementById('main').focus({ preventScroll: true }); });

  /* ---------- "On this page" highlighting ---------- */
  var tocLinks = [].slice.call(doc.querySelectorAll('.toc a'));
  if (tocLinks.length && 'IntersectionObserver' in window) {
    var map = {}; tocLinks.forEach(function (a) { var k = a.getAttribute('href').slice(1); (map[k] = map[k] || []).push(a); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { tocLinks.forEach(function (a) { a.removeAttribute('aria-current'); }); (map[en.target.id] || []).forEach(function (a) { a.setAttribute('aria-current', 'true'); }); }
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    Object.keys(map).forEach(function (id) { var el = doc.getElementById(id); el && io.observe(el); });
  }
})();
