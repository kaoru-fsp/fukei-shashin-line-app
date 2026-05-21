const fs = require('fs');

let content = fs.readFileSync('src/services/geminiReferenceService.ts', 'utf8');

// Replace gemini-3-flash-preview with gemini-2.5-flash
content = content.replace(/gemini-3-flash-preview/g, 'gemini-2.5-flash');

// Update fetchWeather to use open-meteo
const weatherReplacement = `export const fetchWeather = async (location: string, date: Date, coords?: {lat: number, lng: number}): Promise<ReferenceData['weather'] | null> => {
  const dateStr = date.toLocaleDateString('ja-JP');
  const cacheKey = \`weather_data_om_\${location}_\${dateStr}\`;
  const cached = getCachedData<ReferenceData['weather']>(cacheKey);
  if (cached) return cached;

  if (!coords) return null;

  try {
    const isoDate = date.toISOString().split('T')[0];
    const url = \`https://api.open-meteo.com/v1/forecast?latitude=\${coords.lat}&longitude=\${coords.lng}&hourly=temperature_2m,precipitation_probability,weather_code&timezone=Asia%2FTokyo&start_date=\${isoDate}&end_date=\${isoDate}\`;
    
    const res = await fetch(url);
    if (!res.ok) throw new Error("OpenMeteo error");
    const json = await res.json();
    
    // Parse OM data to our format
    const getWMOText = (code: number) => {
      if (code === 0) return "快晴";
      if (code === 1 || code === 2) return "晴れ時々曇り";
      if (code === 3) return "曇り";
      if (code === 45 || code === 48) return "霧";
      if (code >= 51 && code <= 55) return "霧雨";
      if (code >= 61 && code <= 65) return "雨";
      if (code >= 71 && code <= 77) return "雪";
      if (code >= 80 && code <= 82) return "にわか雨";
      if (code === 95 || code === 96 || code === 99) return "雷雨";
      return "曇り";
    };

    const targetIndices = [6, 9, 12, 15, 18, 21]; // Indices representing 6:00, 9:00, etc.
    const hourly = targetIndices.map(i => {
      const code = json.hourly.weather_code[i];
      const temp = json.hourly.temperature_2m[i];
      const pop = json.hourly.precipitation_probability[i] || 0;
      
      return {
        time: \`\${i}:00\`,
        weather: getWMOText(code),
        temp: \`\${Math.round(temp)}℃\`,
        pop: \`\${pop}%\`
      };
    });

    const maxPop = Math.max(...(json.hourly.precipitation_probability || []));
    const codes = json.hourly.weather_code.slice(6, 18); // Daytime codes
    const dominantCode = codes.sort((a,b) =>
          codes.filter(v => v===a).length
        - codes.filter(v => v===b).length
    ).pop() || 0;

    const data = {
      summary: getWMOText(dominantCode),
      precipitationProb: \`\${maxPop}%\`,
      hourly
    };
    
    setCachedData(cacheKey, data);
    return data;
  } catch (error) {
    console.error("Error fetching weather:", error);
    return null;
  }
};`;

content = content.replace(/export const fetchWeather = async \(location.*?catch \(error\) \{\n    console\.error\("Error fetching weather:", error\);\n    return null;\n  \}\n\};/s, weatherReplacement);


// Update fetchTideData to use open-meteo marine
const tideReplacement = `export const fetchTideData = async (location: string, date: Date, coords?: {lat: number, lng: number}): Promise<TideData> => {
  const dateStr = date.toLocaleDateString('ja-JP');
  const cacheKey = \`tides_om_\${location}_\${dateStr}\`;
  const cached = getCachedData<TideData>(cacheKey);
  if (cached) return cached;

  if (!coords) return { highTides: [], lowTides: [] };

  try {
    const isoDate = date.toISOString().split('T')[0];
    const url = \`https://marine-api.open-meteo.com/v1/marine?latitude=\${coords.lat}&longitude=\${coords.lng}&hourly=ocean_height&timezone=Asia%2FTokyo&start_date=\${isoDate}&end_date=\${isoDate}\`;
    
    const res = await fetch(url);
    if (!res.ok) throw new Error("OpenMeteo Marine error");
    const json = await res.json();
    
    const heights = json.hourly.ocean_height;
    const times = json.hourly.time;
    
    if (!heights || heights.length === 0 || heights[0] === null) {
      return { highTides: [], lowTides: [] }; // Inner land or unsupported
    }
    
    const highTides = [];
    const lowTides = [];
    
    // Find local maxima and minima
    for (let i = 1; i < heights.length - 1; i++) {
        if (heights[i] === null) continue;
        
        const prev = heights[i - 1];
        const next = heights[i + 1];
        const current = heights[i];
        
        if (prev !== null && next !== null) {
            const dateObj = new Date(times[i]);
            const timeStr = \`\${dateObj.getHours().toString().padStart(2, '0')}:\${dateObj.getMinutes().toString().padStart(2, '0')}\`;
            const levelCm = Math.round(current * 100);
            
            if (current > prev && current > next) {
                highTides.push({ time: timeStr, level: levelCm });
            } else if (current < prev && current < next) {
                lowTides.push({ time: timeStr, level: levelCm });
            }
        }
    }
    
    // Take at most 2 max/min per day and sort
    const data = {
      highTides: highTides.slice(0, 2),
      lowTides: lowTides.slice(0, 2)
    };
    
    setCachedData(cacheKey, data);
    return data;
  } catch (error) {
    console.error("Error fetching tide data:", error);
    return { highTides: [], lowTides: [] };
  }
};`;

content = content.replace(/export const fetchTideData = async \(location.*?catch \(error\) \{\n    console\.error\("Error fetching tide data:", error\);\n    return \{ highTides: \[\], lowTides: \[\] \};\n  \}\n\};/s, tideReplacement);

fs.writeFileSync('src/services/geminiReferenceService.ts', content);
