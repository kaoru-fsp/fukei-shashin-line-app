import http from 'http';

http.get('http://localhost:3000/api/contest-data', (res) => {
  let data = '';
  res.on('data', (chunk) => data += chunk);
  res.on('end', () => console.log(data.slice(0, 100)));
});
