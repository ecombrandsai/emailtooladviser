// EmailToolAdviser — site interactions
(function () {
  'use strict';

  // Smooth scroll for in-page anchors
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

  // Lazy-init images that include data-src
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

  // CTA click tracking shim (wire to GA later)
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
})();
