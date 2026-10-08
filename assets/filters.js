// Client-side filtering for story lists; the full list works without JS.
(function(){
  var f=document.querySelector('form[data-filter-for]');if(!f)return;
  var cards=[].slice.call(document.querySelectorAll(f.dataset.filterFor)),cnt=f.querySelector('[data-count]'),empty=document.querySelector('[data-empty]');
  var multi={topics:1,sdgs:1};
  function apply(){
    var v={},q=new URLSearchParams();
    [].forEach.call(f.elements,function(el){if(el.name&&el.value){v[el.name]=el.value;q.set(el.name,el.value)}});
    var n=0;cards.forEach(function(c){
      var ok=Object.keys(v).every(function(k){var d=c.dataset[k]||'';return multi[k]?d.split(' ').indexOf(v[k])>-1:d===v[k]});
      c.hidden=!ok;if(ok)n++;
    });
    if(cnt)cnt.textContent=n;if(empty)empty.hidden=n>0;
    history.replaceState(null,'',location.pathname+(q.toString()?'?'+q:''));
  }
  var p=new URLSearchParams(location.search);
  [].forEach.call(f.elements,function(el){if(el.name&&p.get(el.name))el.value=p.get(el.name)});
  f.addEventListener('change',apply);
  f.addEventListener('reset',function(){setTimeout(apply,0)});
  f.addEventListener('submit',function(e){e.preventDefault()});
  apply();
})();
