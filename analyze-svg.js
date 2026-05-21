import fs from 'fs';

const files = [
  'src/assets/logo_fukeishashin-tree.svg',
  'src/assets/logo_fukeishashin.svg',
  'src/assets/logo_publishing.svg',
  'src/assets/logo_tree.svg',
  'src/assets/logo_kaze.svg'
];

for (const file of files) {
  if (!fs.existsSync(file)) continue;
  let content = fs.readFileSync(file, 'utf8');
  console.log("Analyzing " + file);
  
  // Extract all numbers
  const numRegex = /[-+]?[0-9]*\.?[0-9]+/g;
  let matches;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  let x = 0, y = 0;
  
  // This is a naive heuristic just to see the range of coordinates
  while ((matches = numRegex.exec(content)) !== null) {
    const val = parseFloat(matches[0]);
    if (val > 200 && val < 2000) { // arbitrary bound based on 1920x1080
      // Just collect all numbers, even Y works
      if (val < minX) minX = val;
      if (val > maxX) maxX = val;
    }
  }
  console.log(`${file}: Extracted number range: ${minX} to ${maxX}`);
}
