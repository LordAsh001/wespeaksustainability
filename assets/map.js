// Interactive Leaflet map with clustering; falls back to the static SVG map + table.
(function(){
  if(!window.L||!L.markerClusterGroup)return; // static map stays
  var el=document.getElementById('map'),f=document.getElementById('map-filters'),cnt=f.querySelector('[data-count]');
  fetch('/map-data.json').then(function(r){return r.json()}).then(function(data){
    el.innerHTML='';
    var map=L.map(el,{scrollWheelZoom:false,worldCopyJump:true}).setView([12,10],2);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',{maxZoom:12,attribution:'&copy; OpenStreetMap contributors &copy; CARTO'}).addTo(map);
    var group=L.markerClusterGroup({showCoverageOnHover:false,maxClusterRadius:40});map.addLayer(group);
    function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
    function draw(){
      var v={};[].forEach.call(f.elements,function(e){if(e.name&&e.value)v[e.name]=e.value});
      group.clearLayers();var n=0;
      data.forEach(function(d){
        if(v.kind&&d.k!==v.kind)return;if(v.region&&d.r!==v.region)return;if(v.problem&&d.pr!==v.problem)return;
        if(v.topic&&d.tp.indexOf(v.topic)<0)return;if(v.sdg&&d.sd.map(String).indexOf(v.sdg)<0)return;if(v.status&&d.st!==v.status)return;
        n++;
        var icon=L.divIcon({className:'',html:'<div class="mk'+(d.k==='memorial'?' memorial':'')+'"></div>',iconSize:[18,18],iconAnchor:[9,9]});
        var m=L.marker([d.la,d.lo],{icon:icon,title:d.n,alt:d.n,keyboard:true});
        m.bindPopup('<div><span class="kind">'+(d.k==='memorial'?'Remembered':esc(d.pl))+'</span><h3>'+esc(d.n)+'</h3><div style="color:#6f655a;font-size:.85rem">'+esc(d.p)+(d.k==='story'?' · '+esc(d.ev):'')+'</div><p style="margin:.5em 0">'+esc(d.s)+'</p><a href="'+d.u+'">'+(d.k==='memorial'?'Read the profile':'Read the story')+' →</a></div>');
        group.addLayer(m);
      });
      cnt.textContent=n+' shown';
      document.querySelectorAll('#map-table tbody tr, .table-wrap tbody tr').forEach(function(){});
    }
    f.addEventListener('change',draw);draw();
  }).catch(function(){});
})();
