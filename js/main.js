(function(){
  // Reading progress bar
  var bar=document.getElementById('progress-bar');
  if(bar){
    window.addEventListener('scroll',function(){
      var h=document.documentElement, b=document.body;
      var st='scrollTop', sh='scrollHeight';
      var max=(h[sh]||b[sh])-h.clientHeight;
      var pct=max>0?((h[st]||b[st])/max)*100:0;
      bar.style.width=Math.min(pct,100)+'%';
    },{passive:true});
  }

  // Mobile sticky CTA — appears after first major CTA component enters viewport
  var cta=document.getElementById('msct');
  if(cta&&window.innerWidth<768){
    var triggers=document.querySelectorAll('.featured-pick,.featured-pick-box,.top-pick,.cta-box,.pick-cta,.cta-box-btn');
    if(!triggers.length){
      var links=document.querySelectorAll('a[href*="constantcontact"]');
      if(links.length>0)triggers=[links[0]];
    }
    if(triggers.length&&'IntersectionObserver' in window){
      var shown=false;
      var obs=new IntersectionObserver(function(entries){
        entries.forEach(function(e){
          if(e.isIntersecting&&!shown){
            shown=true;
            cta.style.display='block';
            document.body.style.paddingBottom='64px';
            obs.disconnect();
          }
        });
      },{threshold:0.5});
      Array.prototype.forEach.call(triggers,function(el){obs.observe(el);});
    }
    var close=document.getElementById('msct-close');
    if(close){close.addEventListener('click',function(){
      cta.style.display='none';
      document.body.style.paddingBottom='0';
    });}
  }

  // FAQ accordion (for .faq-q / .faq-item structure; native <details> handles itself)
  document.querySelectorAll('.faq-q').forEach(function(q){
    q.addEventListener('click',function(){
      var item=this.closest('.faq-item');
      if(item)item.classList.toggle('open');
    });
  });

  // Smooth scroll for in-page anchors
  document.querySelectorAll('a[href^="#"]').forEach(function(link){
    link.addEventListener('click',function(e){
      var id=link.getAttribute('href');
      if(id.length<2)return;
      var target=document.querySelector(id);
      if(!target)return;
      e.preventDefault();
      target.scrollIntoView({behavior:'smooth',block:'start'});
    });
  });
})();
