let stockView=null;
const stockDay=$('#stockDay'), stockForm=$('#stockForm');
stockDay.max=localDay();stockForm.elements.day.max=localDay();

function renderStocks(view){
  stockView=view;stockDay.value=view.day;stockForm.elements.day.value=view.day;
  const days=view.snapshotDays||[],prior=days.filter(x=>x<view.day).at(-1),next=days.find(x=>x>view.day);
  $('#stockPrev').disabled=!prior;$('#stockNext').disabled=!next;
  $('#stockPrev').dataset.day=prior||'';$('#stockNext').dataset.day=next||'';
  const index=days.indexOf(view.day);
  $('#stockPageStatus').textContent=days.length?(index>=0?`第 ${index+1} / ${days.length} 个记录日`:`截至此日，共 ${days.filter(x=>x<=view.day).length} 个记录日`):'暂无记录';
  const active=view.positions.filter(x=>!x.closed);
  $('#stockActiveCount').textContent=`${active.length} 只`;
  $('#stockAsOfTotal').textContent=money(active.reduce((sum,x)=>sum+Number(x.market_value),0));
  $('#stockPositions').innerHTML=view.positions.length?view.positions.map(x=>`<div class="stock-row ${x.closed?'closed':''}"><div><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.symbol)} · ${x.closed?'已清仓于 '+escapeHtml(x.day):'最近记录 '+escapeHtml(x.day)}</small></div><strong class="money">${money(x.market_value)}</strong><button type="button" data-stock-symbol="${escapeHtml(x.symbol)}" data-stock-name="${escapeHtml(x.name)}">填写快照</button></div>`).join(''):'<div class="empty">这个日期还没有股票持仓。</div>';
  $('#stockRecords').innerHTML=view.records.length?view.records.map(x=>`<div class="stock-row ${Number(x.market_value)===0?'closed':''}"><div><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.symbol)} · ${Number(x.market_value)===0?'清仓':'持仓快照'}</small></div><strong class="money">${money(x.market_value)}</strong></div>`).join(''):'<div class="empty">当天没有新快照；上方状态沿用此前最近的记录。</div>';
}

async function loadStocks(day){
  const view=await api('/api/stocks?day='+encodeURIComponent(day||localDay()));
  if(!day&&view.snapshotDays.length&&view.snapshotDays.at(-1)!==view.day)return loadStocks(view.snapshotDays.at(-1));
  renderStocks(view);
}

stockDay.onchange=()=>loadStocks(stockDay.value).catch(x=>toast(x.message));
$('#stockPrev').onclick=e=>loadStocks(e.currentTarget.dataset.day).catch(x=>toast(x.message));
$('#stockNext').onclick=e=>loadStocks(e.currentTarget.dataset.day).catch(x=>toast(x.message));
$('#stockToday').onclick=()=>loadStocks(localDay()).catch(x=>toast(x.message));
$('#stockPositions').onclick=e=>{const button=e.target.closest('[data-stock-symbol]');if(!button)return;stockForm.elements.symbol.value=button.dataset.stockSymbol;stockForm.elements.name.value=button.dataset.stockName;stockForm.elements.market_value.value=stockView.positions.find(x=>x.symbol===button.dataset.stockSymbol)?.market_value||'';stockForm.scrollIntoView({behavior:'smooth',block:'center'})};

async function submitStock(close=false){
  const data=Object.fromEntries(new FormData(stockForm));
  if(close)data.market_value='0';
  if(!stockForm.elements.symbol.value||!stockForm.elements.name.value||!data.day||data.market_value===''){toast('请填写日期、股票代码、名称和金额');return}
  try{
    const result=await api('/api/stocks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    await Promise.all([load(),loadStocks(result.day)]);
    stockForm.elements.market_value.value='';
    toast(result.closed?'已记录清仓；请手动更新现金账户':'股票快照已保存');
  }catch(x){toast(x.message)}
}
stockForm.onsubmit=e=>{e.preventDefault();submitStock(false)};
$('#stockClose').onclick=()=>submitStock(true);
loadStocks().catch(x=>toast(x.message));
