async function test() {
  const prompt = `あなたは風景写真・カメラの歴史に精通したジャーナリストです。
4月30日という日付に関連する、写真界の本物の歴史的出来事を正確に3つ選んでください。
必ず実在する出来事を選び、それぞれの出来事について詳しく解説されているWikipediaやカメラメーカーの公式サイト、あるいはGoogle検索結果へのURLを併記してください。
レスポンスは以下のJSON配列のみとし、それ以外の文章やマークダウンは一切含めないでください。
[{"event":"19xx年: 〇〇の誕生日", "url":"https://ja.wikipedia.org/wiki/〇〇"}]`;
  const res = await fetch("http://localhost:3000/api/gemini", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "generateContent", request: prompt })
  });
  console.log(res.status);
  console.log(await res.text());
}
test();
