
import { apiGet } from './api.js';
export async function loadHealth(root) {
    const data = await apiGet('/api/health');
    root.innerHTML = `<div>Health: ${JSON.stringify(data)}</div>`;
}
