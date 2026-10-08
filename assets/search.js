// Lightweight full-text search over /search-index.json
(function(){
  var input=document.getElementById('q'),out=document.getElementById('results'),st=document.getElementById('search-status'),idx=null;
  function norm(s){return (s||'').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'')}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function stem(w){return w.replace(/(ing|ers|er|es|s)$/,'')}
  function run(q){
    var terms=norm(q).split(/\s+/).filter(function(w){return w.length>1}).map(stem);
    if(!terms.length){out.innerHTML='';st.textContent='';return}
    var res=idx.map(function(d){
      var t=norm(d.t),body=norm(d.s+' '+d.p+' '+d.x),score=0;
      for(var i=0;i<terms.length;i++){var w=terms[i];var a=t.indexOf(w)>-1,b=body.indexOf(w)>-1;if(!a&&!b)return null;score+=(a?5:0)+(b?1:0)}
      if(d.k==='Story')score+=.5;return{d:d,s:score};
    }).filter(Boolean).sort(function(a,b){return b.s-a.s});
    st.textContent=res.length+' result'+(res.length===1?'':'s')+' for “'+q+'”';
    out.innerHTML=res.length?res.map(function(r){var d=r.d;return '<article class="result"><span class="kind">'+esc(d.k)+(d.p?' · '+esc(d.p):'')+'</span><h3><a href="'+d.u+'">'+esc(d.t)+'</a></h3><p>'+esc(d.s)+'</p></article>'}).join(''):
      '<p class="empty">Nothing found yet. Try a broader word, <a href="/stories/">browse all stories</a>, or <a href="/submit/">tell us a story about it</a>.</p>';
  }
  var q=new URLSearchParams(location.search).get('q')||'';input.value=q;
  fetch('/search-index.json').then(function(r){return r.json()}).then(function(d){idx=d;if(q)run(q);
    var tm;input.addEventListener('input',function(){clearTimeout(tm);tm=setTimeout(function(){run(input.value);history.replaceState(null,'','?q='+encodeURIComponent(input.value))},150)});
  }).catch(function(){st.textContent='Search is unavailable right now. Please browse the stories instead.'});
})();
