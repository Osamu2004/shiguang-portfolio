const allocationForm = document.querySelector('#allocationPlanForm');

function updateAllocationDraft() {
  const weights = [...allocationForm.querySelectorAll('[data-target-key]')]
    .map(input => Number(input.value || 0));
  const sum = weights.reduce((a, b) => a + b, 0);
  const total = document.querySelector('#allocationWeightTotal');
  total.textContent = `权重合计 ${sum.toFixed(2)}%`;
  total.classList.toggle('invalid', sum !== 0 && Math.abs(sum - 100) > 0.0001);
  const budget = Number(allocationForm.elements.monthly_budget.value || 0);
  const spent = Number(allocationForm.elements.monthly_spent.value || 0);
  document.querySelector('#allocationRemaining').textContent = money(Math.max(0, budget - spent));
}

window.renderAllocationPlan = function renderAllocationPlan() {
  const plan = state.allocationPlan || {};
  document.querySelector('#allocationPlanMonth').textContent = `${plan.month || localDay().slice(0, 7)} · 本月`;
  allocationForm.elements.monthly_budget.value = plan.monthly_budget || '0.00';
  allocationForm.elements.monthly_spent.value = plan.monthly_spent || '0.00';
  const rows = plan.rows || [];
  document.querySelector('#allocationTargetRows').innerHTML = rows.length ? rows.map(row => `
    <div class="allocation-target-row">
      <div class="allocation-fund"><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.code || '无代码')} · 当前 ${money(row.current_value)}</small></div>
      <label><span class="sr-only">${escapeHtml(row.name)}目标权重</span><input data-target-key="${escapeHtml(row.key)}" type="number" min="0" max="100" step="0.01" inputmode="decimal" value="${escapeHtml(row.target_weight)}" required><span>%</span></label>
      <div class="allocation-weight-change">${Number(row.before_weight).toFixed(2)}% <span>→</span> ${plan.ready ? Number(row.after_weight).toFixed(2) + '%' : '待设置'}</div>
      <div class="allocation-buy money">${plan.ready ? money(row.buy_amount) : '—'}</div>
    </div>`).join('') : '<div class="empty compact">先在上方记录基金或 ETF 持仓，再设置目标权重。</div>';
  updateAllocationDraft();
  const summary = document.querySelector('#allocationPlanSummary');
  if (!rows.length) {
    summary.innerHTML = '<div class="allocation-plan-empty">暂无可规划的基金持仓。</div>';
  } else if (!plan.ready) {
    summary.innerHTML = `<div class="allocation-plan-empty">${plan.stale_targets ? '持仓已变化，请重新核对各基金权重并保存。' : '将目标权重合计设为 100%，保存后生成本月计划。'}</div>`;
  } else {
    const buys = [...rows].filter(row => Number(row.buy_amount) > 0)
      .sort((a, b) => Number(b.buy_amount) - Number(a.buy_amount));
    const message = Number(plan.remaining) <= 0
      ? '本月没有剩余额度。请核对已投入金额或调整预算。'
      : buys.length ? '' : '当前没有可执行的买入建议。';
    summary.innerHTML = `<div class="allocation-plan-totals"><div><small>本月剩余额度</small><strong class="money">${money(plan.remaining)}</strong></div><div><small>建议投入</small><strong class="money">${money(plan.allocated)}</strong></div><div><small>未分配</small><strong class="money">${money(plan.unallocated)}</strong></div></div>${message ? `<p>${message}</p>` : `<div class="allocation-order"><b>本月建议买入顺序</b>${buys.map((row, index) => `<div><span class="allocation-rank">${index + 1}</span><span>${escapeHtml(row.name)}${row.drawdown_pct ? `<small>近期净值回撤 ${escapeHtml(row.drawdown_pct)}% · 已提高优先级</small>` : ''}</span><strong class="money">${money(row.buy_amount)}</strong></div>`).join('')}</div>`}`;
  }
};

allocationForm.addEventListener('input', updateAllocationDraft);
allocationForm.addEventListener('submit', async event => {
  event.preventDefault();
  const target_weights = Object.fromEntries([...allocationForm.querySelectorAll('[data-target-key]')]
    .map(input => [input.dataset.targetKey, input.value]));
  const body = {
    monthly_budget: allocationForm.elements.monthly_budget.value,
    monthly_spent: allocationForm.elements.monthly_spent.value,
    target_weights,
  };
  const button = allocationForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api('/api/allocation-plan', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    await load();
    toast('月度配置计划已保存');
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
