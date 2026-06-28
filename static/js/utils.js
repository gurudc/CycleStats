
export function formatDate(d) { return new Date(d).toLocaleDateString(); }
export function formatTime(s) { return new Date(s * 1000).toISOString().substr(11, 8); }
export function sportBadge(type) { return type === 'ride' ? '🚴' : '🏃'; }
