import fs from "fs";

const filepath = "src/services/geminiReferenceService.ts";
let content = fs.readFileSync(filepath, "utf8");

content = content.replace(/model:\s*"gemini-2\.5-flash"/g, 'model: "gemini-3-flash-preview"');
// I will keep the thinkingConfig because it is supported in 3-flash-preview.

fs.writeFileSync(filepath, content);
console.log("Updated gemini-2.5-flash to gemini-3-flash-preview in geminiReferenceService.ts");
