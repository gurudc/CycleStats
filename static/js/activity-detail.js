
import { apiGet } from './api.js';
export async function openActivity(root, id) {
    const data = await apiGet(`/api/activities/${id}`);
    root.innerHTML = `<div>Activity: ${JSON.stringify(data)}</div>`;
}
