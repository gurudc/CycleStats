// Segments - Strava-style segments
import { apiGet, apiPost } from './api.js';

export async function loadSegments(root) {
    root.innerHTML = '<div class="page"><h1>Segments</h1><p>Loading...</p></div>';
    
    try {
        const data = await apiGet('/segments/');
        renderSegments(root, data);
    } catch (e) {
        root.innerHTML = `<div class="page"><h1>Segments</h1><p class="error">Error: ${e.message}</p></div>`;
    }
}

function renderSegments(root, segments) {
    if (!segments || segments.length === 0) {
        root.innerHTML = `
            <div class="page">
                <h1>Segments</h1>
                <div class="card">
                    <p>No segments yet. Create one to track your best times.</p>
                </div>
            </div>
        `;
        return;
    }
    
    let html = `<div class="page"><h1>Segments</h1>`;
    for (const seg of segments) {
        html += `<div class="card"><h3>${seg.name}</h3><p>${seg.distance_m || '?'}m</p></div>`;
    }
    html += '</div>';
    root.innerHTML = html;
}