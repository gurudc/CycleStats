// Settings page
import { apiGet, apiPost } from './api.js';

export async function loadSettings(root) {
    root.innerHTML = '<div class="page"><h1>Settings</h1><p>Loading...</p></div>';
    
    try {
        // Get current FTP
        const data = await apiGet('/training/ftp/');
        
        let html = `
            <div class="page">
                <h1>Settings</h1>
                
                <div class="card">
                    <h3>FTP (Functional Threshold Power)</h3>
                    <input type="number" id="ftp-input" value="${data?.ftp || 200}" />
                    <button onclick="updateFtp()">Update FTP</button>
                    <p class="muted">FTP is used for power zone calculations.</p>
                </div>
                
                <div class="card">
                    <h3>Account</h3>
                    <p>Username: admin</p>
                    <button onclick="logout()">Logout</button>
                </div>
            </div>
        `;
        
        root.innerHTML = html;
        
    } catch (e) {
        root.innerHTML = `<div class="page"><h1>Settings</h1><p class="error">Error: ${e.message}</p></div>`;
    }
}

window.updateFtp = async function() {
    const ftp = document.getElementById('ftp-input').value;
    try {
        await apiPost('/training/recompute?ftp=' + ftp, {});
        alert('FTP updated to ' + ftp + 'W');
    } catch (e) {
        alert('Error: ' + e.message);
    }
};

window.logout = async function() {
    try {
        await apiPost('/auth/logout', {});
        window.location.reload();
    } catch (e) {
        window.location.reload();
    }
};