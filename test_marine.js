async function test() {
  const url = `https://marine-api.open-meteo.com/v1/marine?latitude=35.3000&longitude=139.4833&hourly=wave_height,wave_period&timezone=Asia%2FTokyo`;
  const text = await fetch(url).then(r => r.text());
  console.log("Marine keys:", text.slice(0, 500));
}
test();
