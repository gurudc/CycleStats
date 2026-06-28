
import { apiGet, apiPost } from './api.js';
export async function loadActivities(root) {
    const data = await apiGet('/api/activities');
    root.innerHTML = `<div>Activities: ${JSON.stringify(data)}</div>`;
}
export async function deleteActivity(id) {
    await apiPost('/api/activities/delete', { id });
    alert('Deleted');
}
