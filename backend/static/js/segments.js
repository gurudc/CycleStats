// Segments page - Strava-style segments
import { apiGet, apiPost } from './api.js';

let segments = [];

export async function loadSegments(root) {
    root.innerHTML = '<div class="page"><h1>Segments</h1><p>Loading...</p></div>';
    
    try {
        const data = await apiGet('/segments/');
        segments = data;
        renderSegments(root);
    } catch (e) {
        root.innerHTML = `<div class="page"><h1>Segments</h1><p class="error">Error: ${e.message}</p></div>`;
    }
}

function renderSegments(root) {
    if (!segments || segments.length === 0) {
        root.innerHTML = `
            <div class="page">
                <h1>Segments</h1>
                <div class="card">
                    <p>No segments defined yet.</p>
                    <p>Create segments to track your best times on specific routes.</p>
                    <button onclick="createSegmentPrompt()">Create Segment</button>
                </div>
            </div>
        `;
        return;
    }
    
    let html = `
        <div class="page">
            <h1>Segments</h1>
            <div class="segments-list">
    `;
    
    for (const seg of segments) {
        html += `
            <div class="card segment-card" onclick="showSegmentLeaderboard(${seg.id})">
                <h3>${seg.name}</h3>
                <p>${seg.distance_m || '?'}m • ${seg.sport}</p>
            </div>
        `;
    }
    
    html += `
            </div>
            <div id="leaderboard"></div>
        </div>
    `;
    
    root.innerHTML = html;
}

window.showSegmentLeaderboard = async function(segmentId) {
    const lbDiv = document.getElementById('leaderboard');
    if (!lbDiv) return;
    
    lbDiv.innerHTML = '<p>Loading leaderboard...</p>';
    
    try {
        const data = await apiGet(`/segments/${segmentId}/leaderboard`);
        renderLeaderboard(lbDiv, data);
    } catch (e) {
        lbDiv.innerHTML = `<p class="error">Error: ${e.message}</p>`;
    }
};

function renderLeaderboard(root, data) {
    const { segment, results } = data;
    
    if (!segment) {
        root.innerHTML = '<p>Segment not found</p>';
        return;
    }
    
    let html = `
        <div class="card">
            <h2>${segment.name}</h2>
            <p>${segment.distance_m || 0}m • ${segment.sport}</p>
            
            <h3>Personal Bests</h3>
            <table class="leaderboard">
                <tr><th>#</th><th>Date</th><th>Time</th></tr>
    `;
    
    if (!results || results.length === 0) {
        html += '<tr><td colspan="3">No efforts yet</td></tr>';
    } else {
        for (let i = 0; i < results.length; i++) {
            const r = results[i];
            const date = r.date ? new Date(r.date).toLocaleDateString() : '-';
            const time = r.time_s ? formatTime(r.time_s) : '-';
            html += `<tr><td>${i + 1}</td><td>${date}</td><td>${time}</td></tr>`;
        }
    }
    
    html += '</table></div>';
    root.innerHTML = html;
}

window.createSegmentPrompt = function() {
    const name = prompt('Segment name:');
    if (!name) return;
    
    const distance = prompt('Approximate distance in meters:', '1000');
    const sport = prompt('Sport (cycling/running):', 'cycling');
    
    if (name && distance) {
        createSegment(name, sport, parseInt(distance));
    }
};

async function createSegment(name, sport, distance) {
    try {
        await apiPost('/segments/', {
            name,
            sport,
            distance_m: distance
        });
        loadSegments(document.getElementById('page-root'));
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}