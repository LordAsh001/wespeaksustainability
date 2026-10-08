// Menu + theme toggle (progressive enhancement)
(function(){
  var b=document.querySelector('.menu-btn'),n=document.getElementById('nav');
  if(b&&n)b.addEventListener('click',function(){var o=n.classList.toggle('open');b.setAttribute('aria-expanded',o)});
  var t=document.querySelector('[data-theme-toggle]');
  if(t)t.addEventListener('click',function(){
    var r=document.documentElement,cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
    var next=cur==='dark'?'light':'dark';r.dataset.theme=next;try{localStorage.setItem('wss-theme',next)}catch(e){}
  });
})();
