// EmailToolAdviser — site interactions + mobile CTA
(function () {
  'use strict';

  // ---- Smooth-scroll for in-page anchors ----
  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener('click', function (e) {
      var id = link.getAttribute('href');
      if (id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // ---- Lazy-init images that include data-src ----
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var img = entry.target;
        if (img.dataset.src) img.src = img.dataset.src;
        io.unobserve(img);
      });
    });
    document.querySelectorAll('img[data-src]').forEach(function (img) { io.observe(img); });
  }

  // ---- Affiliate click tracking shim ----
  document.querySelectorAll('a[href*="join.constantcontact.com"]').forEach(function (a) {
    a.addEventListener('click', function () {
      try {
        if (window.gtag) {
          window.gtag('event', 'affiliate_click', {
            event_category: 'cta',
            event_label: a.textContent.trim().slice(0, 60)
          });
        }
      } catch (e) { /* swallow */ }
    });
  });

  // ---- Smart mobile sticky CTA ----
  // Mobile-only, appears once the visitor has scrolled past the first major CTA.
  function injectMobileCTA() {
    if (window.innerWidth >= 768) return;
    if (document.getElementById('msct')) return;
    var bar = document.createElement('div');
    bar.id = 'msct';
    bar.style.cssText = 'display:none;position:fixed;bottom:0;left:0;right:0;background:#1a2332;padding:12px 16px;z-index:9999;box-shadow:0 -4px 20px rgba(0,0,0,0.3);';
    bar.innerHTML = ''
      + '<div style="display:flex;align-items:center;justify-content:space-between;max-width:600px;margin:0 auto;gap:12px;">'
      +   '<div style="display:flex;align-items:center;gap:10px;min-width:0;">'
      +     '<div style="width:32px;height:32px;background:#1856a0;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:11px;color:white;flex-shrink:0;">CC</div>'
      +     '<div style="min-width:0;">'
      +       '<div style="color:white;font-weight:700;font-size:13px;">Our Top Pick</div>'
      +       '<div style="color:#94a3b8;font-size:11px;">Constant Contact - from $12/mo</div>'
      +     '</div>'
      +   '</div>'
      +   '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">'
      +     '<a href="https://join.constantcontact.com/join-now" rel="sponsored noopener" target="_blank" style="background:#2563eb;color:white;padding:10px 16px;border-radius:8px;font-weight:700;font-size:13px;text-decoration:none;white-space:nowrap;">Get Started</a>'
      +     '<button type="button" id="msct-close" style="background:transparent;border:none;color:#94a3b8;font-size:22px;cursor:pointer;padding:4px 8px;line-height:1;">×</button>'
      +   '</div>'
      + '</div>';
    document.body.appendChild(bar);
    document.getElementById('msct-close').addEventListener('click', function () {
      bar.style.display = 'none';
      document.body.style.paddingBottom = '0';
    });

    // Pick triggers: featured-pick-box, in-article CTAs, OR the second
    // affiliate-link in the page.
    var triggers = document.querySelectorAll('.featured-pick-box, .featured-pick-cta, .in-article-cta, .top-pick, .cta-box');
    if (!triggers.length) {
      var links = document.querySelectorAll('a[href*="constantcontact"]');
      if (links.length > 1) triggers = [links[1]];
      else if (links.length === 1) triggers = [links[0]];
    }
    if (!triggers.length || !('IntersectionObserver' in window)) return;
    var shown = false;
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !shown) {
          shown = true;
          bar.style.display = 'block';
          document.body.style.paddingBottom = '70px';
          observer.disconnect();
        }
      });
    }, { threshold: 0.5 });
    Array.prototype.forEach.call(triggers, function (el) { observer.observe(el); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectMobileCTA);
  } else {
    injectMobileCTA();
  }
})();
