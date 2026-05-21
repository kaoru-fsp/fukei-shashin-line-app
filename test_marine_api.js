const coords = { lat: 35.6895, lng: 139.6917 };
const isoDate = new Date().toISOString().split('T')[0];
const url = `https://marine-api.open-meteo.com/v1/marine?latitude=${coords.lat}&longitude=${coords.lng}&hourly=ocean_height&timezone=Asia%2FTokyo&start_date=${isoDate}&end_date=${isoDate}`;
fetch(url).then(r => r.json()).then(console.log).catch(console.error);
