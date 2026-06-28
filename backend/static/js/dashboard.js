
import { apiGet } from './api.js';
export async function loadDashboard(root) {
    const data = await apiGet('/api/dashboard');
    root.innerHTML = `<div>Dashboard Data: ${JSON.stringify(data)}</div>`;
}
