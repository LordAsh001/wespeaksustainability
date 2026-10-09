// Menu + theme toggle (progressive enhancement)
(function(){
  var t=document.querySelector('[data-theme-toggle]');
  if(t)t.addEventListener('click',function(){
    var r=document.documentElement,cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
    var next=cur==='dark'?'light':'dark';r.dataset.theme=next;try{localStorage.setItem('wss-theme',next)}catch(e){}
  });
})();
// Copy citation / print brief
document.addEventListener('click',function(ev){
  var c=ev.target.closest('[data-copy]');
  if(c){try{navigator.clipboard.writeText(c.dataset.copy).then(function(){c.textContent='Copied';setTimeout(function(){c.textContent='Copy citation'},1800)})}catch(e){}}
  if(ev.target.closest('[data-print]'))window.print();
});
