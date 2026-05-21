const fs = require('fs');
let content = fs.readFileSync('src/services/geminiReferenceService.ts', 'utf8');

content = content.replace(/const jsonStr = response\.text\.trim\(\);/g, "const textVal = typeof response.text === 'function' ? response.text() : response.text;\n    const jsonStr = textVal.replace(/```json/g, '').replace(/```/g, '').trim();");

content = content.replace(/const data = JSON\.parse\(response\.text\.trim\(\)\)/g, "const textVal = typeof response.text === 'function' ? response.text() : response.text;\n    const data = JSON.parse(textVal.replace(/```json/g, '').replace(/```/g, '').trim())");

fs.writeFileSync('src/services/geminiReferenceService.ts', content);
