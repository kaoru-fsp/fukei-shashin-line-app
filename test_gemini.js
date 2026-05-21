const prompt = "hello, respond with JSON {\"hello\":\"world\"}";
const request = {
  model: "gemini-2.5-flash",
  contents: prompt,
  config: { responseMimeType: "application/json" }
};

fetch("http://localhost:3000/api/gemini", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ action: "generateContent", request })
})
  .then(r => r.json())
  .then(console.log)
  .catch(console.error);
