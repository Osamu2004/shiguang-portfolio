let holdingCalendar=null;
const holdingDay=$('#holdingDay'), datedHoldingForm=$('#holdingForm');
holdingDay.max=localDay();datedHoldingForm.elements.day.max=localDay();

function renderHoldingCalendar(view,syncFormDay=true){
  holdingCalendar=view;holdingDay.value=view.day;
  if(syncFormDay)datedHoldingForm.elements.day.value=view.day;
  const days=view.snapshotDays||[],prior=days.filter(x=>x<view.day).at(-1),next=days.find(x=>x>view.day);
  $('#holdingPrev').disabled=!prior;$('#holdingNext').disabled=!next;
  $('#holdingPrev').dataset.day=prior||'';$('#holdingNext').dataset.day=next||'';
  const page=days.indexOf(view.day);
  $('#holdingPageStatus').textContent=days.length?(page>=0?`第 ${page+1} / ${days.length} 个记录日`:`截至此日，共 ${days.filter(x=>x<=view.day).length} 个记录日`):'暂无记录';
  const active=view.positions.filter(x=>!x.closed);
  $('#holdingAsOfCount').textContent=`${active.length} 只`;
  $('#holdingAsOfTotal').textContent=money(active.reduce((sum,x)=>sum+Number(x.market_value),0));
  $('#holdingCalendarRows').innerHTML=view.positions.length?view.positions.map(x=>{
    const profit=Number(x.holding_profit),rate=Number(x.return_rate);
    const metrics=x.closed
      ?`<div class="calendar-metrics"><span class="calendar-value">市值 <span class="money">${money(0)}</span></span><span class="calendar-closed-rate">已清仓 · 持有收益率不适用</span></div>`
      :`<div class="calendar-metrics"><span class="calendar-value">市值 <span class="money">${money(x.market_value)}</span></span><span class="calendar-profit ${marketClass(profit)}">持有收益 <span class="money">${profit>=0?'+':''}${money(profit)}</span></span><span class="calendar-rate ${marketClass(rate)}">持有收益率 ${rate>=0?'+':''}${rate.toFixed(2)}%</span></div>`;
    return `<div class="calendar-row ${x.closed?'closed':''}"><div class="calendar-identity"><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.code||'无代码')} · ${escapeHtml(x.category)} · ${x.closed?'已清仓'+(x.closed_on?'于 '+escapeHtml(x.closed_on):''):'最近盘点 '+escapeHtml(x.day)}</small></div>${metrics}<button type="button" data-key="${escapeHtml(x.holding_key)}">填写快照</button></div>`;
  }).join(''):'<div class="empty">截至该日期没有基金或 ETF 持仓。</div>';
}

async function loadHoldingCalendar(day,syncFormDay=true){
  const view=await api('/api/holdings/calendar?day='+encodeURIComponent(day||localDay()));
  renderHoldingCalendar(view,syncFormDay);
}
window.refreshHoldingCalendar=()=>loadHoldingCalendar(holdingDay.value||localDay(),false).catch(x=>toast(x.message));
holdingDay.onchange=()=>loadHoldingCalendar(holdingDay.value).catch(x=>toast(x.message));
$('#holdingPrev').onclick=e=>loadHoldingCalendar(e.currentTarget.dataset.day).catch(x=>toast(x.message));
$('#holdingNext').onclick=e=>loadHoldingCalendar(e.currentTarget.dataset.day).catch(x=>toast(x.message));
$('#holdingToday').onclick=()=>loadHoldingCalendar(localDay()).catch(x=>toast(x.message));
$('#holdingCalendarRows').onclick=e=>{
  const button=e.target.closest('[data-key]');if(!button)return;
  const row=holdingCalendar.positions.find(x=>x.holding_key===button.dataset.key);if(!row)return;
  datedHoldingForm.elements.code.value=row.code||'';
  datedHoldingForm.elements.name.value=row.name;
  if([...datedHoldingForm.elements.category.options].some(x=>x.value===row.category))datedHoldingForm.elements.category.value=row.category;
  datedHoldingForm.elements.market_value.value=row.market_value;
  datedHoldingForm.elements.holding_profit.value=row.closed?'0':row.holding_profit;
  datedHoldingForm.elements.return_rate.value=row.closed?'0':row.return_rate;
  datedHoldingForm.scrollIntoView({behavior:'smooth',block:'center'});
};

async function saveDatedHolding(close=false){
  const data=Object.fromEntries(new FormData(datedHoldingForm));
  if(close){data.market_value='0';data.holding_profit='0';data.return_rate='0'}
  if(!data.day||!data.name){toast('请填写日期和基金 / ETF 名称');return}
  try{
    const result=await api('/api/holdings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    await load();
    await loadHoldingCalendar(data.day);
    verifyHint.className='verify-hint valid';verifyHint.textContent='平台原始值模式 · 三项分别保存';
    datedHoldingForm.elements.market_value.value='';
    toast(close?'已记录清仓；请手动更新现金账户':result.mode==='updated'?'该日快照已更新':'该日快照已保存');
  }catch(x){verifyHint.className='verify-hint invalid';verifyHint.textContent=x.message;toast(x.message)}
}
datedHoldingForm.onsubmit=e=>{e.preventDefault();saveDatedHolding(false)};
$('#holdingClear').onclick=()=>saveDatedHolding(true);
loadHoldingCalendar().catch(x=>toast(x.message));
