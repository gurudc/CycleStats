// Power Curve page
import { apiGet } from './api.js';

export async function loadPowerCurve(root) {
    root.innerHTML = '<div class="page"><h1>Power Curve</h1><p>Loading...</p></div>';
    
    try {
        const data = await apiGet('/training/power-curve/');
        
        let html = `
            <div class="page">
                <h1>Power Curve</h1>
                <div class="card">
                    <p>Your power duration curve shows your best average power at various durations.</p>
                </div>
        `;
        
        // Add chart placeholder
        html += '<div class="card"><canvas id="power-curve-chart"></canvas></div>';
        
        html += '</div>';
        root.innerHTML = html;
        
        // If we have data, render chart
        if (data && data.best_efforts) {
            renderPowerCurveChart(data.best_efforts);
        }
        
    } catch (e) {
        root.innerHTML = `<div class="page"><h1>Power Curve</h1><p class="error">Error: ${e.message}</p></div>`;
    }
}

function renderPowerCurveChart(data) {
    const ctx = document.getElementById('power-curve-chart');
    if (!ctx) return;
    
    const labels = Object.keys(data).map(d => d + 's');
    const values = Object.values(data);
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Best Average Power (W)',
                data: values,
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                fill: true
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { color: '#e4e6ef' } }
            },
            scales: {
                y: { 
                    ticks: { color: '#8b8fa3' },
                    grid: { color: '#2a2d3a' }
                },
                x: { 
                    ticks: { color: '#8b8fa3' },
                    grid: { color: '#2a2d3a' }
                }
            }
        }
    });
}