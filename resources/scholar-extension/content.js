(()=>{
  if(document.querySelector('#shiguang-scholar-export'))return;
  const text=e=>(e?.textContent||'').trim(),number=e=>Number(text(e).replace(/[^0-9]/g,''))||0;
  function snapshot(){
    const params=new URLSearchParams(location.search),metricRows=[...document.querySelectorAll('#gsc_rsb_st tbody tr')];
    const metric=(row,col)=>number(metricRows[row]?.querySelectorAll('td')[col]);
    const papers=[...document.querySelectorAll('tr.gsc_a_tr')].map(row=>{
      const title=row.querySelector('.gsc_a_at'),cite=row.querySelector('.gsc_a_c a'),year=row.querySelector('.gsc_a_y');
      const gray=[...row.querySelectorAll('.gs_gray')];
      return {id:title?.getAttribute('data-href')||title?.href||text(title),title:text(title),authors:text(gray[0]),venue:text(gray[1]),year:number(year),citations:number(cite),url:title?.href||title?.getAttribute('data-href')||''};
    });
    const yearly={};document.querySelectorAll('.gsc_g_t').forEach((el,i)=>{const bar=document.querySelectorAll('.gsc_g_al')[i];if(text(el))yearly[text(el)]=number(bar)});
    const interests=[...document.querySelectorAll('#gsc_prf_int a')].map(text);
    const payload={schemaVersion:1,capturedAt:new Date().toISOString(),source:'google-scholar-visible-profile',profile:{id:params.get('user')||'',name:text(document.querySelector('#gsc_prf_in')),affiliation:text(document.querySelector('.gsc_prf_il')),interests,url:location.href,metrics:{citationsAll:metric(0,1),citationsRecent:metric(0,2),hIndexAll:metric(1,1),hIndexRecent:metric(1,2),i10All:metric(2,1),i10Recent:metric(2,2)},yearlyCitations:yearly},papers};
    return payload;
  }
  async function sync(payload){return await chrome.runtime.sendMessage({type:'sync-scholar',payload})}
  const button=document.createElement('button');button.id='shiguang-scholar-export';button.textContent='同步全部到拾光';button.onclick=async()=>{button.disabled=true;button.textContent='正在加载全部论文…';const more=document.querySelector('#gsc_bpf_more');let tries=0;while(more&&!more.disabled&&tries++<100){more.click();await new Promise(r=>setTimeout(r,650))}const result=await sync(snapshot());button.textContent=result?.ok?'已同步到拾光':'拾光未启动，已暂存';setTimeout(()=>{button.disabled=false;button.textContent='同步全部到拾光'},1800)};document.body.appendChild(button);
  setTimeout(async()=>{if(text(document.querySelector('#gsc_prf_in')))await sync(snapshot())},1800);
})();
