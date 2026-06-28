// Power Profile page - Xert-style power profile
import { apiGet } from './api.js';

export async function loadPowerProfile(root) {
    root.innerHTML = '<div class="page"><h1>Power Profile</h1><p>Loading...</p></div>';
    
    try {
        const data = await apiGet('/training/power-profile/');
        
        let html = `
            <div class="page">
                <h1>Power Profile</h1>
                <div class="card">
                    <p>Your power profile shows your physiological strengths based on best efforts.</p>
                </div>
        `;
        
        // Display profile data if available
        if (data && data.profile) {
            html += '<div class="card">';
            html += '<h3>Profile Data</h3>';
            html += '<table>';
            
            for (const [key, value] of Object.entries(data.profile)) {
                html += `<tr><td>${key}</td><td>${value || '-'}</td></tr>`;
            }
            
            html += '</table></div>';
        } else {
            html += '<div class="card"><p>No power data available. Upload activities with power data.</p></div>';
        }
        
        html += '</div>';
        root.innerHTML = html;
        
    } catch (e) {
        root.innerHTML = `<div class="page"><h1>Power Profile</h1><p class="error">Error: ${e.message}</p></div>`;
    }
}