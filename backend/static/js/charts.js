
export function destroyChart(chart) { if (chart) chart.destroy(); }
export function renderHealthChart(ctx, data) { return new Chart(ctx, { type: 'line', data }); }
export function renderStreamChart(ctx, data) { return new Chart(ctx, { type: 'line', data }); }
