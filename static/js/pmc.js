
import { apiGet } from './api.js';
export async function loadPMC(root) {
    const data = await apiGet('/api/pmc');
    root.innerHTML = `<div>PMC: ${JSON.stringify(data)}</div>`;
}
